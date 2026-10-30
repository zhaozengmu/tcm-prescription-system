"""处方审核状态机。

状态迁移规则（含初审/复审两级审核）：
草稿 -> 提交 -> 待预审
待预审 -> 系统预审 -> 已预审 / 预警拦截
已预审 -> 药师领取 -> 初审中
预警拦截 -> 填写理由放行 -> 初审中
初审中 -> 初审通过 -> 复审中 / 退回 -> 已驳回
复审中 -> 复审通过 -> 已通过 / 退回 -> 已驳回
已驳回 -> 修改后重新提交 -> 待预审（版本号+1）
已通过 -> 发药确认 -> 已发药完结（终态）

非法迁移在接口层直接拒绝。
"""
from apps.prescriptions.models import Prescription

# 允许的状态迁移映射：当前状态 -> 触发事件 -> 目标状态
TRANSITIONS = {
    "DRAFT": {"submit": "SUBMITTED"},
    "SUBMITTED": {"precheck_pass": "PRECHECKED", "precheck_block": "ALERTED"},
    "PRECHECKED": {"claim": "REVIEWING", "reject": "REJECTED"},
    "ALERTED": {"release": "REVIEWING", "reject": "REJECTED"},
    # 初审通过 -> 复审中；初审退回 -> 已驳回
    "REVIEWING": {"approve": "FINAL_REVIEWING", "reject": "REJECTED"},
    # 复审通过 -> 已通过；复审退回 -> 已驳回
    "FINAL_REVIEWING": {"approve": "APPROVED", "reject": "REJECTED"},
    "REJECTED": {"resubmit": "SUBMITTED"},
    "APPROVED": {"dispense": "DISPENSED"},
    "DISPENSED": {},  # 终态
}


def transition(prescription, event, **kwargs):
    """执行状态迁移。

    返回 (success, target_or_error)。
    非法迁移返回 (False, "状态冲突")。
    """
    current = prescription.status
    allowed = TRANSITIONS.get(current, {})
    if event not in allowed:
        return False, f"非法状态迁移：{current} 状态下不允许 {event}"

    target = allowed[event]
    prescription.status = target

    if event == "resubmit":
        prescription.version += 1  # 重新提交版本号加一

    prescription.save(update_fields=["status", "version", "updated_at"])
    return True, target
