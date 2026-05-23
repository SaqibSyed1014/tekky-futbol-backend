from django.contrib import admin

from .models import WaiverSignature


@admin.register(WaiverSignature)
class WaiverSignatureAdmin(admin.ModelAdmin):
    list_display  = ("user", "printed_name", "waiver_version", "signed_at", "ip_address")
    list_filter   = ("waiver_version",)
    search_fields = ("user__email", "printed_name", "user__name")
    readonly_fields = (
        "id", "user", "waiver_version", "date_of_birth", "address",
        "medical_conditions", "emergency_contact_name", "emergency_contact_rel",
        "emergency_contact_phone", "clauses_initialed", "printed_name",
        "signature_image", "signed_at", "ip_address", "user_agent",
    )
    ordering = ("-signed_at",)

    def has_add_permission(self, request):
        return False  # waivers are only created via the API

    def has_delete_permission(self, request, obj=None):
        return False  # legal records must not be deleted
