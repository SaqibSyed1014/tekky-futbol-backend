from django.urls import path

from .views import InitiatePaymentView, MyPaymentView, PaymentCallbackView

app_name = "payments"

urlpatterns = [
    path("initiate/",  InitiatePaymentView.as_view(),  name="initiate"),
    path("me/",        MyPaymentView.as_view(),         name="me"),
    path("callback/",  PaymentCallbackView.as_view(),   name="callback"),
]
