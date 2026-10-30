from django.apps import AppConfig


class PatientsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.patients"
    verbose_name = "患者信息管理"
