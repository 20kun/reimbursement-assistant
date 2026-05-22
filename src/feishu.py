"""Feishu (Lark) bot integration — push notifications and interactive messages."""

import hashlib
import hmac
import json
import os
import time
from datetime import date

import requests


class FeishuBot:
    """Send reimbursement notifications via Feishu webhook."""

    def __init__(self, webhook_url: str | None = None, secret: str | None = None):
        self.webhook_url = webhook_url or os.getenv("FEISHU_WEBHOOK_URL", "")
        self.secret = secret or os.getenv("FEISHU_WEBHOOK_SECRET", "")

    def _sign(self) -> tuple[str, str]:
        """Generate Feishu signature for webhook verification."""
        timestamp = str(int(time.time()))
        if not self.secret:
            return timestamp, ""
        sign_str = f"{timestamp}\n{self.secret}"
        hmac_code = hmac.new(
            self.secret.encode("utf-8"),
            sign_str.encode("utf-8"),
            digestmod=hashlib.sha256,
        )
        sign = hmac_code.digest().decode("utf-8", errors="replace")
        # base64 encode
        import base64
        sign_b64 = base64.b64encode(hmac_code.digest()).decode("utf-8")
        return timestamp, sign_b64

    def send_approval_notification(
        self,
        applicant: str,
        total_amount: float,
        invoice_count: int,
        compliance_status: str,
        form_url: str = "",
    ) -> bool:
        """Send reimbursement approval request to manager via Feishu."""
        if not self.webhook_url:
            return False

        status_emoji = {"pass": "🟢", "violation": "🔴", "needs_review": "🟡"}
        emoji = status_emoji.get(compliance_status, "📋")
        status_text = {"pass": "合规通过", "violation": "需关注", "needs_review": "待补充"}

        timestamp, sign = self._sign()

        card = {
            "timestamp": timestamp,
            "sign": sign,
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": f"{emoji} 报销审批通知"},
                    "template": "blue",
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": (
                                f"**申请人**：{applicant}\n"
                                f"**报销金额**：¥{total_amount:,.2f}\n"
                                f"**发票数量**：{invoice_count} 张\n"
                                f"**AI审核结果**：{status_text.get(compliance_status, compliance_status)}\n"
                                f"**提交时间**：{date.today().isoformat()}"
                            ),
                        },
                    },
                    {
                        "tag": "note",
                        "elements": [
                            {
                                "tag": "plain_text",
                                "content": "🤖 本通知由智能报销助手自动生成 | AI已预审",
                            }
                        ],
                    },
                ],
            },
        }

        if form_url:
            card["card"]["elements"].insert(1, {
                "tag": "action",
                "actions": [{
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "查看报销单"},
                    "type": "primary",
                    "url": form_url,
                }],
            })

        try:
            resp = requests.post(self.webhook_url, json=card, timeout=10)
            return resp.status_code == 200 and resp.json().get("code") == 0
        except requests.RequestException:
            return False

    def send_simple_message(self, title: str, content: str) -> bool:
        """Send a simple text card to Feishu group."""
        if not self.webhook_url:
            return False

        timestamp, sign = self._sign()

        payload = {
            "timestamp": timestamp,
            "sign": sign,
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": "blue",
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {"tag": "lark_md", "content": content},
                    }
                ],
            },
        }

        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            return resp.status_code == 200 and resp.json().get("code") == 0
        except requests.RequestException:
            return False
