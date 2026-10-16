"""path("unione/", include("unione_wrapper.urls")) -> /unione/webhook"""
from django.urls import path

from .views import webhook

app_name = "unione"
urlpatterns = [path("webhook", webhook, name="webhook")]
