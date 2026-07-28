import stripe
from django.conf import settings


def _client() -> stripe:
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


def create_checkout_session(reference_number: str, amount: str = "700.00") -> str:
    """
    Creates a Stripe Checkout Session and returns the hosted checkout URL.
    The frontend redirects the customer directly to this URL.
    """
    client = _client()
    session = client.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": "TekkyFutbol Registration Fee"},
                "unit_amount": round(float(amount) * 100),  # Stripe expects cents
            },
            "quantity": 1,
        }],
        mode="payment",
        client_reference_id=reference_number,
        success_url=f"{settings.FRONTEND_BASE_URL}/payment/success",
        cancel_url=f"{settings.FRONTEND_BASE_URL}/payment/failed",
    )
    return session.url


def verify_webhook(payload: bytes, sig_header: str):
    """
    Verifies the Stripe webhook signature using the raw request body.
    Returns the verified Stripe Event object.
    Raises stripe.error.SignatureVerificationError or ValueError on failure.
    """
    client = _client()
    return client.Webhook.construct_event(
        payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
    )
