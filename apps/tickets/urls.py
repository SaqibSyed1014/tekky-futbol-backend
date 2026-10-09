from django.urls import path

from .views import (
    MyTicketsView,
    TicketAvailabilityView,
    TicketBySessionView,
    TicketCheckInView,
    TicketCheckoutView,
)

app_name = "tickets"

urlpatterns = [
    path("checkout/", TicketCheckoutView.as_view(), name="checkout"),
    path("availability/", TicketAvailabilityView.as_view(), name="availability"),
    path("by-session/<str:session_id>/", TicketBySessionView.as_view(), name="by_session"),
    path("my/", MyTicketsView.as_view(), name="my_tickets"),
    path("check-in/", TicketCheckInView.as_view(), name="check_in"),
]
