from django.urls import path
from . import views

urlpatterns = [
    path("prescriptions", views.api_prescription_create, name="api_prescription_create"),
    path("prescriptions/<int:pk>", views.api_prescription_items, name="api_prescription_items"),
    path("prescriptions/<int:pk>/submit", views.api_prescription_submit, name="api_prescription_submit"),
    path("formulas/<int:formula_id>", views.api_formula_detail, name="api_formula_detail"),
]
