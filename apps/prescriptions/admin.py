from django.contrib import admin
from .models import Herb, FormulaTemplate, FormulaItem, AuditRule, Prescription, PrescriptionItem


class FormulaItemInline(admin.TabularInline):
    model = FormulaItem
    extra = 1


@admin.register(Herb)
class HerbAdmin(admin.ModelAdmin):
    list_display = ("name", "pinyin", "max_dose", "is_toxic", "default_dose")
    search_fields = ("name", "pinyin")
    list_filter = ("is_toxic",)


@admin.register(FormulaTemplate)
class FormulaTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "indication")
    inlines = [FormulaItemInline]


@admin.register(AuditRule)
class AuditRuleAdmin(admin.ModelAdmin):
    list_display = ("rule_no", "rule_type", "herbs", "level", "message", "version", "is_active")
    list_filter = ("rule_type", "level", "is_active")


class PrescriptionItemInline(admin.TabularInline):
    model = PrescriptionItem
    extra = 0


@admin.register(Prescription)
class PrescriptionAdmin(admin.ModelAdmin):
    list_display = ("presc_no", "patient", "doctor", "status", "version", "created_at")
    list_filter = ("status", "presc_type")
    search_fields = ("presc_no", "patient__name")
    inlines = [PrescriptionItemInline]
