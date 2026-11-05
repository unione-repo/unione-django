from django.urls import path

from unione_wrapper.views import webhook

urlpatterns = [path("hooks/unione", webhook)]
