"""UniOne Web API for Django: API client, email backend, webhooks."""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Mapping

from unione import UniOneClient
from unione.client import ApiClient, Configuration, base_url_for

from ._settings import Settings

__all__ = ["get_client", "get_api_client", "api_client_for", "settings", "Settings"]
__version__ = "1.1.2"
PLATFORM = "django.1.1.2"
"""The package and its version in the "platform" query parameter of the requests, before the SDK one."""


def settings() -> Settings:
    """Environment variables UNIONE_* overridden by the UNIONE dict of the Django settings."""
    from django.conf import settings as django_settings

    return Settings.load(getattr(django_settings, "UNIONE", None) or {})


@lru_cache(maxsize=None)
def get_client() -> UniOneClient:
    """The UniOne API client of the project settings (one instance per process)."""
    s = settings()
    return UniOneClient(s.require_key(), s.host, s.timeout, platform=PLATFORM)


@lru_cache(maxsize=None)
def get_api_client() -> ApiClient:
    """Low level client (call(path, body)) of the project settings, used by the email backend."""
    return api_client_for({})


def api_client_for(overrides: Mapping[str, Any]) -> ApiClient:
    """Low level client of the project settings with overrides (api_key, host, timeout)."""
    s = settings()
    s = Settings.load({**{k: getattr(s, k) for k in ("api_key", "host", "timeout")}, **overrides}, environ={})
    config = Configuration(s.require_key(), timeout=s.timeout, platform=PLATFORM)
    if s.host:
        config.base_url = base_url_for(s.host)
    return ApiClient(config)


def reset() -> None:
    """Forget the cached clients (the settings have changed)."""
    get_client.cache_clear()
    get_api_client.cache_clear()
