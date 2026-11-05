from django.urls import include, path

urlpatterns = [path("unione/", include("unione_wrapper.urls"))]
