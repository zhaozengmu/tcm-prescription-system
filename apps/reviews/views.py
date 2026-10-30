"""处方审核管理视图。

药师工作台：待审队列、领取/转交、初审/复审、退回、发药、附件与轨迹，
以及消息通知（处方提交提醒药师、驳回/通过提醒医师）。
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.utils import timezone
from django.db import transaction
import json

from apps.prescriptions.models import Prescription, PrescriptionItem
from apps.reviews.models import ReviewRecord, DispenseRecord, Notification
from apps.reviews import engine, state_machine
from apps.users.models import User, Role
from apps.users.permissions import has_permission, get_client_ip


def _notify_user(user, title, content, level="INFO"):
    """给指定用户发消息通知。"""
    Notification.objects.create(recipient=user, title=title, content=content, level=level)


def _notify_pharmacists(title, content, level="INFO"):
    """通知所有药师（拥有审核权限的用户）。"""
    pharmacist_role = Role.objects.filter(code="pharmacist").first()
    if not pharmacist_role:
        return
    users = User.objects.filter(userrole__role=pharmacist_role).distinct()
    for u in users:
        _notify_user(u, title, content, level)


@login_required
def review_workbench(request):
    """药师工作台：待审队列（含初审、复审）。"""
    if not has_permission(request.user, "审核:读"):
        return render(request, "reviews/no_permission.html")

    queue = Prescription.objects.filter(
        status__in=["SUBMITTED", "PRECHECKED", "ALERTED", "REVIEWING", "FINAL_REVIEWING"],
        is_deleted=False,
    ).select_related("patient", "doctor__user").order_by("created_at")

    order = {"ALERTED": 0, "SUBMITTED": 1, "PRECHECKED": 2, "REVIEWING": 3, "FINAL_REVIEWING": 4}
    queue = sorted(queue, key=lambda p: order.get(p.status, 9))

    return render(request, "reviews/workbench.html", {"queue": queue})


@login_required
def review_detail(request, pk):
    """审核详情：预审命中规则 + 初审/复审操作。"""
    if not has_permission(request.user, "审核:读"):
        return render(request, "reviews/no_permission.html")
    prescription = get_object_or_404(Prescription, pk=pk, is_deleted=False)

    precheck = engine.precheck_prescription(prescription)
    items = prescription.items.select_related("herb").all()
    history = prescription.review_records.all().order_by("created_at")
    can_final_review = has_permission(request.user, "审核:复审")

    return render(request, "reviews/review_detail.html", {
        "prescription": prescription,
        "items": items,
        "precheck": precheck,
        "history": history,
        "can_final_review": can_final_review,
    })


@login_required
def notifications_view(request):
    """我的消息通知。"""
    notifications = request.user.notifications.all()[:50]
    return render(request, "reviews/notifications.html", {"notifications": notifications})


# ============ API 接口 ============

def api_review_tasks(request):
    """GET /api/v1/reviews/tasks 药师待审队列。"""
    if not request.user.is_authenticated:
        return JsonResponse({"code": 401, "message": "未登录"}, status=401)
    if not has_permission(request.user, "审核:读"):
        return JsonResponse({"code": 403, "message": "无权限"}, status=403)

    queue = Prescription.objects.filter(
        status__in=["SUBMITTED", "PRECHECKED", "ALERTED", "REVIEWING", "FINAL_REVIEWING"],
        is_deleted=False,
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

    if prescription.status in ("REVIEWING", "FINAL_REVIEWING"):
        return JsonResponse({"code": 409, "message": "该处方已被领取"}, status=409)

    ok, target = state_machine.transition(prescription, "claim")
    if not ok:
        return JsonResponse({"code": 409, "message": target}, status=409)
    return JsonResponse({"code": 200, "message": "领取成功", "data": {"status": target}})


def api_review_approve(request, pk):
    """POST /api/v1/reviews/{id}/approve 初审通过（进入复审）或复审通过（归档）。"""
    prescription = get_object_or_404(Prescription, pk=pk)
    is_final = (prescription.status == "FINAL_REVIEWING")

    # 按当前审核级别校验权限：初审需「审核:通过」，复审需「审核:复审」
    required_perm = "审核:复审" if is_final else "审核:通过"
    if not has_permission(request.user, required_perm):
        return JsonResponse({"code": 403, "message": "无权限"}, status=403)

    data = json.loads(request.body or "{}")
    opinion = data.get("opinion", "")
    alert_note = data.get("alert_note", "")
    adverse_note = data.get("adverse_note", "")

    # 预警拦截状态放行：强制填写异常备注
    if prescription.status == "ALERTED" and not alert_note:
        return JsonResponse({"code": 422, "message": "预警拦截处方放行必须填写异常备注"}, status=422)

    pharmacist = getattr(request.user, "pharmacist", None)
    is_final = (prescription.status == "FINAL_REVIEWING")

    with transaction.atomic():
        # 预警拦截需先放行到初审中
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
            review_level="FINAL" if is_final else "INITIAL",
            precheck_result=precheck["result_text"],
            review_opinion=opinion or ("复审通过" if is_final else "初审通过"),
            pharmacist=pharmacist,
            alert_note=alert_note,
            adverse_note=adverse_note,
        )

        # 复审通过后通知开方医师
        if target == "APPROVED":
            doctor_user = prescription.doctor.user
            _notify_user(doctor_user, "处方审核通过", f"处方 {prescription.presc_no} 已通过审核", "INFO")

    _log(request, "REVIEW_APPROVE", "prescription", str(pk),
         f"{'复审' if is_final else '初审'}通过 {prescription.presc_no}")
    msg = "复审通过，处方已归档" if is_final else "初审通过，进入复审"
    return JsonResponse({"code": 200, "message": msg, "data": {"status": target}})


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
    is_final = (prescription.status == "FINAL_REVIEWING")
    with transaction.atomic():
        ok, target = state_machine.transition(prescription, "reject")
        if not ok:
            return JsonResponse({"code": 409, "message": target}, status=409)

        ReviewRecord.objects.create(
            prescription=prescription,
            review_level="FINAL" if is_final else "INITIAL",
            precheck_result="",
            review_opinion=f"退回：{opinion}",
            reject_reason=opinion,
            pharmacist=pharmacist,
            alert_note=opinion,
        )

        # 通知开方医师处方被退回
        doctor_user = prescription.doctor.user
        _notify_user(doctor_user, "处方被退回", f"处方 {prescription.presc_no} 被退回：{opinion}", "WARN")

    _log(request, "REVIEW_REJECT", "prescription", str(pk), f"退回 {prescription.presc_no}：{opinion}")
    return JsonResponse({"code": 200, "message": "已退回", "data": {"status": target}})


def api_review_history(request, pk):
    """GET /api/v1/reviews/{id}/history 查看审核轨迹。"""
    if not request.user.is_authenticated:
        return JsonResponse({"code": 401, "message": "未登录"}, status=401)
    prescription = get_object_or_404(Prescription, pk=pk)
    history = list(
        prescription.review_records.all().values(
            "id", "review_level", "precheck_result", "review_opinion", "reject_reason",
            "adverse_note", "pharmacist__user__username", "created_at"
        ).order_by("created_at")
    )
    return JsonResponse({"code": 200, "message": "ok", "data": history})


def api_dispense(request, pk):
    """POST /api/v1/reviews/{id}/dispense 药房发药确认。"""
    if not has_permission(request.user, "发药:确认"):
        return JsonResponse({"code": 403, "message": "无权限"}, status=403)

    prescription = get_object_or_404(Prescription, pk=pk)
    data = json.loads(request.body or "{}")

    with transaction.atomic():
        ok, target = state_machine.transition(prescription, "dispense")
        if not ok:
            return JsonResponse({"code": 409, "message": target}, status=409)

        DispenseRecord.objects.create(
            prescription=prescription,
            dispenser=request.user,
            checked_herbs=bool(data.get("checked_herbs", True)),
            note=data.get("note", ""),
        )

        # 通知开方医师已发药
        _notify_user(prescription.doctor.user, "处方已发药",
                     f"处方 {prescription.presc_no} 已完成发药", "INFO")

    _log(request, "DISPENSE", "prescription", str(pk), f"发药 {prescription.presc_no}")
    return JsonResponse({"code": 200, "message": "发药完成", "data": {"status": target}})


def api_notifications(request):
    """GET /api/v1/notifications 我的消息通知列表。"""
    if not request.user.is_authenticated:
        return JsonResponse({"code": 401, "message": "未登录"}, status=401)
    notifications = request.user.notifications.all()[:50]
    items = [{
        "id": n.id, "title": n.title, "content": n.content,
        "level": n.level, "is_read": n.is_read, "created_at": n.created_at.strftime("%Y-%m-%d %H:%M"),
    } for n in notifications]
    unread = request.user.notifications.filter(is_read=False).count()
    return JsonResponse({"code": 200, "message": "ok", "data": {"items": items, "unread": unread}})


def api_notification_read(request, pk):
    """POST /api/v1/notifications/{id}/read 标记已读。"""
    if not request.user.is_authenticated:
        return JsonResponse({"code": 401, "message": "未登录"}, status=401)
    n = get_object_or_404(Notification, pk=pk, recipient=request.user)
    n.is_read = True
    n.save(update_fields=["is_read"])
    return JsonResponse({"code": 200, "message": "ok", "data": None})


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
