"""用户登录、注册、退出与医师管理视图。"""
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils import timezone
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
import json

from .models import User, Role, Doctor, Pharmacist
from .permissions import has_permission, get_client_ip


def login_view(request):
    """账号密码登录，带图形验证码与失败锁定。"""
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        captcha = request.POST.get("captcha", "").strip()

        # 图形验证码校验（演示简化：固定验证码 demo，生产需接入真实图形验证码）
        session_captcha = request.session.get("captcha", "demo")
        if captcha.lower() != session_captcha.lower():
            messages.error(request, "验证码错误")
            return render(request, "users/login.html")

        user = User.objects.filter(username=username).first()
        if user and user.locked_until and user.locked_until > timezone.now():
            messages.error(request, "账号已锁定，请稍后再试")
            return render(request, "users/login.html")

        auth_user = authenticate(request, username=username, password=password)
        if auth_user is None:
            if user:
                user.failed_attempts += 1
                if user.failed_attempts >= settings.LOGIN_MAX_ATTEMPTS:
                    user.locked_until = timezone.now() + timezone.timedelta(
                        seconds=settings.LOGIN_LOCK_SECONDS
                    )
                    user.failed_attempts = 0
                    messages.error(request, "连续失败次数过多，账号已锁定 10 分钟")
                else:
                    user.save()
                    messages.error(request, "用户名或密码错误")
            else:
                messages.error(request, "用户名或密码错误")
            return render(request, "users/login.html")

        # 登录成功，重置失败计数
        user.failed_attempts = 0
        user.locked_until = None
        user.save()
        login(request, auth_user)

        # 记录登录日志
        from apps.stats.models import OperationLog
        OperationLog.objects.create(
            operator=auth_user,
            action_type="LOGIN",
            object_type="session",
            object_id=str(auth_user.id),
            detail="用户登录",
            ip=get_client_ip(request),
            result="success",
        )
        return redirect("dashboard:index")

    return render(request, "users/login.html")


def logout_view(request):
    """安全退出，销毁会话并记录日志。"""
    if request.user.is_authenticated:
        from apps.stats.models import OperationLog
        OperationLog.objects.create(
            operator=request.user,
            action_type="LOGOUT",
            object_type="session",
            object_id=str(request.user.id),
            detail="用户退出",
            ip=get_client_ip(request),
            result="success",
        )
    logout(request)
    return redirect("users:login")


@require_POST
def api_login(request):
    """API 登录接口：POST /api/v1/auth/login。"""
    data = json.loads(request.body or "{}")
    username = data.get("username", "")
    password = data.get("password", "")
    user = authenticate(request, username=username, password=password)
    if user is None:
        return JsonResponse({"code": 401, "message": "用户名或密码错误"}, status=401)
    login(request, user)
    return JsonResponse({
        "code": 200,
        "message": "ok",
        "data": {"id": user.id, "username": user.username, "name": user.get_full_name()},
    })


@require_POST
def api_logout(request):
    """API 退出接口：POST /api/v1/auth/logout。"""
    logout(request)
    return JsonResponse({"code": 200, "message": "ok", "data": None})


@login_required
def doctor_list(request):
    """医师列表与资料查询。"""
    from .permissions import has_permission as hp
    doctors = Doctor.objects.select_related("user").all()
    return render(request, "users/doctor_list.html", {"doctors": doctors})


def api_doctors(request):
    """GET /api/v1/doctors 医师列表。"""
    if not request.user.is_authenticated:
        return JsonResponse({"code": 401, "message": "未登录"}, status=401)
    doctors = list(
        Doctor.objects.select_related("user").values(
            "id", "user__username", "user__first_name", "license_no", "department", "title"
        )
    )
    return JsonResponse({"code": 200, "message": "ok", "data": doctors})
