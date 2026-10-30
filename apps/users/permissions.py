"""RBAC 权限校验工具。

提供接口级权限装饰器与角色判断辅助函数，
实现"菜单—操作—接口"三级权限控制。
"""
from functools import wraps

from django.http import JsonResponse


def get_user_roles(user):
    """获取用户的所有角色编码。"""
    if not user or not user.is_authenticated:
        return set()
    return set(
        user.userrole_set.values_list("role__code", flat=True)
    )


def get_user_permissions(user):
    """获取用户的所有权限编码。"""
    if not user or not user.is_authenticated:
        return set()
    return set(
        RolePermission.objects.filter(
            role__userrole__user=user
        ).values_list("permission__code", flat=True)
    )


def has_permission(user, perm_code):
    """判断用户是否拥有某权限。"""
    return perm_code in get_user_permissions(user)


def permission_required(perm_code):
    """接口级权限装饰器。

    校验失败返回 403 并记入日志，避免"隐藏按钮但接口可调用"的越权漏洞。
    """

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return JsonResponse({"code": 401, "message": "未登录或会话过期"}, status=401)
            if not has_permission(request.user, perm_code):
                # 越权尝试记入操作日志
                from apps.stats.models import OperationLog
                OperationLog.objects.create(
                    operator=request.user,
                    action_type="ACCESS_DENIED",
                    object_type="api",
                    object_id=perm_code,
                    detail=f"越权访问接口：{perm_code}",
                    ip=get_client_ip(request),
                    result="denied",
                )
                return JsonResponse({"code": 403, "message": "无权限访问"}, status=403)
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


def get_client_ip(request):
    """获取客户端 IP。"""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


# 导入放在文件末尾，避免循环导入
from apps.users.models import RolePermission  # noqa: E402
