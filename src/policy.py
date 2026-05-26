"""Reimbursement policy rules engine — configurable per-company policy.

Supports:
  - Per-category amount limits with hard/soft cap modes
  - Tiered city pricing for hotels
  - Required additional fields per category
  - Runtime policy customization
"""

from copy import deepcopy
from dataclasses import dataclass, field

TIER1_CITIES = ["北京", "上海", "广州", "深圳"]


@dataclass
class PolicyRule:
    category: str
    max_amount: float
    per_person: bool = False
    cap_mode: str = "soft"  # "hard"=强制截断, "soft"=仅警告, "none"=不限制
    requires_attendees: bool = False
    requires_pre_approval: bool = False
    requires_detail_list: bool = False
    requires_receipt: bool = True
    extra_fields: dict[str, str] = field(default_factory=dict)
    # extra_fields: {field_key: field_label} — additional info needed for this category
    notes: str = ""


DEFAULT_POLICY: dict[str, PolicyRule] = {
    "餐饮招待": PolicyRule(
        category="餐饮招待",
        max_amount=150,
        per_person=True,
        cap_mode="soft",
        requires_attendees=True,
        extra_fields={
            "guest_count": "对方人数",
            "our_count": "我司参与人数",
            "guest_names": "招待对象（单位/姓名）",
            "purpose": "招待事由",
        },
        notes="人均≤150元，须注明招待对象、双方人数及事由",
    ),
    "差旅住宿": PolicyRule(
        category="差旅住宿",
        max_amount=500,
        cap_mode="hard",
        extra_fields={
            "city": "入住城市",
            "nights": "入住天数",
            "check_in_date": "入住日期",
        },
        notes="一线城市≤500/晚，其他≤350/晚，须附住宿水单",
    ),
    "交通费": PolicyRule(
        category="交通费",
        max_amount=200,
        cap_mode="hard",
        extra_fields={
            "from_location": "出发地",
            "to_location": "目的地",
            "transport_type": "交通方式",
            "trip_purpose": "出行事由",
        },
        notes="出租车≤200/次，高铁二等座≤800，机票经济舱≤2000须事前审批",
    ),
    "办公用品": PolicyRule(
        category="办公用品",
        max_amount=500,
        cap_mode="soft",
        requires_detail_list=True,
        extra_fields={
            "item_list": "物品清单",
            "usage": "用途说明",
        },
        notes="单件≤500元，须列明物品清单及用途",
    ),
    "培训会议": PolicyRule(
        category="培训会议",
        max_amount=3000,
        cap_mode="soft",
        requires_pre_approval=True,
        extra_fields={
            "approval_number": "事前审批编号",
            "training_name": "培训/会议名称",
            "participant_count": "参与人数",
        },
        notes="须提供事前审批单，注册费≤3000元",
    ),
    "通讯费": PolicyRule(
        category="通讯费",
        max_amount=200,
        cap_mode="hard",
        extra_fields={
            "bill_month": "费用所属月份",
            "phone_number": "报销号码",
        },
        notes="月报销上限200元，超出部分自理",
    ),
    "快递费": PolicyRule(
        category="快递费",
        max_amount=100,
        cap_mode="hard",
        extra_fields={
            "tracking_number": "快递单号",
            "send_to": "收件方",
            "purpose": "寄送事由",
        },
        notes="单次≤100元，须附快递单据",
    ),
    "其他": PolicyRule(
        category="其他",
        max_amount=500,
        cap_mode="soft",
        requires_pre_approval=True,
        extra_fields={
            "purpose": "费用说明",
            "approval_number": "事前审批编号",
        },
        notes="须主管事前审批",
    ),
}


def get_default_policy() -> dict[str, PolicyRule]:
    """Return mutable copy of default policy (for customization)."""
    return deepcopy(DEFAULT_POLICY)


def get_policy_for_category(
    category: str,
    city: str | None = None,
    policy: dict[str, PolicyRule] | None = None,
) -> PolicyRule:
    """Resolve applicable policy rule given category and optional city."""
    rules = policy if policy is not None else DEFAULT_POLICY

    if category == "差旅住宿" and city:
        if city in TIER1_CITIES:
            rule = rules.get("差旅住宿", rules["其他"])
            return rule
        else:
            rule = deepcopy(rules.get("差旅住宿", rules["其他"]))
            rule.max_amount = 350
            rule.notes = "非一线城市≤350元/晚，须附住宿水单"
            return rule

    return rules.get(category, rules["其他"])


def check_compliance(
    category: str,
    amount: float,
    city: str | None = None,
    has_attendees: bool = False,
    has_pre_approval: bool = False,
    has_detail_list: bool = False,
    attendee_count: int = 0,
    policy: dict[str, PolicyRule] | None = None,
) -> tuple[list[dict], float]:
    """
    Run all applicable policy checks. Returns (violations, reimbursable_amount).

    reimbursable_amount = min(amount, limit) for hard_cap, = amount for soft_cap.
    Each violation: {"rule": str, "severity": "error"|"warning", "message": str, "fix": str}
    """
    rule = get_policy_for_category(category, city, policy)
    violations = []
    reimbursable = amount

    # Calculate effective limit
    effective_max = rule.max_amount
    if rule.per_person and attendee_count > 0:
        effective_max = rule.max_amount * attendee_count

    # Apply cap mode
    if amount > effective_max:
        if rule.cap_mode == "hard":
            overage = amount - effective_max
            reimbursable = effective_max
            violations.append({
                "rule": f"{category}金额上限（强制截断）",
                "severity": "warning",
                "message": f"实际金额 ¥{amount:.2f} 超出限额 ¥{effective_max:.2f}，超出 ¥{overage:.2f} 不予报销",
                "fix": f"实际可报销金额为 ¥{effective_max:.2f}，超出 ¥{overage:.2f} 须自理",
            })
        elif rule.cap_mode == "soft":
            overage = amount - effective_max
            violations.append({
                "rule": f"{category}金额超出限额",
                "severity": "error",
                "message": f"报销金额 ¥{amount:.2f} 超出限额 ¥{effective_max:.2f}",
                "fix": f"超出部分 ¥{overage:.2f} 须主管特批，或拆分为合规金额",
            })

    if rule.requires_attendees and not has_attendees:
        violations.append({
            "rule": "招待对象信息缺失",
            "severity": "warning",
            "message": f"{category} 须注明招待对象及双方人数",
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

    return violations, reimbursable


def get_extra_fields(category: str, policy: dict[str, PolicyRule] | None = None) -> dict[str, str]:
    """Return required extra fields for a given category."""
    rules = policy if policy is not None else DEFAULT_POLICY
    rule = rules.get(category, rules["其他"])
    return dict(rule.extra_fields)
