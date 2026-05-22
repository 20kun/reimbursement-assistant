"""Core AI Agent — OCR extraction + policy compliance + form auto-fill.

Powered by DeepSeek API (OpenAI-compatible)."""

import base64
import json
import os
from datetime import date

from openai import OpenAI

from .policy import check_compliance, POLICY_RULES

EXTRACTION_PROMPT = """你是财务发票识别专家。仔细阅读这张发票图片，提取关键信息。

## 识别指南
- 增值税发票：vendor=销售方名称（非购买方），amount=价税合计小写金额
- 餐饮发票/小票：vendor=餐厅/饭店名称，amount=合计/应收金额
- 交通票：vendor=运输公司/出租车公司，amount=票价/金额
- 住宿发票：vendor=酒店名称，amount=住宿费合计

## 金额识别（重要）
- 优先取「价税合计」「合计金额」「实收金额」「应收金额」中数字
- 去掉¥符号、逗号、空格，只保留数字和小数点
- 大写金额可对照验证，但以小写为准

## 日期识别
- 增值税发票看「开票日期」
- 小票看「日期」「时间」
- 统一转YYYY-MM-DD格式，年必须是20xx

## 分类判断
- 餐厅/饭店/酒楼/快餐/咖啡/外卖 → 餐饮招待
- 酒店/宾馆/民宿/旅馆 → 差旅住宿
- 机票/高铁/火车/出租车/滴滴/加油/过路费 → 交通费
- 文具/打印/耗材/电脑配件/纸张 → 办公用品
- 培训费/会议费/报名费 → 培训会议
- 快递/物流/运输费 → 快递费
- 电话费/网费/手机充值 → 通讯费
- 无法判断 → 其他

## 城市识别
- 增值税发票：看销售方地址前几个字，或发票监制章
- 餐饮/酒店：看店铺地址或电话区号

返回纯JSON（不要markdown代码块，不要解释文字）：

{"vendor":"开票单位全称","amount":100.00,"date":"2025-06-15","category":"餐饮招待","city":"广州","tax_id":"91440101...","invoice_number":"发票号码","items":"购买物品或服务简述","attendee_count":null,"notes":""}

字段说明：
- vendor: 销售方/收款方全称（必填）
- amount: 数字（必填）
- date: YYYY-MM-DD（必填）
- category: 餐饮招待/差旅住宿/交通费/办公用品/培训会议/通讯费/快递费/其他（必填）
- city: 城市名或null
- tax_id: 税号或null
- invoice_number: 发票号或null
- items: 商品/服务简述或null
- attendee_count: 人数或null
- notes: 备注或null
如果某字段无法识别，填null"""


class ReimbursementAgent:
    """Intelligent reimbursement assistant — OCR + compliance + auto-fill."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY is required. Set in .env file.")
        base_url = base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.extractions: list[dict] = []
        self.total_saved_minutes = 0

    def extract_invoice(self, image_bytes: bytes, mime_type: str = "image/png") -> dict:
        """Extract structured data from invoice image using DeepSeek Vision."""
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        data_url = f"data:{mime_type};base64,{image_b64}"

        response = self.client.chat.completions.create(
            model="deepseek-chat",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url},
                    },
                    {"type": "text", "text": EXTRACTION_PROMPT},
                ],
            }],
        )

        raw = response.choices[0].message.content.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            import re
            match = re.search(r'\{[\s\S]*\}', raw)
            if match:
                data = json.loads(match.group())
            else:
                raise ValueError(f"Failed to parse AI response as JSON:\n{raw}")

        data["_extracted_at"] = date.today().isoformat()
        self.extractions.append(data)
        self.total_saved_minutes += 5
        return data

    def check_compliance(self, extraction: dict) -> dict:
        """Run policy compliance checks on extracted invoice data."""
        category = extraction.get("category", "其他")
        amount = float(extraction.get("amount", 0))
        city = extraction.get("city")
        attendee_count = extraction.get("attendee_count")
        has_attendees = attendee_count is not None and attendee_count > 0

        violations = check_compliance(
            category=category,
            amount=amount,
            city=city,
            has_attendees=has_attendees,
            has_pre_approval=False,
            has_detail_list=bool(extraction.get("items")),
        )

        if not violations:
            return {
                "overall_status": "pass",
                "checks": [{
                    "rule": "所有规则",
                    "status": "pass",
                    "detail": "报销申请符合公司政策",
                    "suggestion": None,
                }],
                "summary": "合规，可直接提交",
                "risk_level": "low",
            }

        has_errors = any(v["severity"] == "error" for v in violations)
        overall = "violation" if has_errors else "needs_review"
        risk = "high" if len([v for v in violations if v["severity"] == "error"]) > 1 else "medium" if has_errors else "low"

        checks = []
        for v in violations:
            checks.append({
                "rule": v["rule"],
                "status": "fail" if v["severity"] == "error" else "warning",
                "detail": v["message"],
                "suggestion": v["fix"],
            })

        return {
            "overall_status": overall,
            "checks": checks,
            "summary": f"发现{len(violations)}项问题（{len([v for v in violations if v['severity']=='error'])}项错误，{len([v for v in violations if v['severity']=='warning'])}项提醒）",
            "risk_level": risk,
        }

    def auto_fill_form(self, extractions: list[dict]) -> dict:
        """Generate complete reimbursement form data from extractions."""
        total = sum(float(e.get("amount", 0)) for e in extractions)

        items = []
        for i, e in enumerate(extractions):
            items.append({
                "序号": i + 1,
                "日期": e.get("date", ""),
                "类别": e.get("category", "其他"),
                "金额": float(e.get("amount", 0)),
                "开票单位": e.get("vendor", ""),
                "发票号": e.get("invoice_number", ""),
                "事由/物品": e.get("items", ""),
                "城市": e.get("city") or "",
            })

        return {
            "申请人": "",
            "部门": "",
            "报销日期": date.today().isoformat(),
            "报销事由": "",
            "明细": items,
            "合计金额": total,
            "附件数量": len(extractions),
        }

    def get_stats(self) -> dict:
        """Return usage statistics for ROI quantification."""
        return {
            "invoices_processed": len(self.extractions),
            "total_saved_minutes": self.total_saved_minutes,
            "total_saved_hours": round(self.total_saved_minutes / 60, 1),
        }
