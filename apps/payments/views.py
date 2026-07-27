import logging

from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsAdmin
from apps.core.pagination import StandardResultsPagination

from .models import Payment
from .serializers import AdminPaymentSerializer, PaymentStatusSerializer
from .services import build_hpp_form, verify_callback

logger = logging.getLogger(__name__)


class InitiatePaymentView(APIView):
    """
    GET /api/v1/payments/initiate/

    Returns signed form fields for the BoA Hosted Payments Page.
    The frontend auto-POSTs these to the HPP URL.

    Rules:
    - User must have signed the waiver.
    - If already PAID → 400.
    - If no record or FAILED/CANCELLED → (re)create/reset to PENDING and return form.
    - If PENDING → return fresh form fields (allow retry).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        if user.role == "admin":
            return Response(
                {"detail": "Admins do not pay a registration fee."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if not hasattr(user, "waiver_signature"):
            return Response(
                {"detail": "You must sign the waiver before paying."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        payment = Payment.objects.filter(user=user).first()

        if payment and payment.status == Payment.Status.PAID:
            return Response(
                {"detail": "Registration fee already paid."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if payment is None:
            payment = Payment.objects.create(
                user=user,
                reference_number=str(user.id),
            )
        elif payment.status in (Payment.Status.FAILED, Payment.Status.CANCELLED):
            payment.status = Payment.Status.PENDING
            payment.save(update_fields=["status", "updated_at"])

        form_data = build_hpp_form(
            reference_number=payment.reference_number,
            amount=str(payment.amount),
        )
        return Response(form_data)


class MyPaymentView(APIView):
    """
    GET /api/v1/payments/me/

    Returns the current user's payment record, or null if none exists yet.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        payment = Payment.objects.filter(user=request.user).first()
        if payment is None:
            return Response({"payment": None})
        return Response({"payment": PaymentStatusSerializer(payment).data})


@method_decorator(csrf_exempt, name="dispatch")
class PaymentCallbackView(APIView):
    """
    POST /api/v1/payments/callback/

    Server-to-server notification from BoA after payment processing.
    No auth — BoA posts directly from their servers.
    We verify the HMAC-SHA256 signature before updating the record.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    parser_classes = [FormParser, MultiPartParser]

    def post(self, request):
        data = request.data

        if not verify_callback(data):
            logger.warning("BoA callback received with invalid signature")
            return Response({"detail": "Invalid signature."}, status=status.HTTP_400_BAD_REQUEST)

        reference_number = data.get("req_reference_number") or data.get("reference_number")
        decision         = data.get("decision", "").upper()
        transaction_id   = data.get("transaction_id", "")
        reason_code      = data.get("reason_code", "")

        logger.info(
            "BoA callback: ref=%s decision=%s reason=%s txn=%s",
            reference_number, decision, reason_code, transaction_id,
        )

        try:
            payment = Payment.objects.get(reference_number=reference_number)
        except Payment.DoesNotExist:
            logger.error("BoA callback: no payment found for ref=%s", reference_number)
            return Response({"detail": "Payment record not found."}, status=status.HTTP_404_NOT_FOUND)

        if decision == "ACCEPT":
            payment.status         = Payment.Status.PAID
            payment.transaction_id = transaction_id
            payment.paid_at        = timezone.now()
        elif decision == "CANCEL":
            payment.status = Payment.Status.CANCELLED
        else:
            payment.status = Payment.Status.FAILED

        payment.save(update_fields=["status", "transaction_id", "paid_at", "updated_at"])
        return Response({"detail": "OK"})


class AdminPaymentListView(APIView):
    """
    GET /api/v1/admin/payments/

    Lists all players/captains who have initiated payment, with their status.
    Supports ?status=pending|paid|failed|cancelled filter.
    """
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        qs = (
            Payment.objects
            .select_related("user")
            .order_by("-created_at")
        )

        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        paginator = StandardResultsPagination()
        page = paginator.paginate_queryset(qs, request)
        if page is not None:
            return paginator.get_paginated_response(AdminPaymentSerializer(page, many=True).data)
        return Response(AdminPaymentSerializer(qs, many=True).data)
