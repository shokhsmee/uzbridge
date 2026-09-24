from django.conf import settings
from django.http import Http404

from accounts.models import Company


def subdomain_of(host: str) -> str | None:
    """'acme.uzbridge.uz:443' -> 'acme'; the bare domain or a deeper host -> None."""
    host = host.split(":", 1)[0].lower()
    base = settings.BASE_DOMAIN.lower()
    if not host.endswith("." + base):
        return None
    label = host[: -len(base) - 1]
    return label if label and "." not in label else None


class TenantMiddleware:
    """Sets request.company from the subdomain.

    Reserved subdomains (app, api, ...) and the bare domain have no company;
    views that need one use `require_company`. An unknown company subdomain
    is a 404 for everything, so nobody can probe which slugs exist beyond
    that.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.company = None
        request.subdomain = subdomain_of(request.get_host())
        if request.subdomain and request.subdomain not in settings.RESERVED_SUBDOMAINS:
            request.company = Company.objects.filter(slug=request.subdomain, is_active=True).first()
            if request.company is None:
                raise Http404("Unknown company")
        return self.get_response(request)


def company_url(company: Company, path: str = "/") -> str:
    port = f":{settings.PUBLIC_PORT}" if settings.PUBLIC_PORT else ""
    return f"{settings.PUBLIC_SCHEME}://{company.slug}.{settings.BASE_DOMAIN}{port}{path}"


def platform_url(sub: str, path: str = "/") -> str:
    port = f":{settings.PUBLIC_PORT}" if settings.PUBLIC_PORT else ""
    return f"{settings.PUBLIC_SCHEME}://{sub}.{settings.BASE_DOMAIN}{port}{path}"
