from django.contrib import admin

from core.admin_utils import ReadOnlyAdmin, ReadOnlyInline, badge, link

from .models import GoogleAccount, Project, Unit, UnitEvent, UnitStatus

TONES = {
    UnitStatus.FREE: "ok",
    UnitStatus.INTEREST: "accent",
    UnitStatus.RESERVED: "warn",
    UnitStatus.SOLD: "bad",
    UnitStatus.CLOSED: "muted",
}


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ["name", "company", "currency", "units", "is_public", "use_in_amocrm", "last_sync_at", "sheet"]
    list_filter = ["currency", "is_public", "use_in_amocrm", "company"]
    search_fields = ["name", "company__slug"]
    readonly_fields = ["sheet_key", "showroom_key", "last_sync_at", "last_sync_summary", "created_at"]

    @admin.display(description="Units")
    def units(self, obj):
        return obj.units.filter(archived=False).count()

    @admin.display(description="Sheet")
    def sheet(self, obj):
        return link(obj.sheet_url, "Google Sheet")


class EventInline(ReadOnlyInline):
    model = UnitEvent
    fields = ["created_at", "status_from", "status_to", "source", "lead_id", "note"]
    readonly_fields = fields
    ordering = ["-created_at"]


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ["label", "project", "rooms", "area", "price", "state", "lead", "archived", "updated_at"]
    list_filter = ["status", "kind", "archived", "project__company", "project"]
    search_fields = ["ext_id", "number", "project__name", "lead_id"]
    list_select_related = ["project", "amo_connection"]
    exclude = ["plan"]
    readonly_fields = ["sheet_status", "status_changed_at", "updated_at"]
    raw_id_fields = ["amo_connection"]
    inlines = [EventInline]

    @admin.display(description="Status", ordering="status")
    def state(self, obj):
        return badge(obj.get_status_display(), TONES.get(obj.status, "muted"))

    @admin.display(description="Lead")
    def lead(self, obj):
        if obj.lead_id and obj.amo_connection_id:
            return link(f"https://{obj.amo_connection.host}/leads/detail/{obj.lead_id}", f"#{obj.lead_id}")
        return "—"


@admin.register(UnitEvent)
class UnitEventAdmin(ReadOnlyAdmin):
    list_display = ["created_at", "unit", "status_from", "status_to", "source", "lead_id", "note"]
    list_filter = ["source", "status_to", "created_at"]
    search_fields = ["unit__ext_id", "unit__project__name", "lead_id"]
    date_hierarchy = "created_at"
    list_select_related = ["unit__project"]


@admin.register(GoogleAccount)
class GoogleAccountAdmin(ReadOnlyAdmin):
    list_display = ["company", "email", "connected_by", "created_at"]
    search_fields = ["company__slug", "email"]
    exclude = ["refresh_token", "access_token"]
