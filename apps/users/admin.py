from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import PlayerProfile, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ["-created_at"]
    list_display = ["email", "role", "is_captain", "is_active", "is_staff", "created_at"]
    list_filter = ["role", "is_captain", "is_active", "is_staff"]
    search_fields = ["email"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Role & Flags", {"fields": ("role", "is_captain")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Timestamps", {"fields": ("created_at", "updated_at", "last_login")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "role", "password1", "password2")}),
    )
    readonly_fields = ["created_at", "updated_at"]


@admin.register(PlayerProfile)
class PlayerProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "team", "position", "status", "created_at"]
    list_filter = ["status", "position"]
    search_fields = ["user__email", "team__name"]
    readonly_fields = ["created_at", "updated_at"]
    autocomplete_fields = ["user", "team"]
