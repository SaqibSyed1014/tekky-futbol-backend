from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import FanProfile, PlayerProfile, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ["-created_at"]
    list_display = ["email", "name", "role", "is_captain", "is_active", "is_staff", "created_at"]
    list_filter = ["role", "is_captain", "is_active", "is_staff"]
    search_fields = ["email", "name"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profile", {"fields": ("name", "phone", "gender")}),
        ("Role & Flags", {"fields": ("role", "is_captain")}),
        ("OAuth", {"fields": ("google_id", "apple_id")}),
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


@admin.register(FanProfile)
class FanProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "favorite_division", "zip_code", "shirt_size", "created_at"]
    list_filter = ["favorite_division", "shirt_size"]
    search_fields = ["user__email", "user__name", "zip_code"]
    readonly_fields = ["created_at", "updated_at"]
    autocomplete_fields = ["user"]
