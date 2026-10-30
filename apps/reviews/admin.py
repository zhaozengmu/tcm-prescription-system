from django.contrib import admin
from .models import ReviewRecord


@admin.register(ReviewRecord)
class ReviewRecordAdmin(admin.ModelAdmin):
    list_display = ("prescription", "pharmacist", "created_at")
    list_filter = ("created_at",)
