import logging

import stripe
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsAdmin
from apps.core.pagination import StandardResultsPagination

from .models import Payment
from .serializers import AdminPaymentSerializer, PaymentStatusSerializer
from .services import create_checkout_session, verify_webhook

logger = logging.getLogger(__name__)


class InitiatePaymentView(APIView):
    """
    GET /api/v1/payments/initiate/

    Creates a Stripe Checkout Session and returns the hosted checkout URL.
    The frontend redirects the customer to that URL to complete payment.
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

        try:
            checkout_url = create_checkout_session(
                reference_number=payment.reference_number,
                amount=str(payment.amount),
            )
        except stripe.error.StripeError as e:
            logger.error("Stripe error creating checkout session: %s", e)
            return Response(
                {"detail": "Payment service unavailable. Please try again later."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response({"checkout_url": checkout_url})


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

    Stripe webhook endpoint. Stripe POSTs signed events here after payment.
    We verify the signature using the raw request body before processing.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        payload    = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")

        try:
            event = verify_webhook(payload, sig_header)
        except (ValueError, stripe.error.SignatureVerificationError):
            logger.warning("Stripe webhook received with invalid signature")
            return Response({"detail": "Invalid signature."}, status=status.HTTP_400_BAD_REQUEST)

        event_type = event["type"]
        session    = event["data"]["object"]

        logger.info("Stripe webhook: type=%s session=%s", event_type, getattr(session, "id", None))

        if event_type == "checkout.session.completed":
            self._handle_completed(session)
        elif event_type == "checkout.session.expired":
            self._handle_expired(session)

        return Response({"detail": "OK"})

    def _handle_completed(self, session):
        reference_number = getattr(session, "client_reference_id", None)
        transaction_id   = getattr(session, "id", None)

        try:
            payment = Payment.objects.get(reference_number=reference_number)
        except Payment.DoesNotExist:
            logger.error("Stripe webhook: no payment found for ref=%s", reference_number)
            return

        payment.status         = Payment.Status.PAID
        payment.transaction_id = transaction_id
        payment.paid_at        = timezone.now()
        payment.save(update_fields=["status", "transaction_id", "paid_at", "updated_at"])
        logger.info("Payment marked paid: ref=%s txn=%s", reference_number, transaction_id)

    def _handle_expired(self, session):
        reference_number = getattr(session, "client_reference_id", None)

        try:
            payment = Payment.objects.get(reference_number=reference_number)
        except Payment.DoesNotExist:
            return

        if payment.status == Payment.Status.PENDING:
            payment.status = Payment.Status.CANCELLED
            payment.save(update_fields=["status", "updated_at"])
            logger.info("Payment marked cancelled (expired): ref=%s", reference_number)


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
