import stripe
from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class ShopCheckoutView(APIView):
    """
    POST /api/v1/shop/checkout/

    Public endpoint — no auth required.
    Creates a Stripe Checkout Session for a single shop product and returns
    the hosted checkout URL. Uses inline price_data so no Stripe Products
    need to exist in the dashboard.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        name = request.data.get('name', '').strip()
        description = request.data.get('description', '').strip()
        image_url = request.data.get('image_url', '').strip()
        amount = request.data.get('amount')
        cancel_url = (request.data.get('cancel_url', '') or '').strip()

        if not name or amount is None:
            return Response(
                {'detail': 'name and amount are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            amount_cents = round(float(amount) * 100)
        except (TypeError, ValueError):
            return Response(
                {'detail': 'Invalid amount.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not cancel_url:
            cancel_url = f"{settings.FRONTEND_BASE_URL}/shop"

        product_data = {'name': name}
        if description:
            product_data['description'] = description
        if image_url:
            product_data['images'] = [image_url]

        stripe.api_key = settings.STRIPE_SECRET_KEY

        try:
            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'usd',
                        'product_data': product_data,
                        'unit_amount': amount_cents,
                    },
                    'quantity': 1,
                }],
                mode='payment',
                success_url=f"{settings.FRONTEND_BASE_URL}/shop/order/success",
                cancel_url=cancel_url,
            )
        except stripe.error.StripeError:
            return Response(
                {'detail': 'Payment service unavailable. Please try again later.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response({'checkout_url': session.url})
