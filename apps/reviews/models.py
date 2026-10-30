"""审核记录模型，对应数据存储 D5（审核记录库）。"""
from django.db import models


class ReviewRecord(models.Model):
    """审核记录，关联处方与规则，全流程留痕。"""

    prescription = models.ForeignKey(
        "prescriptions.Prescription",
        on_delete=models.CASCADE,
        related_name="review_records",
        verbose_name="处方",
    )
    precheck_result = models.TextField("预审结论与命中规则", blank=True)
    review_opinion = models.TextField("复核意见", blank=True)
    pharmacist = models.ForeignKey(
        "users.Pharmacist",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="review_records",
        verbose_name="审核药师",
    )
    alert_note = models.TextField("异常备注", blank=True)
    attachment = models.FileField("附件", upload_to="review_attachments/", blank=True, null=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "审核记录"
        verbose_name_plural = "审核记录"
        indexes = [
            models.Index(fields=["prescription_id"]),
        ]

    def __str__(self):
        return f"{self.prescription.presc_no} 审核记录"
