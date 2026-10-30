"""初始化系统基础数据。

用法：python manage.py init_data

创建内容：
1. 四类角色（医师、药师、管理员、患者）
2. 权限点与角色权限分配
3. 审核规则库初始清单（十八反、十九畏、妊娠禁忌、毒性剂量上限、用法用量、特殊人群）
4. 药材字典与方剂模板
5. 演示账号与模拟数据（可选）
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.users.models import User, Role, Permission, RolePermission, UserRole, Doctor, Pharmacist
from apps.prescriptions.models import Herb, FormulaTemplate, FormulaItem, AuditRule


# 权限编码清单（表3-8 权限矩阵依据）
PERMISSIONS = [
    ("患者:读", "患者读取", "action"),
    ("患者:新增", "患者建档", "action"),
    ("处方:新增", "新建处方", "action"),
    ("处方:修改", "修改处方", "action"),
    ("处方:提交", "提交处方", "action"),
    ("审核:读", "查看审核", "action"),
    ("审核:领取", "领取审核任务", "action"),
    ("审核:转交", "转交审核任务", "action"),
    ("审核:通过", "审核通过", "action"),
    ("审核:退回", "审核退回", "action"),
    ("审核:附件", "上传附件", "action"),
    ("统计:读", "查看统计", "action"),
    ("日志:读", "查看日志", "action"),
    ("导出:执行", "导出数据", "action"),
    ("用户:读", "查看用户", "action"),
    ("用户:管理", "用户与权限配置", "action"),
    ("字典:维护", "字典与规则维护", "action"),
]

# 角色权限分配
ROLE_PERMISSIONS = {
    "doctor": ["患者:读", "患者:新增", "处方:新增", "处方:修改", "处方:提交", "统计:读"],
    "pharmacist": ["审核:读", "审核:领取", "审核:转交", "审核:通过", "审核:退回", "审核:附件", "统计:读"],
    "admin": [
        "用户:读", "用户:管理", "患者:读", "处方:新增", "统计:读", "日志:读", "导出:执行", "字典:维护",
        "审核:读",
    ],
    "patient": ["统计:读"],
}

# 审核规则库初始清单（附录A）
AUDIT_RULES = [
    # 十八反（强制拦截）
    ("R-18F-001", "18F", "甘草,甘遂", "block", "十八反：甘草反甘遂，禁止同方", "药典/配伍禁忌"),
    ("R-18F-002", "18F", "甘草,大戟", "block", "十八反：甘草反大戟，禁止同方", "药典"),
    ("R-18F-003", "18F", "乌头,半夏", "block", "十八反：乌头反半夏，禁止同方", "药典"),
    ("R-18F-004", "18F", "乌头,瓜蒌", "block", "十八反：乌头反瓜蒌，禁止同方", "药典"),
    ("R-18F-005", "18F", "乌头,贝母", "block", "十八反：乌头反贝母，禁止同方", "药典"),
    ("R-18F-006", "18F", "藜芦,人参", "block", "十八反：藜芦反人参，禁止同方", "药典"),
    # 十九畏（预警）
    ("R-19W-001", "19W", "硫黄,朴硝", "warn", "十九畏：硫黄畏朴硝，请核对", "药典"),
    ("R-19W-002", "19W", "水银,砒霜", "warn", "十九畏：水银畏砒霜，请核对", "药典"),
    ("R-19W-003", "19W", "人参,五灵脂", "warn", "十九畏：人参畏五灵脂，请核对", "药典"),
    ("R-19W-004", "19W", "丁香,郁金", "warn", "十九畏：丁香畏郁金，请核对", "药典"),
    # 妊娠禁忌
    ("R-PR-001", "PR", "麝香", "block", "妊娠禁忌：麝香禁用", "药典"),
    ("R-PR-002", "PR", "三棱,莪术", "warn", "妊娠慎用破血药", "药典"),
    ("R-PR-003", "PR", "桃仁", "warn", "妊娠慎用：桃仁", "药典"),
    ("R-PR-004", "PR", "红花", "warn", "妊娠慎用：红花", "药典"),
    # 毒性剂量上限
    ("R-TX-001", "TX", "附子", "block", "附子超剂量上限", "药典"),
    ("R-TX-002", "TX", "细辛", "warn", "细辛用量请复核", "药典"),
    ("R-TX-003", "TX", "制川乌", "block", "制川乌超剂量上限", "药典"),
    ("R-TX-004", "TX", "制草乌", "block", "制草乌超剂量上限", "药典"),
    # 用法用量规范
    ("R-YY-001", "YY", "", "warn", "特殊煎法未标注（先煎/后下）", "规范"),
    # 特殊人群
    ("R-SP-001", "SP", "", "warn", "特殊人群剂量需折算确认", "规范"),
]

# 药材字典（含毒性药材剂量上限）
HERBS = [
    ("甘草", "gancao", "补气药", "甘平", 10, False),
    ("甘遂", "gansui", "泻下药", "苦寒有毒", 3, True),
    ("大戟", "daji", "泻下药", "苦寒有毒", 3, True),
    ("半夏", "banxia", "化痰药", "辛温有毒", 9, True),
    ("乌头", "wutou", "温里药", "辛热有毒", 3, True),
    ("人参", "renshen", "补气药", "甘温", 9, False),
    ("藜芦", "lilu", "涌吐药", "辛苦寒有毒", 3, True),
    ("瓜蒌", "gualou", "化痰药", "甘寒", 12, False),
    ("贝母", "beimu", "化痰药", "苦寒", 9, False),
    ("硫黄", "liuhuang", "攻毒药", "酸温有毒", 3, True),
    ("朴硝", "puxiao", "泻下药", "咸寒", 10, False),
    ("五灵脂", "wulingzhi", "活血药", "苦甘温", 6, False),
    ("丁香", "dingxiang", "温里药", "辛温", 3, False),
    ("郁金", "yujin", "活血药", "辛苦寒", 9, False),
    ("麝香", "shexiang", "开窍药", "辛温", 0.15, True),
    ("三棱", "sanleng", "活血药", "苦辛平", 9, False),
    ("莪术", "ezhu", "活血药", "辛苦温", 9, False),
    ("桃仁", "taoren", "活血药", "苦平", 9, False),
    ("红花", "honghua", "活血药", "辛温", 6, False),
    ("附子", "fuzi", "温里药", "辛甘热有毒", 9, True),
    ("细辛", "xixin", "解表药", "辛温", 3, True),
    ("制川乌", "zhichuanwu", "祛风湿药", "辛苦热有毒", 3, True),
    ("制草乌", "zhicaowu", "祛风湿药", "辛苦热有毒", 3, True),
    ("黄芪", "huangqi", "补气药", "甘温", 15, False),
    ("当归", "danggui", "补血药", "甘辛温", 12, False),
    ("白术", "baizhu", "补气药", "苦甘温", 12, False),
    ("茯苓", "fuling", "利水药", "甘淡平", 15, False),
    ("陈皮", "chenpi", "理气药", "辛苦温", 9, False),
    ("白芍", "baishao", "补血药", "苦酸微寒", 12, False),
    ("川芎", "chuanxiong", "活血药", "辛温", 9, False),
]

# 方剂模板
FORMULAS = [
    {
        "name": "四君子汤",
        "category": "补气剂",
        "indication": "脾胃气虚证",
        "items": [("人参", 9), ("白术", 9), ("茯苓", 9), ("甘草", 6)],
    },
    {
        "name": "四物汤",
        "category": "补血剂",
        "indication": "营血虚滞证",
        "items": [("当归", 9), ("川芎", 9), ("白芍", 9), ("熟地黄", 12)],
    },
    {
        "name": "二陈汤",
        "category": "祛痰剂",
        "indication": "湿痰证",
        "items": [("半夏", 9), ("陈皮", 9), ("茯苓", 9), ("甘草", 6)],
    },
    {
        "name": "补中益气汤",
        "category": "补气剂",
        "indication": "脾胃气虚、中气下陷",
        "items": [("黄芪", 15), ("人参", 9), ("白术", 9), ("当归", 9), ("陈皮", 6), ("甘草", 6)],
    },
]


class Command(BaseCommand):
    help = "初始化系统基础数据（角色、权限、规则库、字典、方剂模板、演示账号）"

    def handle(self, *args, **options):
        with transaction.atomic():
            self.create_roles_and_permissions()
            self.create_audit_rules()
            self.create_herbs_and_formulas()
            self.create_demo_accounts()
        self.stdout.write(self.style.SUCCESS("初始化完成！"))

    def create_roles_and_permissions(self):
        # 角色
        roles = {
            "doctor": Role.objects.get_or_create(code="doctor", defaults={"name": "医师", "description": "接诊开方"})[0],
            "pharmacist": Role.objects.get_or_create(code="pharmacist", defaults={"name": "药师", "description": "处方审核"})[0],
            "admin": Role.objects.get_or_create(code="admin", defaults={"name": "系统管理员", "description": "系统维护"})[0],
            "patient": Role.objects.get_or_create(code="patient", defaults={"name": "患者", "description": "查询本人处方"})[0],
        }

        # 权限
        perm_objs = {}
        for code, name, level in PERMISSIONS:
            perm_objs[code] = Permission.objects.get_or_create(
                code=code, defaults={"name": name, "level": level}
            )[0]

        # 角色权限分配
        for role_code, perm_codes in ROLE_PERMISSIONS.items():
            role = roles[role_code]
            for pc in perm_codes:
                RolePermission.objects.get_or_create(role=role, permission=perm_objs[pc])

        self.stdout.write(self.style.SUCCESS("角色与权限创建完成"))

    def create_audit_rules(self):
        for rule_no, rule_type, herbs, level, message, basis in AUDIT_RULES:
            AuditRule.objects.get_or_create(
                rule_no=rule_no,
                defaults={
                    "rule_type": rule_type,
                    "herbs": herbs,
                    "level": level,
                    "message": message,
                    "basis": basis,
                    "version": "V1.0",
                },
            )
        self.stdout.write(self.style.SUCCESS(f"审核规则库创建完成（{len(AUDIT_RULES)} 条）"))

    def create_herbs_and_formulas(self):
        for name, pinyin, category, prop, max_dose, is_toxic in HERBS:
            Herb.objects.get_or_create(
                name=name,
                defaults={
                    "pinyin": pinyin,
                    "category": category,
                    "property": prop,
                    "max_dose": max_dose,
                    "is_toxic": is_toxic,
                    "default_dose": max_dose,
                },
            )
        # 补充熟地黄
        Herb.objects.get_or_create(
            name="熟地黄", defaults={"pinyin": "shudihuang", "category": "补血药", "property": "甘微温", "max_dose": 15, "default_dose": 12}
        )

        for f in FORMULAS:
            formula, _ = FormulaTemplate.objects.get_or_create(
                name=f["name"],
                defaults={"category": f["category"], "indication": f["indication"]},
            )
            for herb_name, dose in f["items"]:
                herb = Herb.objects.get(name=herb_name)
                FormulaItem.objects.get_or_create(formula=formula, herb=herb, defaults={"dose": dose})

        self.stdout.write(self.style.SUCCESS(f"药材字典（{len(HERBS)+1} 味）与方剂模板（{len(FORMULAS)} 个）创建完成"))

    def create_demo_accounts(self):
        """创建演示账号（仅用于课程实训，模拟数据）。"""
        accounts = [
            # (username, password, name, role_code, is_doctor, is_pharmacist)
            ("admin", "Admin@123", "系统管理员", "admin", False, False),
            ("doctor1", "Doctor@123", "陈志明", "doctor", True, False),
            ("doctor2", "Doctor@123", "王玉晨", "doctor", True, False),
            ("pharmacist1", "Pharm@123", "雷婧怡", "pharmacist", False, True),
            ("patient1", "Patient@123", "张三", "patient", False, False),
        ]

        for username, password, name, role_code, is_doctor, is_pharmacist in accounts:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={"first_name": name, "last_name": "", "is_staff": (role_code == "admin")},
            )
            if created:
                user.set_password(password)
                user.save()
            role = Role.objects.get(code=role_code)
            UserRole.objects.get_or_create(user=user, role=role)

            if is_doctor:
                Doctor.objects.get_or_create(
                    user=user,
                    defaults={"license_no": f"ZY{user.id:06d}", "department": "中医科", "title": "主治医师"},
                )
            if is_pharmacist:
                Pharmacist.objects.get_or_create(
                    user=user, defaults={"license_no": f"YS{user.id:06d}"}
                )

        self.stdout.write(self.style.SUCCESS("演示账号创建完成"))
        self.stdout.write(self.style.WARNING("演示账号：admin/Admin@123, doctor1/Doctor@123, pharmacist1/Pharm@123"))
