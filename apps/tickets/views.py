from datetime import timedelta

import stripe
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.core.pagination import StandardResultsPagination
from apps.core.permissions import IsAdmin

from .constants import (
    LEAGUE_WIDE_CAPS,
    MATCHDAY_TIERS,
    MAX_WEEK_NUMBER,
    MIN_WEEK_NUMBER,
    PURCHASABLE_TIERS,
    TIER_LABELS,
    TIER_PRICES_CENTS,
)
from .models import TicketOrder
from .serializers import AdminTicketSerializer, MyTicketSerializer
from .services import (
    InvalidTicketToken,
    SoldOut,
    remaining_bundle_capacity,
    remaining_capacity,
    reserve_capacity,
    verify_qr_token,
)

CHECKOUT_SESSION_TTL_MINUTES = 30


def _build_product_name(tier, division, week_number):
    label = TIER_LABELS[tier]
    if tier in MATCHDAY_TIERS:
        division_label = "North Division" if division == TicketOrder.Division.NORTH else "South Division"
        return f"{division_label} — {label} (Week {week_number})"
    return label


def _parse_checkout_input(data):
    """Validates and normalizes the checkout request body. Returns (fields_dict, error_message)."""
    tier = (data.get("tier") or "").strip()
    if tier not in PURCHASABLE_TIERS:
        return None, "Invalid or unavailable ticket tier."

    division = ""
    week_number = None

    if tier in MATCHDAY_TIERS:
        division = (data.get("division") or "").strip()
        if division not in (TicketOrder.Division.NORTH, TicketOrder.Division.SOUTH):
            return None, "A valid division is required for this pass."

        try:
            week_number = int(data.get("week_number"))
        except (TypeError, ValueError):
            return None, "A valid week number is required for this pass."
        if not (MIN_WEEK_NUMBER <= week_number <= MAX_WEEK_NUMBER):
            return None, f"Week must be between {MIN_WEEK_NUMBER} and {MAX_WEEK_NUMBER}."

    # Apparel size / fulfillment method are no longer collected at checkout —
    # the Supporter Bundle ships without a pre-purchase size/fulfillment
    # picker. TicketOrder.apparel_size/fulfillment_method stay blank.
    return {
        "tier": tier,
        "division": division,
        "week_number": week_number,
    }, None


class TicketCheckoutView(APIView):
    """
    POST /api/v1/tickets/checkout/

    Public endpoint (optionally authenticated — ties the ticket to the
    account when a valid JWT is sent). Reserves capacity for the requested
    tier/bucket, creates a Stripe Checkout Session, and records the order as
    PENDING before the buyer ever reaches Stripe — tickets are non-refundable,
    so the capacity hold must exist before payment, not after.
    """

    permission_classes = [AllowAny]
    authentication_classes = [JWTAuthentication]

    def post(self, request):
        fields, error = _parse_checkout_input(request.data)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        cancel_url = (request.data.get("cancel_url", "") or "").strip()
        if not cancel_url:
            cancel_url = f"{settings.FRONTEND_BASE_URL}/tickets"

        amount_cents = TIER_PRICES_CENTS[fields["tier"]]
        product_name = _build_product_name(fields["tier"], fields["division"], fields["week_number"])

        user = request.user if request.user and request.user.is_authenticated else None

        stripe.api_key = settings.STRIPE_SECRET_KEY

        try:
            with transaction.atomic():
                try:
                    reserve_capacity(fields["tier"], fields["division"], fields["week_number"])
                except SoldOut as e:
                    return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

                expires_at = int((timezone.now() + timedelta(minutes=CHECKOUT_SESSION_TTL_MINUTES)).timestamp())

                session = stripe.checkout.Session.create(
                    payment_method_types=["card"],
                    line_items=[{
                        "price_data": {
                            "currency": "usd",
                            "product_data": {"name": product_name},
                            "unit_amount": amount_cents,
                        },
                        "quantity": 1,
                    }],
                    mode="payment",
                    metadata={"type": "ticket_order"},
                    success_url=f"{settings.FRONTEND_BASE_URL}/tickets/order/success?session_id={{CHECKOUT_SESSION_ID}}",
                    cancel_url=cancel_url,
                    expires_at=expires_at,
                )

                TicketOrder.objects.create(
                    user=user,
                    stripe_session_id=session.id,
                    tier=fields["tier"],
                    division=fields["division"],
                    week_number=fields["week_number"],
                    product_name=product_name,
                    amount_cents=amount_cents,
                    status=TicketOrder.Status.PENDING,
                )
        except stripe.error.StripeError:
            return Response(
                {"detail": "Payment service unavailable. Please try again later."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response({"checkout_url": session.url})


class TicketAvailabilityView(APIView):
    """
    GET /api/v1/tickets/availability/?division=north&week=3
    GET /api/v1/tickets/availability/?tier=season_pass

    Public, unauthenticated — mirrors apps/kits/views.py::KitStatusView's
    pattern of a plain, no-serializer availability check.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        tier = request.query_params.get("tier")

        if tier in LEAGUE_WIDE_CAPS:
            return Response({"remaining": remaining_capacity(tier)})

        division = request.query_params.get("division", "")
        week_param = request.query_params.get("week")

        if division not in (TicketOrder.Division.NORTH, TicketOrder.Division.SOUTH) or not week_param:
            return Response(
                {"detail": "Provide either tier=<league-wide tier>, or division and week for a matchday."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            week_number = int(week_param)
        except ValueError:
            return Response({"detail": "Invalid week."}, status=status.HTTP_400_BAD_REQUEST)
        if not (MIN_WEEK_NUMBER <= week_number <= MAX_WEEK_NUMBER):
            return Response({"detail": "Invalid week."}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "matchday_remaining": remaining_capacity(TicketOrder.Tier.SINGLE_MATCH, division, week_number),
            "bundle_remaining": remaining_bundle_capacity(division, week_number),
        })


class TicketBySessionView(APIView):
    """
    GET /api/v1/tickets/by-session/<stripe_session_id>/

    Public — success-page lookup right after checkout. Trusts the
    unguessable Stripe session id as the capability token, the same trust
    model Stripe's own success_url?session_id={CHECKOUT_SESSION_ID}
    convention already relies on.
    """

    permission_classes = [AllowAny]

    def get(self, request, session_id):
        ticket = TicketOrder.objects.filter(stripe_session_id=session_id).exclude(
            status=TicketOrder.Status.PENDING
        ).first()
        if ticket is None:
            return Response({"detail": "Ticket not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(MyTicketSerializer(ticket).data)


class MyTicketsView(APIView):
    """GET /api/v1/tickets/my/ — the authenticated user's ticket wallet."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        qs = TicketOrder.objects.filter(
            Q(user=user) | Q(user__isnull=True, email__iexact=user.email),
        ).exclude(status=TicketOrder.Status.PENDING)
        return Response(MyTicketSerializer(qs, many=True).data)


class TicketCheckInView(APIView):
    """
    POST /api/v1/tickets/check-in/  { "token": "<scanned qr token>" }

    Admin-only (gate staff log in as admin — no separate staff role exists
    in this project today). Scanning twice is not an error: the second scan
    returns already_checked_in=true with the original timestamp.
    """

    permission_classes = [IsAdmin]

    def post(self, request):
        token = (request.data.get("token") or "").strip()
        if not token:
            return Response({"detail": "token is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            ticket_id = verify_qr_token(token)
        except InvalidTicketToken:
            return Response({"detail": "Invalid QR code."}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            ticket = TicketOrder.objects.select_for_update().filter(id=ticket_id).first()
            if ticket is None:
                return Response({"detail": "Ticket not found."}, status=status.HTTP_404_NOT_FOUND)

            if ticket.status == TicketOrder.Status.PENDING:
                return Response({"detail": "This ticket was never completed."}, status=status.HTTP_400_BAD_REQUEST)

            already_checked_in = ticket.status == TicketOrder.Status.CHECKED_IN
            if not already_checked_in:
                ticket.status = TicketOrder.Status.CHECKED_IN
                ticket.checked_in_at = timezone.now()
                ticket.checked_in_by = request.user
                ticket.save(update_fields=["status", "checked_in_at", "checked_in_by"])

        return Response({
            "already_checked_in": already_checked_in,
            "checked_in_at": ticket.checked_in_at,
            "checked_in_by": ticket.checked_in_by.name if ticket.checked_in_by else "",
            "product_name": ticket.product_name,
            "buyer_name": ticket.user.name if ticket.user else "",
        })


class AdminTicketListView(APIView):
    """GET /api/v1/admin/tickets/ — every completed ticket purchase, who holds it, and its status."""

    permission_classes = [IsAdmin]

    def get(self, request):
        qs = (
            TicketOrder.objects
            .exclude(status=TicketOrder.Status.PENDING)
            .select_related("user", "checked_in_by")
            .order_by("-created_at")
        )

        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        tier_filter = request.query_params.get("tier")
        if tier_filter:
            qs = qs.filter(tier=tier_filter)

        paginator = StandardResultsPagination()
        page = paginator.paginate_queryset(qs, request)
        if page is not None:
            return paginator.get_paginated_response(AdminTicketSerializer(page, many=True).data)
        return Response(AdminTicketSerializer(qs, many=True).data)
