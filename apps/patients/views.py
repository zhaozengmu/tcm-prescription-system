"""患者信息管理视图。"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.utils import timezone
import json

from .models import Patient
from apps.users.permissions import permission_required, has_permission, get_client_ip
from apps.utils.crypto import encrypt, decrypt, mask_id_card, mask_phone, hash_value


@login_required
def patient_list(request):
    """患者列表：分页 + 关键字 + 条件筛选。"""
    qs = Patient.objects.filter(is_deleted=False)

    name = request.GET.get("name", "").strip()
    patient_no = request.GET.get("patient_no", "").strip()
    gender = request.GET.get("gender", "").strip()
    age_min = request.GET.get("age_min", "").strip()
    age_max = request.GET.get("age_max", "").strip()

    if name:
        qs = qs.filter(name__icontains=name)
    if patient_no:
        qs = qs.filter(patient_no__icontains=patient_no)
    if gender:
        qs = qs.filter(gender=gender)
    if age_min:
        qs = qs.filter(age__gte=int(age_min))
    if age_max:
        qs = qs.filter(age__lte=int(age_max))

    qs = qs.order_by("-last_visit_at", "-created_at")
    paginator = Paginator(qs, 20)
    page = paginator.get_page(request.GET.get("page", 1))

    # 列表页掩码展示
    for p in page.object_list:
        p.masked_id_card = mask_id_card(decrypt(p.id_card_encrypted)) if p.id_card_encrypted else ""
        p.masked_phone = mask_phone(decrypt(p.phone_encrypted)) if p.phone_encrypted else ""

    return render(request, "patients/patient_list.html", {"page": page})


@login_required
def patient_detail(request, pk):
    """患者详情：按权限解密敏感字段。"""
    patient = get_object_or_404(Patient, pk=pk, is_deleted=False)
    can_view_sensitive = has_permission(request.user, "患者:读")
    if can_view_sensitive:
        patient.id_card = decrypt(patient.id_card_encrypted) if patient.id_card_encrypted else ""
        patient.phone = decrypt(patient.phone_encrypted) if patient.phone_encrypted else ""
    else:
        patient.id_card = mask_id_card(decrypt(patient.id_card_encrypted)) if patient.id_card_encrypted else ""
        patient.phone = mask_phone(decrypt(patient.phone_encrypted)) if patient.phone_encrypted else ""
    return render(request, "patients/patient_detail.html", {"patient": patient, "can_view_sensitive": can_view_sensitive})


def api_patient_list(request):
    """GET /api/v1/patients 患者分页与条件检索。"""
    if not request.user.is_authenticated:
        return JsonResponse({"code": 401, "message": "未登录"}, status=401)
    if not has_permission(request.user, "患者:读"):
        return JsonResponse({"code": 403, "message": "无权限"}, status=403)

    qs = Patient.objects.filter(is_deleted=False)
    name = request.GET.get("name", "")
    if name:
        qs = qs.filter(name__icontains=name)

    page = int(request.GET.get("page", 1))
    page_size = int(request.GET.get("page_size", 20))
    paginator = Paginator(qs.order_by("-created_at"), page_size)
    items = []
    for p in paginator.get_page(page):
        items.append({
            "id": p.id,
            "patient_no": p.patient_no,
            "name": p.name,
            "gender": p.get_gender_display(),
            "age": p.age,
            "id_card": mask_id_card(decrypt(p.id_card_encrypted)) if p.id_card_encrypted else "",
            "phone": mask_phone(decrypt(p.phone_encrypted)) if p.phone_encrypted else "",
        })
    return JsonResponse({
        "code": 200, "message": "ok",
        "data": {"items": items, "total": paginator.count, "page": page, "page_size": page_size},
    })


def api_patient_create(request):
    """POST /api/v1/patients 患者建档。"""
    if not request.user.is_authenticated:
        return JsonResponse({"code": 401, "message": "未登录"}, status=401)
    if not has_permission(request.user, "患者:新增"):
        return JsonResponse({"code": 403, "message": "无权限"}, status=403)

    data = json.loads(request.body or "{}")
    name = data.get("name", "").strip()
    if not name:
        return JsonResponse({"code": 400, "message": "姓名必填"}, status=400)

    id_card = data.get("id_card", "")
    phone = data.get("phone", "")

    patient = Patient(
        patient_no=Patient.generate_patient_no(),
        name=name,
        gender=data.get("gender", "U"),
        age=data.get("age"),
        id_card_encrypted=encrypt(id_card),
        id_card_hash=hash_value(id_card),
        phone_encrypted=encrypt(phone),
        phone_hash=hash_value(phone),
        allergy_history=data.get("allergy_history", ""),
        pregnancy_status=data.get("pregnancy_status", "NONE"),
        visit_summary=data.get("visit_summary", ""),
    )
    patient.save()

    from apps.stats.models import OperationLog
    OperationLog.objects.create(
        operator=request.user, action_type="CREATE", object_type="patient",
        object_id=str(patient.id), detail=f"建档患者 {patient.name}", ip=get_client_ip(request), result="success",
    )
    return JsonResponse({"code": 200, "message": "ok", "data": {"id": patient.id, "patient_no": patient.patient_no}})
