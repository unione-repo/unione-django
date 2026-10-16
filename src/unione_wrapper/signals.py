"""Signals of the webhook endpoint (sender: the view function).

webhook_received:       callback (model of the notification), payload (decoded body)
webhook_event_received: event (one event: event_name, event_data), user (its user/project)

Receivers run inside the request: keep them fast, the API waits for 200 OK for 3 seconds only.
"""
from django.dispatch import Signal

webhook_received = Signal()
webhook_event_received = Signal()
