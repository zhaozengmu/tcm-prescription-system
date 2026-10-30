"""中药字典、方剂模板、审核规则与处方模型。

对应数据存储：
- D3 中药与方剂字典：Herb、FormulaTemplate、FormulaItem、AuditRule
- D4 处方与明细库：Prescription、PrescriptionItem
"""
from django.db import models
from django.utils import timezone


class Herb(models.Model):
    """药材目录（中药字典）。"""

    name = models.CharField("药材名称", max_length=64, unique=True)
    pinyin = models.CharField("拼音", max_length=100, blank=True)
    category = models.CharField("类别", max_length=32, blank=True)
    property = models.CharField("性味归经", max_length=100, blank=True)
    max_dose = models.DecimalField("剂量上限(g)", max_digits=8, decimal_places=2, null=True, blank=True)
    is_toxic = models.BooleanField("是否毒性药材", default=False)
    default_dose = models.DecimalField("常用剂量(g)", max_digits=8, decimal_places=2, null=True, blank=True)
    unit = models.CharField("单位", max_length=8, default="g")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "药材目录"
        verbose_name_plural = "药材目录"

    def __str__(self):
        return self.name


class FormulaTemplate(models.Model):
    """方剂模板，支持一键引用。"""

    name = models.CharField("方剂名称", max_length=64, unique=True)
    category = models.CharField("类别", max_length=32, blank=True)
    indication = models.CharField("主治", max_length=200, blank=True)
    description = models.TextField("方解说明", blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "方剂模板"
        verbose_name_plural = "方剂模板"

    def __str__(self):
        return self.name


class FormulaItem(models.Model):
    """方剂模板明细（组成药味）。"""

    formula = models.ForeignKey(FormulaTemplate, on_delete=models.CASCADE, related_name="items", verbose_name="方剂")
    herb = models.ForeignKey(Herb, on_delete=models.CASCADE, verbose_name="药材")
    dose = models.DecimalField("剂量(g)", max_digits=8, decimal_places=2)
    unit = models.CharField("单位", max_length=8, default="g")

    class Meta:
        verbose_name = "方剂明细"
        verbose_name_plural = "方剂明细"
        unique_together = ("formula", "herb")

    def __str__(self):
        return f"{self.formula.name} - {self.herb.name}"


class AuditRule(models.Model):
    """审核规则（D3 规则库）。

    规则以数据形式存储，由管理员在线维护并记录版本，
    审核引擎按当前版本加载，实现规则与代码解耦。
    """

    RULE_TYPE_CHOICES = [
        ("18F", "十八反"),
        ("19W", "十九畏"),
        ("PR", "妊娠禁忌"),
        ("TX", "毒性剂量上限"),
        ("YY", "用法用量规范"),
        ("SP", "特殊人群"),
    ]
    LEVEL_CHOICES = [
        ("block", "强制拦截"),
        ("warn", "预警提示"),
    ]

    rule_no = models.CharField("规则编号", max_length=32, unique=True)
    rule_type = models.CharField("规则类型", max_length=8, choices=RULE_TYPE_CHOICES)
    herbs = models.CharField("涉及药材（逗号分隔）", max_length=200, blank=True)
    level = models.CharField("触发等级", max_length=8, choices=LEVEL_CHOICES, default="warn")
    message = models.CharField("提示文案", max_length=200)
    basis = models.CharField("依据", max_length=100, blank=True)
    version = models.CharField("版本", max_length=16, default="V1.0")
    is_active = models.BooleanField("是否启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "审核规则"
        verbose_name_plural = "审核规则"

    def __str__(self):
        return f"{self.rule_no} {self.message}"


class Prescription(models.Model):
    """处方主记录（D4）。"""

    STATUS_CHOICES = [
        ("DRAFT", "草稿"),
        ("SUBMITTED", "待预审"),
        ("PRECHECKED", "已预审"),
        ("ALERTED", "预警拦截"),
        ("REVIEWING", "复核中"),
        ("APPROVED", "已通过"),
        ("REJECTED", "已驳回"),
        ("DISPENSED", "已发药完结"),
    ]
    TYPE_CHOICES = [
        ("GENERAL", "普通处方"),
        ("DECOCTION", "汤剂处方"),
        ("GRANULE", "颗粒剂处方"),
    ]

    presc_no = models.CharField("处方号", max_length=32, unique=True)
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="prescriptions", verbose_name="患者"
    )
    doctor = models.ForeignKey(
        "users.Doctor", on_delete=models.CASCADE, related_name="prescriptions", verbose_name="医师"
    )
    diagnosis = models.CharField("诊断", max_length=200, blank=True)
    syndrome = models.CharField("辨证结论", max_length=200, blank=True)
    presc_type = models.CharField("处方类型", max_length=16, choices=TYPE_CHOICES, default="GENERAL")
    status = models.CharField("状态", max_length=16, choices=STATUS_CHOICES, default="DRAFT", db_index=True)
    version = models.IntegerField("版本号（乐观锁）", default=1)
    is_deleted = models.BooleanField("逻辑删除", default=False)
    created_at = models.DateTimeField("创建时间", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "处方"
        verbose_name_plural = "处方"
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["doctor_id", "created_at"]),
            models.Index(fields=["patient_id", "created_at"]),
        ]

    def __str__(self):
        return self.presc_no

    @staticmethod
    def generate_presc_no():
        """按日期+流水生成处方号。"""
        now = timezone.now()
        prefix = now.strftime("%Y%m%d")
        last = (
            Prescription.objects.filter(presc_no__startswith=prefix)
            .order_by("-presc_no")
            .first()
        )
        seq = 1
        if last:
            try:
                seq = int(last.presc_no[-4:]) + 1
            except (ValueError, IndexError):
                seq = 1
        return f"P{prefix}{seq:04d}"


class PrescriptionItem(models.Model):
    """处方明细（药味）。"""

    prescription = models.ForeignKey(
        Prescription, on_delete=models.CASCADE, related_name="items", verbose_name="处方"
    )
    herb = models.ForeignKey(Herb, on_delete=models.CASCADE, verbose_name="药材")
    dose = models.DecimalField("剂量(g)", max_digits=8, decimal_places=2)
    unit = models.CharField("单位", max_length=8, default="g")
    decoction = models.CharField("煎服法", max_length=100, blank=True)
    usage = models.CharField("用法用量", max_length=100, blank=True)

    class Meta:
        verbose_name = "处方明细"
        verbose_name_plural = "处方明细"
        # 联合唯一索引：同一处方不能重复录入同一药材
        unique_together = ("prescription", "herb")

    def __str__(self):
        return f"{self.prescription.presc_no} - {self.herb.name}"
