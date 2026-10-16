from django.apps import AppConfig
from django.core.signals import setting_changed


def _reset(setting, **kwargs):
    if setting == "UNIONE":
        from . import reset

        reset()


class UnioneConfig(AppConfig):
    name = "unione_wrapper"
    verbose_name = "UniOne"

    def ready(self):
        setting_changed.connect(_reset, dispatch_uid="unione_wrapper.reset")
