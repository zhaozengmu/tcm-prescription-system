"""处方开具管理视图。

医师创建处方、维护药味明细、提交预审、查询本人处方。
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.contrib import messages
import json

from .models import Prescription, PrescriptionItem, Herb, FormulaTemplate, HerbBatch, Supplier
from apps.patients.models import Patient
from apps.reviews import engine, state_machine
from apps.users.permissions import has_permission, get_client_ip


@login_required
def prescription_list(request):
    """医师查看本人处方列表。"""
    doctor = getattr(request.user, "doctor", None)
    if not doctor:
        return render(request, "prescriptions/no_permission.html")
    qs = Prescription.objects.filter(doctor=doctor, is_deleted=False).select_related("patient").order_by("-created_at")
    return render(request, "prescriptions/prescription_list.html", {"prescriptions": qs})


@login_required
def prescription_create(request):
    """创建处方草稿页面。"""
    doctor = getattr(request.user, "doctor", None)
    if not doctor:
        return render(request, "prescriptions/no_permission.html")
    patients = Patient.objects.filter(is_deleted=False).order_by("-last_visit_at")
    templates = FormulaTemplate.objects.all()
    herbs = Herb.objects.all().order_by("pinyin", "name")
    return render(request, "prescriptions/prescription_form.html", {
        "patients": patients, "templates": templates, "herbs": herbs,
    })


@login_required
def prescription_detail(request, pk):
    """处方详情。"""
    prescription = get_object_or_404(Prescription, pk=pk)
    items = prescription.items.select_related("herb").all()
    return render(request, "prescriptions/prescription_detail.html", {
        "prescription": prescription, "items": items,
    })


@login_required
def herb_list(request):
    """药材字典管理页（拼音首字母检索、产地/炮制/库存展示）。"""
    if not has_permission(request.user, "字典:维护"):
        return render(request, "prescriptions/no_permission.html")
    q = request.GET.get("q", "").strip()
    herbs = Herb.objects.all().order_by("pinyin_initial", "name")
    if q:
        herbs = herbs.filter(
            Q(name__icontains=q)
            | Q(pinyin_initial__icontains=q.upper())
            | Q(origin__icontains=q)
            | Q(processing__icontains=q)
            | Q(efficacy__icontains=q)
        )
    return render(request, "prescriptions/herb_list.html", {"herbs": herbs, "q": q})


@login_required
def herb_card(request, pk):
    """药材信息卡片（打印/PDF 导出）。"""
    herb = get_object_or_404(Herb, pk=pk)
    batches = herb.batches.select_related("supplier").order_by("-inbound_at")
    return render(request, "prescriptions/herb_card.html", {"herb": herb, "batches": batches})


@login_required
def herb_card_pdf(request, pk):
    """药材信息卡片 PDF 导出。"""
    herb = get_object_or_404(Herb, pk=pk)
    batches = herb.batches.select_related("supplier").order_by("-inbound_at")
    html = render(request, "prescriptions/herb_card.html", {"herb": herb, "batches": batches}).content.decode("utf-8")
    return _html_to_pdf_response(html, f"药材卡片_{herb.name}.pdf")


@login_required
def herb_import(request):
    """药材字典 Excel 批量导入页面。"""
    if not has_permission(request.user, "字典:维护"):
        return render(request, "prescriptions/no_permission.html")
    if request.method == "POST":
        f = request.FILES.get("file")
        if not f:
            messages.error(request, "请选择要上传的 Excel 文件")
            return redirect("prescriptions:herb_list")
        result = _import_herbs_excel(f)
        messages.success(request, f"导入完成：成功 {result['success']} 条，跳过 {result['skip']} 条")
        return redirect("prescriptions:herb_list")
    return render(request, "prescriptions/herb_import.html")


# ============ API 接口 ============

def api_prescription_create(request):
    """POST /api/v1/prescriptions 新建处方（草稿）。"""
    if not request.user.is_authenticated:
        return JsonResponse({"code": 401, "message": "未登录"}, status=401)
    if not has_permission(request.user, "处方:新增"):
        return JsonResponse({"code": 403, "message": "无权限"}, status=403)

    doctor = getattr(request.user, "doctor", None)
    if not doctor:
        return JsonResponse({"code": 403, "message": "当前用户非医师"}, status=403)

    data = json.loads(request.body or "{}")
    patient_id = data.get("patient_id")
    patient = get_object_or_404(Patient, pk=patient_id, is_deleted=False)

    pickup_time_raw = data.get("pickup_time") or ""
    from django.utils.dateparse import parse_datetime
    pickup_time = parse_datetime(pickup_time_raw)
    prescription = Prescription.objects.create(
        presc_no=Prescription.generate_presc_no(),
        patient=patient,
        doctor=doctor,
        diagnosis=data.get("diagnosis", ""),
        syndrome=data.get("syndrome", ""),
        presc_type=data.get("presc_type", "OUTPATIENT"),
        decoction_note=data.get("decoction_note", ""),
        pickup_time=pickup_time,
        pickup_person=data.get("pickup_person", ""),
        status="DRAFT",
    )
    _log(request, "CREATE", "prescription", str(prescription.id), f"创建处方 {prescription.presc_no}")
    return JsonResponse({"code": 200, "message": "ok", "data": {"id": prescription.id, "presc_no": prescription.presc_no}})


def api_prescription_items(request, pk):
    """PUT /api/v1/prescriptions/{id} 修改草稿明细。"""
    if not request.user.is_authenticated:
        return JsonResponse({"code": 401, "message": "未登录"}, status=401)
    if not has_permission(request.user, "处方:修改"):
        return JsonResponse({"code": 403, "message": "无权限"}, status=403)

    prescription = get_object_or_404(Prescription, pk=pk)
    if prescription.status != "DRAFT":
        return JsonResponse({"code": 409, "message": "仅草稿状态可修改明细"}, status=409)

    data = json.loads(request.body or "{}")
    items = data.get("items", [])  # [{herb_id, dose, decoction, usage}]

    with transaction.atomic():
        # 清空重建明细
        prescription.items.all().delete()
        for it in items:
            herb = get_object_or_404(Herb, pk=it.get("herb_id"))
            PrescriptionItem.objects.create(
                prescription=prescription,
                herb=herb,
                dose=it.get("dose", 0),
                unit=it.get("unit", "g"),
                decoction=it.get("decoction", ""),
                usage=it.get("usage", ""),
            )

    _log(request, "UPDATE", "prescription", str(pk), f"修改处方明细 {prescription.presc_no}")
    return JsonResponse({"code": 200, "message": "明细已保存", "data": {"id": pk}})


def api_prescription_submit(request, pk):
    """POST /api/v1/prescriptions/{id}/submit 提交待预审。"""
    if not request.user.is_authenticated:
        return JsonResponse({"code": 401, "message": "未登录"}, status=401)
    if not has_permission(request.user, "处方:提交"):
        return JsonResponse({"code": 403, "message": "无权限"}, status=403)

    prescription = get_object_or_404(Prescription, pk=pk)
    if not prescription.items.exists():
        return JsonResponse({"code": 422, "message": "处方明细为空，无法提交"}, status=422)

    # 剂量上限校验（模型层业务规则）
    for item in prescription.items.select_related("herb"):
        if item.herb.max_dose and float(item.dose) > float(item.herb.max_dose):
            return JsonResponse({
                "code": 422,
                "message": f"药材 {item.herb.name} 剂量 {item.dose}g 超过上限 {item.herb.max_dose}g",
            }, status=422)

    with transaction.atomic():
        ok, target = state_machine.transition(prescription, "submit")
        if not ok:
            return JsonResponse({"code": 409, "message": target}, status=409)

        # 触发规则预审
        precheck = engine.precheck_prescription(prescription)
        if precheck["blocked"]:
            state_machine.transition(prescription, "precheck_block")
        else:
            state_machine.transition(prescription, "precheck_pass")

    _log(request, "SUBMIT", "prescription", str(pk), f"提交处方 {prescription.presc_no}")

    # 提交后通知药师待审
    from apps.users.models import User, Role
    from apps.reviews.models import Notification
    pharmacist_role = Role.objects.filter(code="pharmacist").first()
    if pharmacist_role:
        for u in User.objects.filter(userrole__role=pharmacist_role).distinct():
            Notification.objects.create(
                recipient=u,
                title="新处方待审核",
                content=f"处方 {prescription.presc_no} 已提交，请及时审核",
                level="WARN" if precheck["blocked"] else "INFO",
            )

    return JsonResponse({
        "code": 200, "message": "已提交预审",
        "data": {"status": prescription.status, "precheck": precheck},
    })


@login_required
def prescription_print(request, pk):
    """处方单 A4 打印视图（含处方编号、医师/药师签章位置）。"""
    prescription = get_object_or_404(Prescription, pk=pk)
    items = prescription.items.select_related("herb").all()
    reviews = prescription.review_records.select_related("pharmacist__user").order_by("created_at")
    return render(request, "prescriptions/prescription_print.html", {
        "prescription": prescription, "items": items, "reviews": reviews,
    })


@login_required
def prescription_pdf(request, pk):
    """处方单 PDF 导出（复用打印样式，生成 PDF 供下载）。"""
    prescription = get_object_or_404(Prescription, pk=pk)
    items = prescription.items.select_related("herb").all()
    reviews = prescription.review_records.select_related("pharmacist__user").order_by("created_at")
    html = render(request, "prescriptions/prescription_print.html", {
        "prescription": prescription, "items": items, "reviews": reviews,
    }).content.decode("utf-8")
    return _html_to_pdf_response(html, f"处方单_{prescription.presc_no}.pdf")


def api_formula_detail(request, formula_id):
    """GET /api/v1/formulas/{id} 方剂模板详情（一键引用）。"""
    if not request.user.is_authenticated:
        return JsonResponse({"code": 401, "message": "未登录"}, status=401)
    formula = get_object_or_404(FormulaTemplate, pk=formula_id)
    items = list(
        formula.items.select_related("herb").values(
            "herb_id", "herb__name", "dose", "unit"
        )
    )
    return JsonResponse({"code": 200, "message": "ok", "data": {"name": formula.name, "items": items}})


def _log(request, action_type, object_type, object_id, detail):
    from apps.stats.models import OperationLog
    OperationLog.objects.create(
        operator=request.user, action_type=action_type, object_type=object_type,
        object_id=object_id, detail=detail, ip=get_client_ip(request), result="success",
    )


def _html_to_pdf_response(html, filename):
    """将 HTML 转成 PDF 响应（优先 WeasyPrint，回退返回可打印的 HTML）。"""
    try:
        from weasyprint import HTML
        pdf = HTML(string=html).write_pdf()
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
    except Exception:
        # 无 WeasyPrint 时，返回带打印按钮的 HTML，浏览器 Ctrl+P 即可打印/存 PDF
        response = HttpResponse(html, content_type="text/html; charset=utf-8")
        return response


def _import_herbs_excel(fileobj):
    """解析 Excel 批量导入药材。返回 {"success": n, "skip": n}。"""
    import io
    import openpyxl

    success = 0
    skip = 0
    try:
        wb = openpyxl.load_workbook(io.BytesIO(fileobj.read()), data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return {"success": 0, "skip": 0}
        # 表头：药材名称, 拼音首字母, 类别, 性味归经, 功效主治, 道地产地, 炮制规格, 剂量上限, 毒性, 常用剂量, 单位, 库存, 预警线
        header = [str(c).strip() if c else "" for c in rows[0]]
        for row in rows[1:]:
            if not row or not row[0]:
                continue
            name = str(row[0]).strip()
            if not name:
                skip += 1
                continue
            defaults = {}
            field_map = {
                "拼音首字母": "pinyin_initial",
                "类别": "category",
                "性味归经": "property",
                "功效主治": "efficacy",
                "道地产地": "origin",
                "炮制规格": "processing",
                "单位": "unit",
            }
            for idx, col in enumerate(header):
                if col in field_map and idx < len(row) and row[idx] is not None:
                    defaults[field_map[col]] = str(row[idx]).strip()
            # 拼音
            if "拼音" in header:
                idx = header.index("拼音")
                if idx < len(row) and row[idx]:
                    defaults["pinyin"] = str(row[idx]).strip()
            # 剂量上限
            if "剂量上限" in header:
                idx = header.index("剂量上限")
                if idx < len(row) and row[idx] not in (None, ""):
                    try:
                        defaults["max_dose"] = float(row[idx])
                    except (ValueError, TypeError):
                        pass
            # 常用剂量
            if "常用剂量" in header:
                idx = header.index("常用剂量")
                if idx < len(row) and row[idx] not in (None, ""):
                    try:
                        defaults["default_dose"] = float(row[idx])
                    except (ValueError, TypeError):
                        pass
            # 毒性
            if "毒性" in header:
                idx = header.index("毒性")
                if idx < len(row) and row[idx] not in (None, ""):
                    defaults["is_toxic"] = str(row[idx]).strip() in ("是", "1", "true", "True", "毒")
            # 库存 / 预警线
            if "库存" in header:
                idx = header.index("库存")
                if idx < len(row) and row[idx] not in (None, ""):
                    try:
                        defaults["stock"] = float(row[idx])
                    except (ValueError, TypeError):
                        pass
            if "预警线" in header:
                idx = header.index("预警线")
                if idx < len(row) and row[idx] not in (None, ""):
                    try:
                        defaults["stock_warning"] = float(row[idx])
                    except (ValueError, TypeError):
                        pass

            # 自动补全拼音首字母
            if not defaults.get("pinyin_initial") and defaults.get("pinyin"):
                defaults["pinyin_initial"] = "".join(w[0] for w in defaults["pinyin"].split()).upper()

            _, created = Herb.objects.get_or_create(name=name, defaults=defaults)
            if created:
                success += 1
            else:
                skip += 1
        return {"success": success, "skip": skip}
    except Exception:
        return {"success": 0, "skip": 0}
