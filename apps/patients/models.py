"""患者档案模型，对应数据存储 D2（患者档案库）。

敏感字段（身份证号、联系电话）加密存储 + 哈希列等值查询，
列表页掩码展示，详情页按权限解密。
"""
import hashlib

from django.db import models
from django.conf import settings


def _hash_id(value):
    """对身份证号做哈希，用于等值查询。"""
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class Patient(models.Model):
    """患者档案。"""

    GENDER_CHOICES = [("M", "男"), ("F", "女"), ("U", "未知")]
    PREGNANCY_CHOICES = [
        ("NONE", "无"),
        ("PREGNANT", "孕期"),
        ("POSTPARTUM", "产后"),
    ]

    patient_no = models.CharField("患者编号", max_length=32, unique=True)
    name = models.CharField("姓名", max_length=64)
    gender = models.CharField("性别", max_length=2, choices=GENDER_CHOICES, default="U")
    age = models.IntegerField("年龄", null=True, blank=True)
    # 敏感字段：身份证号与联系电话（加密存储）
    id_card_encrypted = models.TextField("身份证号密文", blank=True)
    id_card_hash = models.CharField("身份证号哈希", max_length=64, blank=True, db_index=True)
    phone_encrypted = models.TextField("联系电话密文", blank=True)
    phone_hash = models.CharField("联系电话哈希", max_length=64, blank=True, db_index=True)
    allergy_history = models.TextField("过敏史", blank=True)
    pregnancy_status = models.CharField("孕产状态", max_length=16, choices=PREGNANCY_CHOICES, default="NONE")
    visit_summary = models.TextField("既往就诊摘要", blank=True)
    is_deleted = models.BooleanField("逻辑删除", default=False)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)
    last_visit_at = models.DateTimeField("最近就诊时间", null=True, blank=True)

    class Meta:
        verbose_name = "患者档案"
        verbose_name_plural = "患者档案"
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["gender", "age"]),
        ]

    def __str__(self):
        return f"{self.name}({self.patient_no})"

    @staticmethod
    def generate_patient_no():
        """按规则自动生成患者编号。"""
        from django.utils import timezone
        now = timezone.now()
        prefix = now.strftime("%Y%m%d")
        last = (
            Patient.objects.filter(patient_no__startswith=prefix)
            .order_by("-patient_no")
            .first()
        )
        seq = 1
        if last:
            try:
                seq = int(last.patient_no[-4:]) + 1
            except (ValueError, IndexError):
                seq = 1
        return f"{prefix}{seq:04d}"
