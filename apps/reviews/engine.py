"""处方审核规则引擎（P4 加工的核心）。

规则从 AuditRule 表加载（带缓存与版本），执行自动预审：
- 十八反类命中 -> 强制拦截（block）
- 十九畏类命中 -> 预警提示（warn）
- 妊娠禁忌 -> 结合患者孕产状态强制拦截或分级警示
- 毒性剂量上限 -> 超限强制拦截
- 用法用量规范 -> 缺项提醒
- 特殊人群 -> 提示

返回预审结果：命中规则列表 + 是否强制拦截。
"""
from collections import defaultdict

from django.core.cache import cache
from django.db.models import Q


def _load_rules():
    """加载当前启用的审核规则（带缓存）。"""
    cache_key = "audit_rules_active"
    rules = cache.get(cache_key)
    if rules is None:
        from apps.prescriptions.models import AuditRule
        rules = list(AuditRule.objects.filter(is_active=True).values(
            "id", "rule_no", "rule_type", "herbs", "level", "scope", "message", "version", "basis"
        ))
        cache.set(cache_key, rules, timeout=300)
    return rules


def invalidate_rules_cache():
    """规则变更后主动失效缓存。"""
    cache.delete("audit_rules_active")


def precheck_prescription(prescription):
    """对处方执行自动预审。

    返回 dict：
    {
        "blocked": bool,   # 是否命中强制拦截规则
        "hits": [ {rule_no, rule_type, level, message, herbs}, ... ],
        "result_text": str,  # 预审结论文本
    }
    """
    # 收集处方中的药材集合
    items = prescription.items.select_related("herb").all()
    herb_names = set(item.herb.name for item in items)
    herb_dose = {item.herb.name: float(item.dose) for item in items}

    patient = prescription.patient
    pregnancy = patient.pregnancy_status if patient else "NONE"

    # 按处方类型过滤规则适用范围：门诊处方用 ALL+OUTPATIENT，住院处方用 ALL+INPATIENT
    presc_scope = "INPATIENT" if prescription.presc_type == "INPATIENT" else "OUTPATIENT"
    rules = [r for r in _load_rules() if r.get("scope", "ALL") in ("ALL", presc_scope)]

    hits = []
    blocked = False

    for rule in rules:
        rule_type = rule["rule_type"]
        rule_herbs = [h.strip() for h in rule["herbs"].split(",") if h.strip()]

        if rule_type == "18F":  # 十八反：药材组合命中即强制拦截
            if all(h in herb_names for h in rule_herbs) and len(rule_herbs) >= 2:
                hits.append(_format_hit(rule))
                blocked = True

        elif rule_type == "19W":  # 十九畏：组合命中预警
            if all(h in herb_names for h in rule_herbs) and len(rule_herbs) >= 2:
                hits.append(_format_hit(rule))

        elif rule_type == "PR":  # 妊娠禁忌
            if pregnancy in ("PREGNANT", "POSTPARTUM"):
                if any(h in herb_names for h in rule_herbs):
                    hits.append(_format_hit(rule))
                    if rule["level"] == "block":
                        blocked = True

        elif rule_type == "TX":  # 毒性剂量上限
            for h in rule_herbs:
                if h in herb_names:
                    herb = _get_herb(h)
                    max_dose = float(herb.max_dose) if herb and herb.max_dose else None
                    if max_dose and herb_dose.get(h, 0) > max_dose:
                        hits.append(_format_hit(rule, extra=f"（{h} 剂量 {herb_dose[h]}g 超上限 {max_dose}g）"))
                        if rule["level"] == "block":
                            blocked = True

        elif rule_type == "YY":  # 用法用量规范
            # 检查是否有未标注煎服法的药材
            missing = [item.herb.name for item in items if not item.decoction]
            if missing:
                hits.append(_format_hit(rule, extra=f"（未标注煎服法：{','.join(missing[:5])}）"))

        elif rule_type == "SP":  # 特殊人群
            if patient and patient.age is not None:
                if patient.age < 18 or patient.age > 65:
                    hits.append(_format_hit(rule, extra=f"（{patient.age}岁）"))

    result_text = _build_result_text(hits)
    return {"blocked": blocked, "hits": hits, "result_text": result_text}


def _format_hit(rule, extra=""):
    return {
        "rule_no": rule["rule_no"],
        "rule_type": rule["rule_type"],
        "level": rule["level"],
        "message": rule["message"] + extra,
        "herbs": rule["herbs"],
        "version": rule["version"],
    }


def _build_result_text(hits):
    if not hits:
        return "预审通过，未命中配伍禁忌或剂量超限规则"
    blocked_hits = [h for h in hits if h["level"] == "block"]
    warn_hits = [h for h in hits if h["level"] == "warn"]
    parts = []
    if blocked_hits:
        parts.append(f"强制拦截 {len(blocked_hits)} 项")
    if warn_hits:
        parts.append(f"预警提示 {len(warn_hits)} 项")
    return "；".join(parts)


def _get_herb(name):
    from apps.prescriptions.models import Herb
    return Herb.objects.filter(name=name).first()
