from django.contrib import admin

from core.admin_utils import ReadOnlyAdmin, link

from .models import DocTemplate, GeneratedDoc


@admin.register(DocTemplate)
class DocTemplateAdmin(admin.ModelAdmin):
    list_display = ["name", "company", "kind", "default_format", "next_label", "use_in_amocrm", "updated_at"]
    list_filter = ["kind", "default_format", "use_in_amocrm", "company"]
    search_fields = ["name", "company__slug"]
    exclude = ["docx"]
    readonly_fields = ["docx_name", "created_at", "updated_at"]

    @admin.display(description="Next number")
    def next_label(self, obj):
        return obj.format_number(obj.next_number)


@admin.register(GeneratedDoc)
class GeneratedDocAdmin(ReadOnlyAdmin):
    list_display = [
        "number",
        "template",
        "company",
        "lead",
        "format",
        "created_by_label",
        "created_at",
        "updated_at",
        "file",
    ]
    list_filter = ["format", "template", "company", "created_at"]
    search_fields = ["number", "lead_id", "company__slug", "template__name"]
    date_hierarchy = "created_at"
    list_select_related = ["template", "company", "amo_connection"]
    exclude = ["content", "token"]

    @admin.display(description="Lead")
    def lead(self, obj):
        if obj.amo_connection_id:
            return link(f"https://{obj.amo_connection.host}/leads/detail/{obj.lead_id}", f"#{obj.lead_id}")
        return obj.lead_id

    @admin.display(description="File")
    def file(self, obj):
        from .services import download_url

        return link(download_url(obj), "download")
