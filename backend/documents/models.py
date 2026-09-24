import secrets
import uuid

from django.db import models

from accounts.models import Company


class DocFormat(models.TextChoices):
    DOCX = "docx", "Word (.docx)"
    PDF = "pdf", "PDF"


class DocTemplate(models.Model):
    """A company's document (contract, offer, act…) with {keywords}, filled per amoCRM lead.

    Made either by uploading a Word file (kind=docx: formatting kept exactly)
    or in the site's editor (kind=html). Each template numbers its documents
    on its own counter, which never resets: DOG-0001, DOG-0002, …
    """

    class Kind(models.TextChoices):
        DOCX = "docx", "Uploaded Word file"
        HTML = "html", "Built on the site"

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="doc_templates")
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    docx = models.BinaryField(null=True, blank=True)  # the uploaded .docx (kind=docx)
    docx_name = models.CharField(max_length=200, blank=True)
    html = models.TextField(blank=True)  # the editor's content (kind=html)
    default_format = models.CharField(max_length=5, choices=DocFormat.choices, default=DocFormat.PDF)
    # Numbering: prefix + zero-padded counter, e.g. "DOG-" + 0001.
    prefix = models.CharField(max_length=20, blank=True, default="")
    padding = models.PositiveSmallIntegerField(default=4)
    next_number = models.PositiveIntegerField(default=1)
    use_in_amocrm = models.BooleanField(default=True)
    # Where each {keyword} of this template takes its value, e.g.
    #   {"muddat": {"type": "amo", "source": "lead.cf.501"},
    #    "sana": {"type": "date", "offset_days": 10, "style": "long"},
    #    "raqam": {"type": "number"}, "shahar": {"type": "text", "value": "Toshkent"},
    #    "stir": {"type": "builtin", "key": "company_tin"}}
    # Keywords without a binding fall back to the built-ins and the company's amoCRM keywords.
    bindings = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "pk"]
        verbose_name = "document template"
        verbose_name_plural = "document templates"

    def __str__(self):
        return f"{self.company.slug}: {self.name}"

    def format_number(self, seq: int) -> str:
        return f"{self.prefix}{seq:0{self.padding}d}"


class GeneratedDoc(models.Model):
    """One numbered document made for an amoCRM lead. Re-generating keeps the number."""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="documents")
    template = models.ForeignKey(DocTemplate, on_delete=models.PROTECT, related_name="documents")
    amo_connection = models.ForeignKey(
        "amocrm.AmoConnection", null=True, blank=True, on_delete=models.SET_NULL, related_name="documents"
    )
    lead_id = models.BigIntegerField(db_index=True)
    seq = models.PositiveIntegerField()
    number = models.CharField(max_length=40)
    format = models.CharField(max_length=5, choices=DocFormat.choices)
    content = models.BinaryField()
    filename = models.CharField(max_length=200)
    # Public download link (/d/<token>/), shared in the lead's note.
    token = models.CharField(max_length=43, unique=True, default=secrets.token_urlsafe)
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    values = models.JSONField(default=dict, blank=True)  # what the keywords were filled with
    # The copy in the lead's "Файлы" tab; a re-make uploads a new version of it.
    amo_file_uuid = models.CharField(max_length=64, blank=True)
    amo_file_format = models.CharField(max_length=5, blank=True)
    created_by_label = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-pk"]
        verbose_name = "generated document"
        verbose_name_plural = "generated documents"
        constraints = [
            models.UniqueConstraint(fields=["template", "seq"], name="uniq_doc_template_seq"),
        ]

    def __str__(self):
        return f"{self.number} ({self.template.name})"

    @property
    def content_type(self) -> str:
        if self.format == DocFormat.PDF:
            return "application/pdf"
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
