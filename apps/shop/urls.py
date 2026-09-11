from django.urls import path
from .views import ShopCheckoutView, ShopOrderListView

app_name = 'shop'

urlpatterns = [
    path('checkout/', ShopCheckoutView.as_view(), name='checkout'),
    path('orders/', ShopOrderListView.as_view(), name='orders'),
]
