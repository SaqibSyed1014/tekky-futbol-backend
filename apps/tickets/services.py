import base64
import uuid
from io import BytesIO

import qrcode
from django.core.signing import BadSignature, Signer

from .constants import BUNDLE_SUB_CAP, LEAGUE_WIDE_CAPS, MATCHDAY_CAP
from .models import CapacityBucket, TicketOrder

QR_SIGNING_SALT = "tickets.checkin"


class SoldOut(Exception):
    """Raised when a tier/bucket has no remaining capacity."""


class InvalidTicketToken(Exception):
    """Raised when a scanned QR token fails signature verification."""


# ---------------------------------------------------------------------------
# Capacity
# ---------------------------------------------------------------------------

_ACTIVE_STATUSES = [TicketOrder.Status.PENDING, TicketOrder.Status.PAID, TicketOrder.Status.CHECKED_IN]


def _acquire_bucket_lock(key: str) -> None:
    """
    Serializes concurrent capacity checks for the same bucket. Must be called
    inside transaction.atomic() — the lock releases automatically when that
    transaction commits or rolls back.

    get_or_create() is itself race-safe (key is a primary key, so a
    simultaneous duplicate insert raises IntegrityError, which Django
    catches internally and re-fetches) — this is what closes the one gap a
    plain select_for_update() can't: two simultaneous *first-ever*
    reservations against a bucket with no TicketOrder rows yet to lock.
    """
    CapacityBucket.objects.get_or_create(key=key)
    CapacityBucket.objects.select_for_update().get(key=key)


def reserve_capacity(tier: str, division: str = "", week_number: int | None = None) -> None:
    """
    Must be called inside transaction.atomic(), before creating the Stripe
    checkout session and before saving the PENDING TicketOrder row. Raises
    SoldOut if no capacity remains for the requested tier/bucket.

    Counts PENDING + PAID orders (not just PAID) so a second buyer can't
    reach Stripe for a slot that's already mid-checkout for someone else —
    tickets are non-refundable, so there's no way to safely unwind an
    oversold sale after the fact.
    """
    if tier in (TicketOrder.Tier.SINGLE_MATCH, TicketOrder.Tier.SUPPORTER_BUNDLE):
        _acquire_bucket_lock(f"ticket-matchday:{division}:{week_number}")

        matchday_qs = TicketOrder.objects.filter(
            division=division,
            week_number=week_number,
            tier__in=[TicketOrder.Tier.SINGLE_MATCH, TicketOrder.Tier.SUPPORTER_BUNDLE],
            status__in=_ACTIVE_STATUSES,
        )
        if matchday_qs.count() >= MATCHDAY_CAP:
            raise SoldOut("This matchday is sold out.")

        if tier == TicketOrder.Tier.SUPPORTER_BUNDLE:
            bundle_count = matchday_qs.filter(tier=TicketOrder.Tier.SUPPORTER_BUNDLE).count()
            if bundle_count >= BUNDLE_SUB_CAP:
                raise SoldOut(
                    "Supporter Bundles are sold out for this matchday — "
                    "Single Match Passes may still be available."
                )
        return

    cap = LEAGUE_WIDE_CAPS.get(tier)
    if cap is None:
        raise ValueError(f"Unknown ticket tier: {tier}")

    _acquire_bucket_lock(f"ticket-tier:{tier}")
    count = TicketOrder.objects.filter(tier=tier, status__in=_ACTIVE_STATUSES).count()
    if count >= cap:
        raise SoldOut("This pass is sold out.")


def remaining_capacity(tier: str, division: str = "", week_number: int | None = None) -> int:
    """Public, read-only version of the same counting logic — used by the availability endpoint."""
    if tier in (TicketOrder.Tier.SINGLE_MATCH, TicketOrder.Tier.SUPPORTER_BUNDLE):
        matchday_count = TicketOrder.objects.filter(
            division=division,
            week_number=week_number,
            tier__in=[TicketOrder.Tier.SINGLE_MATCH, TicketOrder.Tier.SUPPORTER_BUNDLE],
            status__in=_ACTIVE_STATUSES,
        ).count()
        return max(0, MATCHDAY_CAP - matchday_count)

    cap = LEAGUE_WIDE_CAPS.get(tier)
    if cap is None:
        raise ValueError(f"Unknown ticket tier: {tier}")
    count = TicketOrder.objects.filter(tier=tier, status__in=_ACTIVE_STATUSES).count()
    return max(0, cap - count)


def remaining_bundle_capacity(division: str, week_number: int | None) -> int:
    """Remaining Supporter Bundle slots — the smaller sub-cap inside the shared matchday pool."""
    bundle_count = TicketOrder.objects.filter(
        division=division,
        week_number=week_number,
        tier=TicketOrder.Tier.SUPPORTER_BUNDLE,
        status__in=_ACTIVE_STATUSES,
    ).count()
    remaining_in_pool = remaining_capacity(TicketOrder.Tier.SINGLE_MATCH, division, week_number)
    return max(0, min(BUNDLE_SUB_CAP - bundle_count, remaining_in_pool))


# ---------------------------------------------------------------------------
# QR codes
# ---------------------------------------------------------------------------

def make_qr_token(ticket_id) -> str:
    """
    HMAC-signs the ticket id using the app's existing SECRET_KEY. Not a
    TimestampSigner — a ticket bought in week 1 for a week-14 match must
    still scan successfully in week 14, so the token itself never expires
    (whether the ticket is usable is tracked by TicketOrder.status instead).
    """
    return Signer(salt=QR_SIGNING_SALT).sign(str(ticket_id))


def verify_qr_token(token: str) -> uuid.UUID:
    """Raises InvalidTicketToken if the token was tampered with or malformed."""
    try:
        unsigned = Signer(salt=QR_SIGNING_SALT).unsign(token)
        return uuid.UUID(unsigned)
    except (BadSignature, ValueError, TypeError):
        raise InvalidTicketToken("This QR code is invalid.")


def render_qr_png_bytes(token: str) -> bytes:
    """Renders the token to PNG bytes, generated on demand — never stored."""
    image = qrcode.make(token)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def render_qr_base64(token: str) -> str:
    """Base64 string form — for embedding as a data: URI in a browser <img>, e.g. the wallet pages.
    Not for email: Gmail and most mail clients strip data: URI images from HTML emails."""
    return base64.b64encode(render_qr_png_bytes(token)).decode("ascii")


def ticket_qr_base64(ticket: TicketOrder) -> str:
    """Convenience wrapper — the QR image for a given ticket, derived fresh from its id."""
    return render_qr_base64(make_qr_token(ticket.id))


def ticket_qr_png_bytes(ticket: TicketOrder) -> bytes:
    """Convenience wrapper — raw PNG bytes, for attaching inline (cid:) to an email."""
    return render_qr_png_bytes(make_qr_token(ticket.id))
