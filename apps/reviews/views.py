"""处方审核管理视图。

药师工作台：待审队列、领取/转交、复核通过/退回、附件与轨迹。
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.utils import timezone
from django.db import transaction
import json

from apps.prescriptions.models import Prescription, PrescriptionItem
from apps.reviews.models import ReviewRecord
from apps.reviews import engine, state_machine
from apps.users.permissions import has_permission, get_client_ip
from apps.utils.crypto import decrypt


@login_required
def review_workbench(request):
    """药师工作台：待审队列。"""
    if not has_permission(request.user, "审核:读"):
        return render(request, "reviews/no_permission.html")

    # 待审队列：待预审、已预审、预警拦截、复核中
    queue = Prescription.objects.filter(
        status__in=["SUBMITTED", "PRECHECKED", "ALERTED", "REVIEWING"],
        is_deleted=False,
    ).select_related("patient", "doctor__user").order_by("created_at")

    # 按预警等级排序：预警拦截优先
    order = {"ALERTED": 0, "SUBMITTED": 1, "PRECHECKED": 2, "REVIEWING": 3}
    queue = sorted(queue, key=lambda p: order.get(p.status, 9))

    return render(request, "reviews/workbench.html", {"queue": queue})


@login_required
def review_detail(request, pk):
    """审核详情：预审命中规则 + 复核操作。"""
    if not has_permission(request.user, "审核:读"):
        return render(request, "reviews/no_permission.html")
    prescription = get_object_or_404(Prescription, pk=pk, is_deleted=False)

    # 执行/读取预审结果
    precheck = engine.precheck_prescription(prescription)
    items = prescription.items.select_related("herb").all()
    history = prescription.review_records.all().order_by("created_at")

    return render(request, "reviews/review_detail.html", {
        "prescription": prescription,
        "items": items,
        "precheck": precheck,
        "history": history,
    })


# ============ API 接口 ============

def api_review_tasks(request):
    """GET /api/v1/reviews/tasks 药师待审队列。"""
    if not request.user.is_authenticated:
        return JsonResponse({"code": 401, "message": "未登录"}, status=401)
    if not has_permission(request.user, "审核:读"):
        return JsonResponse({"code": 403, "message": "无权限"}, status=403)

    queue = Prescription.objects.filter(
        status__in=["SUBMITTED", "PRECHECKED", "ALERTED", "REVIEWING"], is_deleted=False
    ).select_related("patient", "doctor__user").order_by("created_at")

    items = []
    for p in queue:
        items.append({
            "id": p.id,
            "presc_no": p.presc_no,
            "patient_name": p.patient.name,
            "doctor_name": p.doctor.user.get_full_name() or p.doctor.user.username,
            "status": p.status,
            "status_display": p.get_status_display(),
            "created_at": p.created_at.isoformat(),
        })
    return JsonResponse({"code": 200, "message": "ok", "data": {"items": items, "total": len(items)}})


def api_review_detail(request, pk):
    """GET /api/v1/reviews/{id} 审核详情与命中规则。"""
    if not request.user.is_authenticated:
        return JsonResponse({"code": 401, "message": "未登录"}, status=401)
    if not has_permission(request.user, "审核:读"):
        return JsonResponse({"code": 403, "message": "无权限"}, status=403)

    prescription = get_object_or_404(Prescription, pk=pk)
    precheck = engine.precheck_prescription(prescription)
    items = list(
        prescription.items.select_related("herb").values(
            "herb__name", "dose", "unit", "decoction", "usage"
        )
    )
    return JsonResponse({
        "code": 200, "message": "ok",
        "data": {
            "id": prescription.id,
            "presc_no": prescription.presc_no,
            "diagnosis": prescription.diagnosis,
            "syndrome": prescription.syndrome,
            "status": prescription.status,
            "items": items,
            "precheck": precheck,
        },
    })


def api_review_claim(request, pk):
    """POST /api/v1/reviews/{id}/claim 领取审核任务。"""
    if not has_permission(request.user, "审核:领取"):
        return JsonResponse({"code": 403, "message": "无权限"}, status=403)
    prescription = get_object_or_404(Prescription, pk=pk)

    # 同一处方仅允许一名药师领取（已进入复核中则不可再领取）
    if prescription.status == "REVIEWING":
        return JsonResponse({"code": 409, "message": "该处方已被领取"}, status=409)

    ok, target = state_machine.transition(prescription, "claim")
    if not ok:
        return JsonResponse({"code": 409, "message": target}, status=409)
    return JsonResponse({"code": 200, "message": "领取成功", "data": {"status": target}})


def api_review_approve(request, pk):
    """POST /api/v1/reviews/{id}/approve 复核通过或带条件放行。"""
    if not has_permission(request.user, "审核:通过"):
        return JsonResponse({"code": 403, "message": "无权限"}, status=403)

    prescription = get_object_or_404(Prescription, pk=pk)
    data = json.loads(request.body or "{}")
    opinion = data.get("opinion", "")
    alert_note = data.get("alert_note", "")

    # 预警拦截状态放行：强制填写异常备注（双签确认逻辑简化为备注必填）
    if prescription.status == "ALERTED" and not alert_note:
        return JsonResponse({"code": 422, "message": "预警拦截处方放行必须填写异常备注"}, status=422)

    pharmacist = getattr(request.user, "pharmacist", None)

    with transaction.atomic():
        # 预警拦截需先放行到复核中，再通过
        if prescription.status == "ALERTED":
            ok, target = state_machine.transition(prescription, "release")
            if not ok:
                return JsonResponse({"code": 409, "message": target}, status=409)
        ok, target = state_machine.transition(prescription, "approve")
        if not ok:
            return JsonResponse({"code": 409, "message": target}, status=409)

        precheck = engine.precheck_prescription(prescription)
        ReviewRecord.objects.create(
            prescription=prescription,
            precheck_result=precheck["result_text"],
            review_opinion=opinion or "复核通过",
            pharmacist=pharmacist,
            alert_note=alert_note,
        )

    _log(request, "REVIEW_APPROVE", "prescription", str(pk), f"审核通过 {prescription.presc_no}")
    return JsonResponse({"code": 200, "message": "复核通过", "data": {"status": target}})


def api_review_reject(request, pk):
    """POST /api/v1/reviews/{id}/reject 退回并记录理由。"""
    if not has_permission(request.user, "审核:退回"):
        return JsonResponse({"code": 403, "message": "无权限"}, status=403)

    prescription = get_object_or_404(Prescription, pk=pk)
    data = json.loads(request.body or "{}")
    opinion = data.get("opinion", "")

    if not opinion:
        return JsonResponse({"code": 422, "message": "退回必须填写退回理由"}, status=422)

    pharmacist = getattr(request.user, "pharmacist", None)
    with transaction.atomic():
        ok, target = state_machine.transition(prescription, "reject")
        if not ok:
            return JsonResponse({"code": 409, "message": target}, status=409)

        ReviewRecord.objects.create(
            prescription=prescription,
            precheck_result="",
            review_opinion=f"退回：{opinion}",
            pharmacist=pharmacist,
            alert_note=opinion,
        )

    _log(request, "REVIEW_REJECT", "prescription", str(pk), f"退回 {prescription.presc_no}：{opinion}")
    return JsonResponse({"code": 200, "message": "已退回", "data": {"status": target}})


def api_review_history(request, pk):
    """GET /api/v1/reviews/{id}/history 查看审核轨迹。"""
    if not request.user.is_authenticated:
        return JsonResponse({"code": 401, "message": "未登录"}, status=401)
    prescription = get_object_or_404(Prescription, pk=pk)
    history = list(
        prescription.review_records.all().values(
            "id", "precheck_result", "review_opinion", "alert_note",
            "pharmacist__user__username", "created_at"
        ).order_by("created_at")
    )
    return JsonResponse({"code": 200, "message": "ok", "data": history})


def _log(request, action_type, object_type, object_id, detail):
    from apps.stats.models import OperationLog
    OperationLog.objects.create(
        operator=request.user,
        action_type=action_type,
        object_type=object_type,
        object_id=object_id,
        detail=detail,
        ip=get_client_ip(request),
        result="success",
    )
