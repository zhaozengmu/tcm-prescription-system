"""用户、角色、权限、医师档案模型。

对应数据存储 D1（用户与权限库），支撑 RBAC 三级权限：
菜单权限、操作权限、接口权限。
"""
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """系统用户，扩展中医业务字段。

    账号与医师档案一一对应；角色通过多对多关联。
    """

    phone = models.CharField("联系电话", max_length=20, blank=True, null=True)
    # 登录失败锁定相关
    failed_attempts = models.IntegerField("连续失败次数", default=0)
    locked_until = models.DateTimeField("锁定截止时间", null=True, blank=True)

    class Meta:
        verbose_name = "用户"
        verbose_name_plural = "用户"

    def __str__(self):
        return f"{self.username}（{self.get_full_name()}）"


class Role(models.Model):
    """角色，如医师、药师、管理员、患者。"""

    code = models.CharField("角色编码", max_length=32, unique=True)
    name = models.CharField("角色名称", max_length=64)
    description = models.CharField("角色描述", max_length=200, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "角色"
        verbose_name_plural = "角色"

    def __str__(self):
        return self.name


class Permission(models.Model):
    """权限点，对应菜单/操作/接口三级资源。

    编码示例：患者:读、患者:新增、处方:提交、审核:通过 等。
    """

    LEVEL_CHOICES = [
        ("menu", "菜单权限"),
        ("action", "操作权限"),
        ("api", "接口权限"),
    ]
    code = models.CharField("权限编码", max_length=64, unique=True)
    name = models.CharField("权限名称", max_length=64)
    level = models.CharField("权限层级", max_length=16, choices=LEVEL_CHOICES, default="action")
    description = models.CharField("权限描述", max_length=200, blank=True)

    class Meta:
        verbose_name = "权限"
        verbose_name_plural = "权限"

    def __str__(self):
        return f"{self.name}({self.code})"


class RolePermission(models.Model):
    """角色与权限多对多关联。"""

    role = models.ForeignKey(Role, on_delete=models.CASCADE, verbose_name="角色")
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, verbose_name="权限")

    class Meta:
        verbose_name = "角色权限"
        verbose_name_plural = "角色权限"
        unique_together = ("role", "permission")

    def __str__(self):
        return f"{self.role} - {self.permission}"


class UserRole(models.Model):
    """用户与角色多对多关联。"""

    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="用户")
    role = models.ForeignKey(Role, on_delete=models.CASCADE, verbose_name="角色")

    class Meta:
        verbose_name = "用户角色"
        verbose_name_plural = "用户角色"
        unique_together = ("user", "role")

    def __str__(self):
        return f"{self.user} - {self.role}"


class Doctor(models.Model):
    """医师档案，与用户 1:1 关联。"""

    user = models.OneToOneField(User, on_delete=models.CASCADE, verbose_name="关联用户", related_name="doctor")
    license_no = models.CharField("执业证号", max_length=64, blank=True)
    department = models.CharField("科室", max_length=64, blank=True)
    title = models.CharField("职称", max_length=32, blank=True)
    clinic_hours = models.CharField("出诊时间", max_length=100, blank=True)
    signature_image = models.FileField("电子签名图片", upload_to="signatures/", blank=True, null=True)
    is_active = models.BooleanField("是否启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "医师档案"
        verbose_name_plural = "医师档案"

    def __str__(self):
        return self.user.get_full_name() or self.user.username


class Pharmacist(models.Model):
    """药师档案，与用户 1:1 关联。"""

    user = models.OneToOneField(User, on_delete=models.CASCADE, verbose_name="关联用户", related_name="pharmacist")
    license_no = models.CharField("执业证号", max_length=64, blank=True)
    is_active = models.BooleanField("是否启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "药师档案"
        verbose_name_plural = "药师档案"

    def __str__(self):
        return self.user.get_full_name() or self.user.username
