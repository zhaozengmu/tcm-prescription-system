"""历史查询与统计视图（含驾驶舱首页）。"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.db.models import Count, Sum, Q, F
from datetime import timedelta
import json

from apps.prescriptions.models import Prescription, PrescriptionItem, Herb, HerbBatch
from apps.users.permissions import has_permission
from apps.reviews.models import ReviewRecord


@login_required
def dashboard(request):
    """管理驾驶舱首页。"""
    today = timezone.now().date()

    # 今日处方数（仅已通过并归档口径）
    today_presc = Prescription.objects.filter(
        created_at__date=today, is_deleted=False
    ).count()
    pending_review = Prescription.objects.filter(
        status__in=["SUBMITTED", "PRECHECKED", "ALERTED", "REVIEWING", "FINAL_REVIEWING"],
        is_deleted=False,
    ).count()
    rejected = Prescription.objects.filter(status="REJECTED", is_deleted=False).count()
    total_presc = Prescription.objects.filter(is_deleted=False).count()

    # 处方量趋势（近7天）
    trend = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        cnt = Prescription.objects.filter(created_at__date=d, is_deleted=False).count()
        trend.append({"date": d.strftime("%m-%d"), "count": cnt})

    # 医师工作量排名 Top
    doctor_rank = list(
        Prescription.objects.filter(is_deleted=False)
        .values("doctor__user__first_name", "doctor__user__username")
        .annotate(cnt=Count("id"))
        .order_by("-cnt")[:10]
    )

    # 药材消耗 Top N
    herb_top = list(
        PrescriptionItem.objects.filter(prescription__is_deleted=False)
        .values("herb__name")
        .annotate(total=Sum("dose"))
        .order_by("-total")[:10]
    )

    # 驳回原因统计 Top N
    reject_reasons = list(
        ReviewRecord.objects.filter(reject_reason__isnull=False)
        .exclude(reject_reason="")
        .values("reject_reason")
        .annotate(cnt=Count("id"))
        .order_by("-cnt")[:10]
    )

    # 近效期药材预警（90 天内到期）
    near_expiry = HerbBatch.objects.filter(
        expire_at__lte=today + timedelta(days=90),
        expire_at__gte=today,
    ).select_related("herb", "supplier")[:20]

    # 库存短缺预警
    stock_shortage = Herb.objects.filter(stock__lte=F("stock_warning"), stock_warning__gt=0)[:20]

    context = {
        "today_presc": today_presc,
        "pending_review": pending_review,
        "rejected": rejected,
        "total_presc": total_presc,
        "trend": trend,
        "doctor_rank": doctor_rank,
        "herb_top": herb_top,
        "reject_reasons": reject_reasons,
        "near_expiry": near_expiry,
        "stock_shortage": stock_shortage,
    }
    return render(request, "stats/dashboard.html", context)


@login_required
def search_view(request):
    """历史处方多条件检索页面。"""
    if not has_permission(request.user, "统计:读"):
        return render(request, "stats/no_permission.html")
    return render(request, "stats/search.html")


@login_required
def logs_view(request):
    """操作日志查询页面。"""
    if not has_permission(request.user, "日志:读"):
        return render(request, "stats/no_permission.html")
    from .models import OperationLog
    logs = OperationLog.objects.select_related("operator").order_by("-created_at")[:100]
    return render(request, "stats/logs.html", {"logs": logs})


# ============ API 接口 ============

def api_stats_overview(request):
    """GET /api/v1/stats/overview 驾驶舱核心指标。"""
    if not request.user.is_authenticated:
        return JsonResponse({"code": 401, "message": "未登录"}, status=401)
    if not has_permission(request.user, "统计:读"):
        return JsonResponse({"code": 403, "message": "无权限"}, status=403)

    today = timezone.now().date()
    trend = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        cnt = Prescription.objects.filter(created_at__date=d, is_deleted=False).count()
        trend.append({"date": d.strftime("%m-%d"), "count": cnt})

    doctor_rank = list(
        Prescription.objects.filter(is_deleted=False)
        .values("doctor__user__first_name", "doctor__user__username")
        .annotate(cnt=Count("id")).order_by("-cnt")[:10]
    )
    herb_top = list(
        PrescriptionItem.objects.filter(prescription__is_deleted=False)
        .values("herb__name").annotate(total=Sum("dose")).order_by("-total")[:10]
    )

    # 驳回原因统计
    reject_reasons = list(
        ReviewRecord.objects.filter(reject_reason__isnull=False)
        .exclude(reject_reason="")
        .values("reject_reason").annotate(cnt=Count("id")).order_by("-cnt")[:10]
    )
    # 近效期与库存预警
    near_expiry = HerbBatch.objects.filter(
        expire_at__lte=today + timedelta(days=90), expire_at__gte=today,
    ).count()
    stock_shortage = Herb.objects.filter(stock__lte=F("stock_warning"), stock_warning__gt=0).count()

    return JsonResponse({
        "code": 200, "message": "ok",
        "data": {
            "today_presc": Prescription.objects.filter(created_at__date=today, is_deleted=False).count(),
            "pending_review": Prescription.objects.filter(status__in=["SUBMITTED", "PRECHECKED", "ALERTED", "REVIEWING", "FINAL_REVIEWING"], is_deleted=False).count(),
            "rejected": Prescription.objects.filter(status="REJECTED", is_deleted=False).count(),
            "total_presc": Prescription.objects.filter(is_deleted=False).count(),
            "trend": trend,
            "doctor_rank": doctor_rank,
            "herb_top": herb_top,
            "reject_reasons": reject_reasons,
            "near_expiry": near_expiry,
            "stock_shortage": stock_shortage,
        },
    })


def api_search(request):
    """GET /api/v1/search/prescriptions 多条件检索。"""
    if not request.user.is_authenticated:
        return JsonResponse({"code": 401, "message": "未登录"}, status=401)
    if not has_permission(request.user, "统计:读"):
        return JsonResponse({"code": 403, "message": "无权限"}, status=403)

    qs = Prescription.objects.filter(is_deleted=False).select_related("patient", "doctor__user")

    status = request.GET.get("status", "")
    doctor_name = request.GET.get("doctor", "")
    patient_name = request.GET.get("patient", "")
    start = request.GET.get("start", "")
    end = request.GET.get("end", "")
    hit_rule = request.GET.get("hit_rule", "")

    if status:
        qs = qs.filter(status=status)
    if doctor_name:
        qs = qs.filter(doctor__user__username__icontains=doctor_name)
    if patient_name:
        qs = qs.filter(patient__name__icontains=patient_name)
    if start:
        qs = qs.filter(created_at__date__gte=start)
    if end:
        qs = qs.filter(created_at__date__lte=end)
    if hit_rule:
        # 是否命中规则：关联审核记录
        qs = qs.filter(review_records__precheck_result__icontains=hit_rule).distinct()

    qs = qs.order_by("-created_at")
    items = []
    for p in qs[:200]:
        items.append({
            "id": p.id, "presc_no": p.presc_no,
            "patient_name": p.patient.name,
            "doctor_name": p.doctor.user.get_full_name() or p.doctor.user.username,
            "status": p.get_status_display(),
            "created_at": p.created_at.strftime("%Y-%m-%d %H:%M"),
        })
    return JsonResponse({"code": 200, "message": "ok", "data": {"items": items, "total": qs.count()}})


def api_logs(request):
    """GET /api/v1/logs 操作日志查询。"""
    if not request.user.is_authenticated:
        return JsonResponse({"code": 401, "message": "未登录"}, status=401)
    if not has_permission(request.user, "日志:读"):
        return JsonResponse({"code": 403, "message": "无权限"}, status=403)

    from .models import OperationLog
    qs = OperationLog.objects.select_related("operator").order_by("-created_at")
    operator = request.GET.get("operator", "")
    action = request.GET.get("action", "")
    if operator:
        qs = qs.filter(operator__username__icontains=operator)
    if action:
        qs = qs.filter(action_type__icontains=action)

    items = []
    for log in qs[:200]:
        items.append({
            "id": log.id,
            "operator": log.operator.username if log.operator else "-",
            "action_type": log.action_type,
            "object_type": log.object_type,
            "object_id": log.object_id,
            "detail": log.detail,
            "ip": log.ip,
            "created_at": log.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        })
    return JsonResponse({"code": 200, "message": "ok", "data": {"items": items, "total": qs.count()}})


def api_export(request):
    """GET /api/v1/export/prescriptions 处方与统计结果导出（Excel）。"""
    if not request.user.is_authenticated:
        return JsonResponse({"code": 401, "message": "未登录"}, status=401)
    if not has_permission(request.user, "导出:执行"):
        return JsonResponse({"code": 403, "message": "无权限"}, status=403)

    import io
    import openpyxl
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "处方清单"
    ws.append(["处方号", "患者", "医师", "诊断", "状态", "创建时间"])

    qs = Prescription.objects.filter(is_deleted=False).select_related("patient", "doctor__user").order_by("-created_at")
    for p in qs[:1000]:
        ws.append([
            p.presc_no, p.patient.name,
            p.doctor.user.get_full_name() or p.doctor.user.username,
            p.diagnosis, p.get_status_display(),
            p.created_at.strftime("%Y-%m-%d %H:%M"),
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    from apps.stats.models import OperationLog
    from apps.users.permissions import get_client_ip
    OperationLog.objects.create(
        operator=request.user, action_type="EXPORT", object_type="prescription",
        object_id="all", detail="导出处方清单", ip=get_client_ip(request), result="success",
    )

    response = HttpResponse(buf.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="prescriptions.xlsx"'
    return response


def api_export_herbs(request):
    """GET /api/v1/export/herbs 药材台账导出（Excel）。"""
    if not request.user.is_authenticated:
        return JsonResponse({"code": 401, "message": "未登录"}, status=401)
    if not has_permission(request.user, "导出:执行"):
        return JsonResponse({"code": 403, "message": "无权限"}, status=403)

    import io
    import openpyxl
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "药材台账"
    ws.append(["药材名称", "拼音首字母", "类别", "性味归经", "功效主治", "道地产地", "炮制规格",
               "剂量上限(g)", "常用剂量(g)", "毒性", "库存(kg)", "预警线(kg)"])

    for h in Herb.objects.all().order_by("pinyin_initial", "name"):
        ws.append([
            h.name, h.pinyin_initial, h.category, h.property, h.efficacy, h.origin, h.processing,
            float(h.max_dose) if h.max_dose else "", float(h.default_dose) if h.default_dose else "",
            "是" if h.is_toxic else "否", float(h.stock), float(h.stock_warning),
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    from apps.stats.models import OperationLog
    from apps.users.permissions import get_client_ip
    OperationLog.objects.create(
        operator=request.user, action_type="EXPORT", object_type="herb",
        object_id="all", detail="导出药材台账", ip=get_client_ip(request), result="success",
    )

    response = HttpResponse(buf.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="herbs.xlsx"'
    return response


def api_export_logs(request):
    """GET /api/v1/export/logs 操作日志导出（Excel）。"""
    if not request.user.is_authenticated:
        return JsonResponse({"code": 401, "message": "未登录"}, status=401)
    if not has_permission(request.user, "导出:执行"):
        return JsonResponse({"code": 403, "message": "无权限"}, status=403)

    import io
    import openpyxl
    from openpyxl import Workbook
    from .models import OperationLog

    wb = Workbook()
    ws = wb.active
    ws.title = "操作日志"
    ws.append(["操作人", "动作", "对象类型", "对象ID", "详情", "IP", "结果", "时间"])

    for log in OperationLog.objects.select_related("operator").order_by("-created_at")[:5000]:
        ws.append([
            log.operator.username if log.operator else "-", log.action_type, log.object_type,
            log.object_id, log.detail, log.ip, log.result,
            log.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    response = HttpResponse(buf.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="operation_logs.xlsx"'
    return response


def api_export_reviews(request):
    """GET /api/v1/export/reviews 审核记录导出（Excel）。"""
    if not request.user.is_authenticated:
        return JsonResponse({"code": 401, "message": "未登录"}, status=401)
    if not has_permission(request.user, "导出:执行"):
        return JsonResponse({"code": 403, "message": "无权限"}, status=403)

    import io
    import openpyxl
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "审核记录"
    ws.append(["处方号", "审核级别", "审核人", "审核意见", "驳回原因", "不良反应备注", "审核时间"])

    for rv in ReviewRecord.objects.select_related("prescription", "pharmacist__user").order_by("-created_at")[:5000]:
        ws.append([
            rv.prescription.presc_no,
            rv.get_review_level_display(),
            (rv.pharmacist.user.get_full_name() or rv.pharmacist.user.username) if rv.pharmacist else "-",
            rv.review_opinion, rv.reject_reason or "", rv.adverse_note or "",
            rv.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    response = HttpResponse(buf.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="review_records.xlsx"'
    return response
