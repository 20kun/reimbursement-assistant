"""Smart Reimbursement Assistant — Streamlit web app.

Usage:
    streamlit run app.py
"""

import datetime
import io
import os
import time

import streamlit as st
from dotenv import load_dotenv

from src import ReimbursementAgent, generate_excel, FeishuBot, POLICY_RULES

load_dotenv()

# ── Page config ──────────────────────────────────────────────
st.set_page_config(
    page_title="智能报销助手 | XPeng",
    page_icon="🧾",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Session state init ───────────────────────────────────────
for key, default in {
    "agent": None,
    "extractions": [],
    "compliance_results": [],
    "form_data": None,
    "step": 1,
    "excel_bytes": None,
    "total_saved": 0,
    "agent_error": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


def _get_config(key: str, default: str = "") -> str:
    """Read config from Streamlit secrets (Cloud) or env (.env local)."""
    try:
        return st.secrets.get(key, os.getenv(key, default))
    except Exception:
        return os.getenv(key, default)


def init_agent():
    """Auto-init agent from secrets/env, no user input needed."""
    if st.session_state.agent is not None:
        return
    api_key = _get_config("DASHSCOPE_API_KEY")
    if not api_key:
        st.session_state.agent_error = "未配置 DASHSCOPE_API_KEY，请联系管理员"
        return
    try:
        st.session_state.agent = ReimbursementAgent(
            api_key=api_key,
            base_url=_get_config("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        )
        st.session_state.agent_error = None
    except Exception as e:
        st.session_state.agent_error = f"AI 服务初始化失败：{e}"


# Auto-init on first load
init_agent()

# ── Sidebar ──────────────────────────────────────────────────
with st.sidebar:
    st.title("🧾 智能报销助手")
    st.caption("Powered by Qwen AI · v2.0")

    # Connection status
    if st.session_state.agent is not None:
        st.success("🟢 AI 服务已就绪")
    elif st.session_state.agent_error:
        st.error(f"🔴 {st.session_state.agent_error}")

    st.divider()

    # Feishu config (optional, collapsed by default)
    with st.expander("📨 飞书推送（可选）"):
        feishu_url = st.text_input(
            "飞书 Webhook URL",
            type="password",
            value=_get_config("FEISHU_WEBHOOK_URL"),
            placeholder="https://open.feishu.cn/...",
        )
        feishu_secret = st.text_input(
            "Webhook 签名密钥",
            type="password",
            value=_get_config("FEISHU_WEBHOOK_SECRET"),
        )

    st.divider()

    # Policy quick reference
    with st.expander("📋 报销政策速查"):
        for name, rule in POLICY_RULES.items():
            if any(k in name for k in ["一线", "其他-", "高铁", "出租车", "机票", "市内"]):
                continue
            st.markdown(f"**{rule.category}** ≤¥{rule.max_amount:.0f}"
                        f"{'/人' if rule.per_person else ''}")
            st.caption(rule.notes)

    st.divider()

    # Stats
    if st.session_state.total_saved > 0:
        st.metric("⏱️ 累计节省时间", f"{st.session_state.total_saved} 分钟")
        st.metric("📄 已处理发票", len(st.session_state.extractions))


# ── Main content ─────────────────────────────────────────────
st.title("🧾 智能报销助手")
st.markdown("> 上传发票 → AI识别 → 合规检查 → 一键生成报销单 → 飞书推送审批")

# Progress bar
step_names = ["1. 上传发票", "2. AI识别提取", "3. 合规审核", "4. 生成报销单"]
progress = st.session_state.step / len(step_names)
st.progress(progress, text=f"步骤 {st.session_state.step}/{len(step_names)}: {step_names[st.session_state.step - 1]}")

st.divider()

# ── STEP 1 & 2: Upload & Extract ─────────────────────────────

col_upload, col_result = st.columns([1, 1])

with col_upload:
    st.subheader("📤 上传发票/收据")
    uploaded_files = st.file_uploader(
        "支持图片（JPG/PNG）和 PDF，可多张批量上传",
        type=["jpg", "jpeg", "png", "pdf", "webp"],
        accept_multiple_files=True,
        help="拍照上传或拖拽发票图片，AI自动识别提取",
    )

    if uploaded_files:
        st.caption(f"已选择 {len(uploaded_files)} 个文件")

        agent_ready = st.session_state.agent is not None

        if st.button("🔍 AI 识别提取", type="primary", use_container_width=True,
                     disabled=not agent_ready):
            agent = st.session_state.agent
            st.session_state.extractions = []
            st.session_state.compliance_results = []
            progress_bar = st.progress(0)
            status_text = st.empty()

            for i, file in enumerate(uploaded_files):
                status_text.text(f"正在识别：{file.name} ...")
                img_bytes = file.read()

                mime_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                            "png": "image/png", "webp": "image/webp"}
                ext = file.name.rsplit(".", 1)[-1].lower()
                mime = mime_map.get(ext, "image/png")

                try:
                    extraction = agent.extract_invoice(img_bytes, mime)
                    compliance = agent.check_compliance(extraction)
                    extraction["_filename"] = file.name
                    extraction["_compliance"] = compliance
                    st.session_state.extractions.append(extraction)
                    st.session_state.compliance_results.append(compliance)
                except Exception as e:
                    st.error(f"识别 {file.name} 失败：{e}")

                progress_bar.progress((i + 1) / len(uploaded_files))

            st.session_state.total_saved += len(uploaded_files) * 5
            st.session_state.step = max(st.session_state.step, 2)
            status_text.text(f"✅ 完成！识别 {len(uploaded_files)} 张发票，节省约 {len(uploaded_files) * 5} 分钟")
            time.sleep(1)
            st.rerun()

        if not agent_ready:
            st.warning("AI 服务未就绪，请检查 .env 中的 DEEPSEEK_API_KEY 配置")

    if st.session_state.total_saved > 0:
        st.info(f"⏱️ AI已为您节省约 **{st.session_state.total_saved} 分钟**（对比手动录入）")

with col_result:
    st.subheader("📋 识别结果")

    if st.session_state.extractions:
        for i, ext in enumerate(st.session_state.extractions):
            status_icon = {
                "pass": "🟢", "violation": "🔴", "needs_review": "🟡",
            }.get(ext.get("_compliance", {}).get("overall_status", ""), "⚪")
            with st.expander(
                f"{status_icon} ¥{ext.get('amount', 0):.2f} | "
                f"{ext.get('vendor', '未知')[:20]} | {ext.get('date', '')}",
                expanded=(i == 0),
            ):
                cols = st.columns(3)
                cols[0].metric("金额", f"¥{ext.get('amount', 0):,.2f}")
                cols[1].metric("类别", ext.get('category', '其他'))
                cols[2].metric("日期", ext.get('date', '未知'))

                st.caption(f"**开票单位**：{ext.get('vendor', '')}")
                st.caption(f"**发票号**：{ext.get('invoice_number', '无')}")
                st.caption(f"**税号**：{ext.get('tax_id', '无')}")
                st.caption(f"**明细**：{ext.get('items', '无')}")
                if ext.get('city'):
                    st.caption(f"**城市**：{ext['city']}")
                if ext.get('attendee_count'):
                    st.caption(f"**人数**：{ext['attendee_count']}")

                comp = ext.get("_compliance", {})
                badge = {"pass": "✅ 合规", "violation": "❌ 违规", "needs_review": "⚠️ 待补充"}
                st.markdown(f"**审核结果**：{badge.get(comp.get('overall_status', ''), '')}")

                for check in comp.get("checks", []):
                    icon = {"pass": "✅", "fail": "❌", "warning": "⚠️"}
                    st.markdown(f"{icon.get(check.get('status'), '•')} {check.get('detail')}")
                    if check.get("suggestion"):
                        st.caption(f"  💡 {check['suggestion']}")

st.divider()

# ── STEP 3 & 4: Compliance Summary & Generate Form ───────────

if st.session_state.extractions:
    col_review, col_generate = st.columns([1, 1])

    with col_review:
        st.subheader("🔍 合规审核总览")

        all_pass = all(
            c.get("overall_status") == "pass"
            for c in st.session_state.compliance_results
        )
        any_error = any(
            c.get("overall_status") == "violation"
            for c in st.session_state.compliance_results
        )

        if all_pass:
            st.success("🎉 所有发票合规，可直接提交报销！")
        elif any_error:
            st.error("⚠️ 存在违规项，请修正后提交")
        else:
            st.warning("📝 部分发票信息不完整，建议补充")

        total_amount = sum(float(e.get("amount", 0)) for e in st.session_state.extractions)
        cols = st.columns(4)
        cols[0].metric("📄 发票数", len(st.session_state.extractions))
        cols[1].metric("💰 合计金额", f"¥{total_amount:,.2f}")
        cols[2].metric("✅ 合规数",
                       sum(1 for c in st.session_state.compliance_results
                           if c.get("overall_status") == "pass"))
        cols[3].metric("⚠️ 问题数",
                       sum(1 for c in st.session_state.compliance_results
                           if c.get("overall_status") != "pass"))

    with col_generate:
        st.subheader("📝 生成报销单")

        applicant = st.text_input("申请人", placeholder="请输入您的姓名")
        department = st.text_input("部门", placeholder="如：研发部/市场部/销售部")
        reason = st.text_area("报销事由", placeholder="如：2024年Q1差旅费报销")

        can_generate = all([applicant, department, reason])

        if st.button("📥 生成报销单 (Excel)", type="primary",
                     use_container_width=True, disabled=not can_generate):
            agent = st.session_state.agent
            if agent:
                form_data = agent.auto_fill_form(st.session_state.extractions)
                form_data["申请人"] = applicant
                form_data["部门"] = department
                form_data["报销事由"] = reason

                overall = "violation" if any_error else ("needs_review" if not all_pass else "pass")
                compliance_summary = {
                    "overall_status": overall,
                    "summary": f"共{len(st.session_state.extractions)}张发票，合计¥{total_amount:,.2f}",
                    "checks": [],
                }
                for c in st.session_state.compliance_results:
                    compliance_summary["checks"].extend(c.get("checks", []))

                excel_bytes = generate_excel(form_data, compliance_summary)
                st.session_state.form_data = form_data
                st.session_state.excel_bytes = excel_bytes
                st.session_state.step = 4
                st.success("✅ 报销单生成成功！")
                st.rerun()

        if st.session_state.excel_bytes:
            today = datetime.date.today().isoformat()
            st.download_button(
                label=f"⬇️ 下载报销单 ({today}).xlsx",
                data=st.session_state.excel_bytes,
                file_name=f"报销单_{applicant or '未填'}_{today}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

            # Feishu push
            st.divider()
            st.subheader("📨 推送飞书审批")
            if st.button("🚀 发送到飞书", use_container_width=True,
                         disabled=not feishu_url):
                bot = FeishuBot(webhook_url=feishu_url, secret=feishu_secret)
                success = bot.send_approval_notification(
                    applicant=applicant,
                    total_amount=total_amount,
                    invoice_count=len(st.session_state.extractions),
                    compliance_status=overall,
                )
                if success:
                    st.success("✅ 已推送飞书审批通知！")
                    st.balloons()
                else:
                    st.error("推送失败，请检查飞书 Webhook 配置")

    st.divider()

    # ROI Display
    if st.session_state.total_saved > 0:
        with st.expander("📊 效率报告 & ROI 计算"):
            col1, col2, col3, col4 = st.columns(4)
            saved_h = st.session_state.total_saved / 60
            col1.metric("⏱️ 本次节省", f"{st.session_state.total_saved} 分钟 ({saved_h:.1f} 小时)")
            monthly = saved_h * 4
            col2.metric("📅 预估月省", f"{monthly:.1f} 小时")
            col3.metric("📅 预估年省", f"{monthly * 12:.0f} 小时")
            col4.metric("💎 年节省成本", f"¥{monthly * 12 * 150:,.0f}")

            st.caption(f"""
            **计算假设**：
            - 手动处理单张发票耗时约5分钟（查看→录入→核对→填写）
            - AI处理耗时约30秒（上传→自动提取→自动审核）
            - 员工时薪成本约¥150（含社保等）
            - 100人团队年省约 ¥{monthly * 12 * 150 * 100:,.0f}
            """)

else:
    st.info('👆 请上传发票图片，点击「AI识别提取」开始')

# ── Footer ────────────────────────────────────────────────────
st.divider()
st.caption(
    "🤖 智能报销助手 v2.0 | Powered by Qwen AI | "
    "AI预审结果仅供参考，最终以财务审核为准 | "
    "Made for XPeng 效能跃升·AI开挂 赛题三"
)
