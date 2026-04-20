from django.contrib import admin

from .models import Application, FreeAgent


@admin.register(FreeAgent)
class FreeAgentAdmin(admin.ModelAdmin):
    list_display = ["user", "preferred_position", "available_since", "is_active", "created_at"]
    list_filter = ["is_active", "preferred_position"]
    search_fields = ["user__email"]
    readonly_fields = ["created_at", "updated_at"]
    autocomplete_fields = ["user"]


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ["applicant", "type", "status", "team", "reviewed_by", "created_at"]
    list_filter = ["type", "status"]
    search_fields = ["applicant__email", "team__name"]
    readonly_fields = ["created_at", "updated_at"]
    autocomplete_fields = ["applicant", "team", "reviewed_by"]
