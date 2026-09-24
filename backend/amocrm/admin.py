from django.contrib import admin

from .models import AmoConnection


@admin.register(AmoConnection)
class AmoConnectionAdmin(admin.ModelAdmin):
    list_display = ["company", "host", "account_id", "status", "expires_at", "connected_at"]
    list_filter = ["status"]
    search_fields = ["company__slug", "host", "account_id"]
    exclude = ["access_token", "refresh_token"]
