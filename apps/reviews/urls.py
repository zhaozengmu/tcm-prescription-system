from django.urls import path
from . import views

app_name = "reviews"

urlpatterns = [
    path("", views.review_workbench, name="workbench"),
    path("<int:pk>/", views.review_detail, name="review_detail"),
]
