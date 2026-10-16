"""Webhook endpoint: GET/HEAD -> 200 (URL check of webhook/set), POST -> signature check and signals."""
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import settings, webhook as notifications
from .signals import webhook_event_received, webhook_received


@csrf_exempt
@require_http_methods(["GET", "HEAD", "POST"])
def webhook(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse("OK", content_type="text/plain")
    try:
        callback, payload = notifications.parse(request.body, settings().signing_key)
    except notifications.WebhookError as e:
        return HttpResponse(str(e), status=e.status, content_type="text/plain")
    webhook_received.send(sender=webhook, callback=callback, payload=payload)
    for event, user in notifications.events(callback):
        webhook_event_received.send(sender=webhook, event=event, user=user)
    return HttpResponse("OK", content_type="text/plain")
