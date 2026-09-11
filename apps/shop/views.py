import stripe
from django.conf import settings
from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import ShopOrder
from .serializers import ShopOrderSerializer


def _parse_amount_cents(amount):
    try:
        amount_cents = round(float(amount) * 100)
    except (TypeError, ValueError):
        return None, 'Invalid amount.'
    if amount_cents <= 0:
        return None, 'Invalid amount.'
    return amount_cents, None


def _parse_quantity(quantity, default=1):
    if quantity is None:
        return default, None
    try:
        parsed = int(quantity)
    except (TypeError, ValueError):
        return None, 'Invalid quantity.'
    if parsed <= 0:
        return None, 'Invalid quantity.'
    return parsed, None


def _build_line_item(raw_item):
    name = (raw_item.get('name') or '').strip()
    if not name:
        return None, None, None, 'Each item requires a name.'

    amount = raw_item.get('amount')
    if amount is None:
        return None, None, None, 'Each item requires an amount.'

    amount_cents, amount_error = _parse_amount_cents(amount)
    if amount_error:
        return None, None, None, amount_error

    quantity, quantity_error = _parse_quantity(raw_item.get('quantity'))
    if quantity_error:
        return None, None, None, quantity_error

    variant = (raw_item.get('variant') or '').strip()
    display_name = f'{name} — {variant}' if variant else name

    description = (raw_item.get('description') or '').strip()
    image_url = (raw_item.get('image_url') or '').strip()

    product_data = {'name': display_name}
    if description:
        product_data['description'] = description
    if image_url:
        product_data['images'] = [image_url]

    line_item = {
        'price_data': {
            'currency': 'usd',
            'product_data': product_data,
            'unit_amount': amount_cents,
        },
        'quantity': quantity,
    }
    return line_item, display_name, quantity, None


def _format_product_summary(display_name, quantity):
    if quantity > 1:
        return f'{display_name} x{quantity}'
    return display_name


class ShopCheckoutView(APIView):
    """
    POST /api/v1/shop/checkout/

    Public endpoint — no auth required.
    Creates a Stripe Checkout Session for one or more shop products and returns
    the hosted checkout URL. Uses inline price_data so no Stripe Products
    need to exist in the dashboard.
    """
    permission_classes = [AllowAny]
    authentication_classes = [JWTAuthentication]

    def post(self, request):
        cancel_url = (request.data.get('cancel_url', '') or '').strip()
        return_path = (request.data.get('return_path', '') or '').strip()
        items_raw = request.data.get('items')

        if items_raw is not None:
            if not isinstance(items_raw, list) or not items_raw:
                return Response(
                    {'detail': 'items must be a non-empty array.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            line_items = []
            product_summaries = []
            for raw_item in items_raw:
                line_item, display_name, quantity, error = _build_line_item(raw_item)
                if error:
                    return Response({'detail': error}, status=status.HTTP_400_BAD_REQUEST)
                line_items.append(line_item)
                product_summaries.append(_format_product_summary(display_name, quantity))

            product_name = ', '.join(product_summaries)
        else:
            line_item, display_name, quantity, error = _build_line_item(request.data)
            if error:
                return Response({'detail': error}, status=status.HTTP_400_BAD_REQUEST)

            line_items = [line_item]
            product_name = _format_product_summary(display_name, quantity)

        if not cancel_url:
            cancel_url = f'{settings.FRONTEND_BASE_URL}/shop'

        stripe.api_key = settings.STRIPE_SECRET_KEY

        metadata = {
            "type": "shop_order",
            "product_name": product_name,
        }
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            metadata["user_id"] = str(user.id)

        try:
            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=line_items,
                mode='payment',
                metadata=metadata,
                success_url=f"{settings.FRONTEND_BASE_URL}/shop/order/success?from={return_path or '/shop'}",
                cancel_url=cancel_url,
            )
        except stripe.error.StripeError:
            return Response(
                {'detail': 'Payment service unavailable. Please try again later.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response({'checkout_url': session.url})


class ShopOrderListView(APIView):
    """GET /api/v1/shop/orders/ — the authenticated user's shop order history."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        qs = ShopOrder.objects.filter(
            Q(user=user) | Q(user__isnull=True, email__iexact=user.email)
        ).order_by("-created_at")
        return Response(ShopOrderSerializer(qs, many=True).data)
