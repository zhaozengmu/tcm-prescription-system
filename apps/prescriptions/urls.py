from django.urls import path
from . import views

app_name = "prescriptions"

urlpatterns = [
    path("", views.prescription_list, name="prescription_list"),
    path("create/", views.prescription_create, name="prescription_create"),
    path("<int:pk>/", views.prescription_detail, name="prescription_detail"),
]
