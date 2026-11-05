"""System checks (manage.py check, runserver): the API key and the URL of the webhook endpoint."""
from django.core.checks import Tags, Warning, register
from django.urls import NoReverseMatch, URLResolver, get_resolver, reverse


@register()
def check_api_key(app_configs, **kwargs):
    from . import settings

    if settings().api_key:
        return []
    return [Warning("UniOne: the API key is not set.",
                    hint='Set the UNIONE_API_KEY environment variable or UNIONE = {"API_KEY": ...} in the settings.',
                    id="unione_wrapper.W001")]


def _mounted(patterns, view) -> bool:
    """The view is in the URL patterns: through include() or with path("...", webhook) of the project."""
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            if _mounted(pattern.url_patterns, view):
                return True
        elif getattr(pattern, "callback", None) is view:
            return True
    return False


@register(Tags.urls)
def check_webhook_url(app_configs, **kwargs):
    import os

    from django.conf import settings as django_settings

    from ._settings import ENV_PREFIX
    from .views import webhook

    enabled = (getattr(django_settings, "UNIONE", None) or {}).get("WEBHOOK_ENABLED")
    if enabled is None:
        enabled = os.environ.get(ENV_PREFIX + "WEBHOOK_ENABLED", "").lower() != "false"
    if not enabled:
        return []
    try:
        reverse("unione:webhook")
        return []
    except NoReverseMatch:
        pass
    if _mounted(get_resolver().url_patterns, webhook):
        return []
    return [Warning("UniOne: the webhook endpoint has no URL.",
                    hint='urlpatterns = [..., path("unione/", include("unione_wrapper.urls"))]  # /unione/webhook; '
                         'no webhooks: UNIONE = {..., "WEBHOOK_ENABLED": False} or '
                         'SILENCED_SYSTEM_CHECKS = ["unione_wrapper.W002"]',
                    id="unione_wrapper.W002")]
