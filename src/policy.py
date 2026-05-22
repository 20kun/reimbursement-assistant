"""Reimbursement policy rules engine — configurable per-company policy."""

from dataclasses import dataclass
from typing import Optional

TIER1_CITIES = ["北京", "上海", "广州", "深圳"]
TIER2_CITIES = ["杭州", "成都", "武汉", "南京", "重庆", "苏州", "西安", "长沙"]


@dataclass
class PolicyRule:
    category: str
    max_amount: float
    per_person: bool = False
    requires_attendees: bool = False
    requires_pre_approval: bool = False
    requires_detail_list: bool = False
    requires_receipt: bool = True
    notes: str = ""


POLICY_RULES: dict[str, PolicyRule] = {
    "餐饮招待": PolicyRule(
        category="餐饮招待",
        max_amount=150,
        per_person=True,
        requires_attendees=True,
        notes="人均不超过150元，须注明招待对象、人数及我司陪同人员",
    ),
    "差旅住宿-一线": PolicyRule(
        category="差旅住宿",
        max_amount=500,
        notes="一线城市（北上广深）≤500元/晚，须附住宿水单",
    ),
    "差旅住宿-其他": PolicyRule(
        category="差旅住宿",
        max_amount=350,
        notes="非一线城市≤350元/晚，须附住宿水单",
    ),
    "交通-出租车": PolicyRule(
        category="交通费",
        max_amount=200,
        notes="单次≤200元，须注明起止地点及事由",
    ),
    "交通-高铁": PolicyRule(
        category="交通费",
        max_amount=800,
        notes="二等座，须附车票",
    ),
    "交通-机票": PolicyRule(
        category="交通费",
        max_amount=2000,
        requires_pre_approval=True,
        notes="经济舱，须事前审批+附行程单",
    ),
    "办公用品": PolicyRule(
        category="办公用品",
        max_amount=500,
        requires_detail_list=True,
        notes="单件≤500元，须列明物品清单及用途",
    ),
    "培训会议": PolicyRule(
        category="培训会议",
        max_amount=3000,
        requires_pre_approval=True,
        notes="须提供事前审批单，注册费≤3000元",
    ),
    "通讯费": PolicyRule(
        category="通讯费",
        max_amount=200,
        notes="月报销上限200元，超出部分自理",
    ),
    "市内交通": PolicyRule(
        category="交通费",
        max_amount=50,
        notes="地铁/公交实报实销，单次≤50元",
    ),
    "快递费": PolicyRule(
        category="办公用品",
        max_amount=100,
        notes="单次≤100元，须附快递单据",
    ),
    "其他": PolicyRule(
        category="其他",
        max_amount=500,
        requires_pre_approval=True,
        notes="须主管事前审批",
    ),
}


def get_policy_for_category(category: str, city: str | None = None) -> PolicyRule:
    """Resolve applicable policy rule given category and optional city."""
    if category == "差旅住宿":
        key = "差旅住宿-一线" if city in TIER1_CITIES else "差旅住宿-其他"
        return POLICY_RULES[key]
    return POLICY_RULES.get(category, POLICY_RULES["其他"])


def check_compliance(
    category: str,
    amount: float,
    city: str | None = None,
    has_attendees: bool = False,
    has_pre_approval: bool = False,
    has_detail_list: bool = False,
) -> list[dict]:
    """
    Run all applicable policy checks. Returns list of violations.
    Each violation: {"rule": str, "severity": "error"|"warning", "message": str, "fix": str}
    """
    rule = get_policy_for_category(category, city)
    violations = []

    effective_max = rule.max_amount
    if rule.per_person and has_attendees:
        effective_max = rule.max_amount * 2  # assume at least 2 attendees

    if amount > effective_max:
        violations.append({
            "rule": f"{category}金额上限",
            "severity": "error",
            "message": f"报销金额 ¥{amount:.2f} 超出限额 ¥{effective_max:.2f}",
            "fix": f"超出部分 ¥{amount - effective_max:.2f} 须主管特批，或拆分为合规金额",
        })

    if rule.requires_attendees and not has_attendees:
        violations.append({
            "rule": "招待对象信息缺失",
            "severity": "warning",
            "message": f"{category} 须注明招待对象及人数",
            "fix": "请补充招待对象姓名、人数及我司陪同人员",
        })

    if rule.requires_pre_approval and not has_pre_approval:
        violations.append({
            "rule": "事前审批缺失",
            "severity": "error",
            "message": f"{category} 须事前审批",
            "fix": "请提供事前审批单编号或截图附件",
        })

    if rule.requires_detail_list and not has_detail_list:
        violations.append({
            "rule": "物品清单缺失",
            "severity": "warning",
            "message": f"{category} 须附物品明细清单",
            "fix": "请补充采购物品名称、数量、单价、用途",
        })

    return violations
