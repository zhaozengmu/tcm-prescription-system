"""操作日志与统计模型，对应数据存储 D6（日志与统计库）。"""
from django.db import models


class OperationLog(models.Model):
    """操作日志，全量留痕，覆盖关键动作。"""

    operator = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="operation_logs", verbose_name="操作人"
    )
    action_type = models.CharField("行为类型", max_length=32, db_index=True)
    object_type = models.CharField("对象类型", max_length=32)
    object_id = models.CharField("对象标识", max_length=64)
    detail = models.TextField("详情", blank=True)
    ip = models.CharField("来源IP", max_length=64, blank=True)
    result = models.CharField("结果", max_length=16, default="success")
    created_at = models.DateTimeField("时间", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "操作日志"
        verbose_name_plural = "操作日志"
        indexes = [
            models.Index(fields=["operator_id", "created_at"]),
            models.Index(fields=["object_type", "created_at"]),
        ]

    def __str__(self):
        return f"{self.action_type} {self.object_type}#{self.object_id}"


class StatDaily(models.Model):
    """每日统计指标预计算表。

    按统计口径（仅统计已通过并归档的处方）预计算常用指标，
    看板直接读取汇总结果，满足 3 秒内响应要求。
    """

    stat_date = models.DateField("统计日期", db_index=True)
    dimension = models.CharField("维度", max_length=32, default="total")  # total/doctor/herb
    dimension_key = models.CharField("维度键", max_length=64, default="")  # 医师ID或药材名
    prescription_count = models.IntegerField("处方量", default=0)
    item_count = models.IntegerField("药味总数", default=0)
    created_at = models.DateTimeField("生成时间", auto_now=True)

    class Meta:
        verbose_name = "统计指标"
        verbose_name_plural = "统计指标"
        unique_together = ("stat_date", "dimension", "dimension_key")

    def __str__(self):
        return f"{self.stat_date} {self.dimension}:{self.dimension_key}"
