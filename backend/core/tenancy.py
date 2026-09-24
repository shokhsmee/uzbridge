"""Which company a request belongs to, and the URLs we hand out.

Two modes (settings.TENANCY):
- "subdomain": acme.uzbridge.uz; the host names the company.
- "path": uzbridge.uz/acme/; the SPA sends the slug in an X-Company header
  and everything lives on one host. Used while the DNS can't do wildcards.
"""

from django.conf import settings
from django.http import Http404

from accounts.models import Company


def path_mode() -> bool:
    return settings.TENANCY == "path"


def subdomain_of(host: str) -> str | None:
    """'acme.uzbridge.uz:443' -> 'acme'; the bare domain or a deeper host -> None."""
    host = host.split(":", 1)[0].lower()
    base = settings.BASE_DOMAIN.lower()
    if not host.endswith("." + base):
        return None
    label = host[: -len(base) - 1]
    return label if label and "." not in label else None


class TenantMiddleware:
    """Sets request.company.

    Reserved names (app, api, ...) and the bare domain have no company. An
    unknown company is a 404 for everything, so nobody can probe which slugs
    exist beyond that.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.company = None
        if path_mode():
            request.subdomain = None
            slug = request.headers.get("X-Company", "").strip().lower()
        else:
            slug = request.subdomain = subdomain_of(request.get_host())
        if slug and slug not in settings.RESERVED_SUBDOMAINS:
            request.company = Company.objects.filter(slug=slug, is_active=True).first()
            if request.company is None:
                raise Http404("Unknown company")
        return self.get_response(request)


def _port() -> str:
    return f":{settings.PUBLIC_PORT}" if settings.PUBLIC_PORT else ""


def origin() -> str:
    """The single public origin in path mode (also the bare domain in subdomain mode)."""
    return f"{settings.PUBLIC_SCHEME}://{settings.BASE_DOMAIN}{_port()}"


def company_origin(company: Company) -> str:
    if path_mode():
        return origin()
    return f"{settings.PUBLIC_SCHEME}://{company.slug}.{settings.BASE_DOMAIN}{_port()}"


def company_url(company: Company, path: str = "/") -> str:
    """A dashboard URL for the company."""
    if path_mode():
        return f"{origin()}/{company.slug}{path}"
    return f"{company_origin(company)}{path}"


def pay_url(invoice) -> str:
    """The customer-facing pay page; its uuid alone identifies the invoice."""
    if path_mode():
        return f"{origin()}/p/{invoice.public_id}/"
    return f"{company_origin(invoice.company)}/p/{invoice.public_id}/"


def platform_url(sub: str, path: str = "/") -> str:
    """app.* / api.* in subdomain mode, the single origin in path mode."""
    if path_mode():
        return f"{origin()}{path}"
    return f"{settings.PUBLIC_SCHEME}://{sub}.{settings.BASE_DOMAIN}{_port()}{path}"
