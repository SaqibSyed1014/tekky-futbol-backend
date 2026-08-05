from django.urls import path
from .views import ShopCheckoutView

app_name = 'shop'

urlpatterns = [
    path('checkout/', ShopCheckoutView.as_view(), name='checkout'),
]
