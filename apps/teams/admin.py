from django.contrib import admin

from .models import Team


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ["name", "captain", "max_players", "is_active", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["name", "captain__email"]
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ["created_at", "updated_at"]
    autocomplete_fields = ["captain"]
