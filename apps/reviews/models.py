"""审核记录、发药记录、消息通知模型。

- ReviewRecord：对应 D5 审核记录库，区分初审/复审两级
- DispenseRecord：药房发药记录
- Notification：消息提醒（处方提交/驳回等）
"""
from django.db import models


class ReviewRecord(models.Model):
    """审核记录，关联处方与规则，全流程留痕，区分初审/复审。"""

    LEVEL_CHOICES = [
        ("INITIAL", "初审"),
        ("FINAL", "复审"),
    ]

    prescription = models.ForeignKey(
        "prescriptions.Prescription",
        on_delete=models.CASCADE,
        related_name="review_records",
        verbose_name="处方",
    )
    review_level = models.CharField("审核级别", max_length=16, choices=LEVEL_CHOICES, default="INITIAL")
    precheck_result = models.TextField("预审结论与命中规则", blank=True)
    review_opinion = models.TextField("复核意见", blank=True)
    reject_reason = models.TextField("驳回原因", blank=True)
    pharmacist = models.ForeignKey(
        "users.Pharmacist",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="review_records",
        verbose_name="审核药师",
    )
    alert_note = models.TextField("异常备注", blank=True)
    adverse_note = models.TextField("不良反应备注", blank=True)
    attachment = models.FileField("附件", upload_to="review_attachments/", blank=True, null=True)
    created_at = models.DateTimeField("审核时间", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "审核记录"
        verbose_name_plural = "审核记录"
        indexes = [
            models.Index(fields=["prescription_id"]),
        ]

    def __str__(self):
        return f"{self.prescription.presc_no} {self.get_review_level_display()}"


class DispenseRecord(models.Model):
    """药房发药记录，药房人员核对处方、确认发药并登记发药人。"""

    prescription = models.OneToOneField(
        "prescriptions.Prescription",
        on_delete=models.CASCADE,
        related_name="dispense_record",
        verbose_name="处方",
    )
    dispenser = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dispense_records",
        verbose_name="发药人",
    )
    checked_herbs = models.BooleanField("饮片核对无误", default=False)
    note = models.CharField("发药备注", max_length=200, blank=True)
    created_at = models.DateTimeField("发药时间", auto_now_add=True)

    class Meta:
        verbose_name = "发药记录"
        verbose_name_plural = "发药记录"

    def __str__(self):
        return f"{self.prescription.presc_no} 发药记录"


class Notification(models.Model):
    """消息提醒：处方提交提醒药师、驳回提醒医师等。"""

    LEVEL_CHOICES = [
        ("INFO", "提示"),
        ("WARN", "预警"),
        ("BLOCK", "拦截"),
    ]

    recipient = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="接收人",
    )
    title = models.CharField("标题", max_length=128)
    content = models.CharField("内容", max_length=255, blank=True)
    level = models.CharField("级别", max_length=8, choices=LEVEL_CHOICES, default="INFO")
    is_read = models.BooleanField("已读", default=False)
    created_at = models.DateTimeField("时间", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "消息通知"
        verbose_name_plural = "消息通知"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.recipient.username}: {self.title}"
