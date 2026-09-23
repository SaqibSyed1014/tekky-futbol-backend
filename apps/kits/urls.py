from django.urls import path

from .views import KitStatusView, LockKitView, MyKitOrderView, MyKitView

app_name = "kits"

urlpatterns = [
    # GET /kits/status/    — public: claimed kit slugs
    path("status/",   KitStatusView.as_view(),   name="kit_status"),

    # GET  /kits/my/       — view team kit state + own order
    # PATCH /kits/my/      — captain: select / change kit slug
    path("my/",       MyKitView.as_view(),      name="my_kit"),

    # POST /kits/my/lock/  — captain: lock the kit
    path("my/lock/",  LockKitView.as_view(),    name="lock_kit"),

    # GET   /kits/my/order/  — view own order
    # POST  /kits/my/order/  — submit order
    # PATCH /kits/my/order/  — update order
    path("my/order/", MyKitOrderView.as_view(), name="my_kit_order"),
]
