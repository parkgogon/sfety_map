"""조회에서 확정한 대상을 사용하는 Telegram·PDF 작업창."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from safety_dashboard.adapters.pdf_report import PdfReportRenderer
from safety_dashboard.adapters.telegram import TelegramNotifier
from safety_dashboard.application.deep_links import dashboard_home_url
from safety_dashboard.application.notifications import build_telegram_payloads
from safety_dashboard.domain.models import DashboardSnapshot


def _render_summary(snapshot: DashboardSnapshot) -> None:
    columns = st.columns(3)
    columns[0].metric("선택 시설", len(snapshot.facilities))
    columns[1].metric("연결 특보", len(snapshot.warning_feed.warnings))
    columns[2].metric("상 위험", snapshot.summary.high_risk_count)


@st.dialog("Telegram 발송", width="large")
def telegram_dialog(
    selected_snapshot: DashboardSnapshot,
    scope_label: str,
    fingerprint: str,
    simulation: bool,
    bot_token: str,
    chat_id: str,
    temporary_policy: bool = False,
    dashboard_base_url: str = "",
) -> None:
    _render_summary(selected_snapshot)
    st.caption(f"조회 범위 · {scope_label}")
    messages = build_telegram_payloads(
        selected_snapshot,
        scope_label=scope_label,
        mode="모의훈련" if simulation else "실시간",
        dashboard_base_url=dashboard_base_url,
        temporary_policy=temporary_policy,
    )
    if not dashboard_home_url(dashboard_base_url):
        st.warning(
            "유효한 HTTPS 대시보드 주소가 없어 이번 메시지에서는 "
            "시설 딥링크를 생략합니다. 발송은 계속할 수 있습니다."
        )
    preview = []
    for index, message in enumerate(messages, start=1):
        delivery = "무음" if message.silent else "일반 알림"
        preview.append(
            f"[{index}/{len(messages)} · {delivery}]\n{message.text}"
        )
    st.text_area(
        "메시지 미리보기",
        value="\n\n--- 다음 메시지 ---\n\n".join(preview),
        height=340,
        disabled=True,
    )
    confirmed = st.checkbox(
        f"선택한 {len(selected_snapshot.facilities)}개 시설의 내용을 발송합니다.",
        key=f"telegram-confirm-{fingerprint}",
    )
    if st.button(
        "Telegram 발송",
        type="primary",
        disabled=not confirmed,
        key=f"telegram-send-{fingerprint}",
        width="stretch",
    ):
        result = TelegramNotifier(bot_token, chat_id).send_batch(messages)
        (st.success if result.success else st.error)(result.message)


@st.dialog("PDF 보고서", width="large")
def report_dialog(
    selected_snapshot: DashboardSnapshot,
    scope_label: str,
    fingerprint: str,
    font_path: str | Path,
    temporary_policy: bool = False,
) -> None:
    _render_summary(selected_snapshot)
    st.caption(f"조회 범위 · {scope_label}")
    st.write(
        "체크한 시설과 해당 시설에 연결된 특보만 보고서에 포함됩니다. "
        f"위험도 정책은 `{selected_snapshot.policy_version}`입니다."
    )
    if temporary_policy:
        st.warning("이 보고서에는 현재 브라우저의 임시 위험도 기준이 사용됩니다.")
    if st.button(
        "PDF 생성",
        type="primary",
        key=f"pdf-generate-{fingerprint}",
        width="stretch",
    ):
        try:
            st.session_state["report_pdf"] = PdfReportRenderer(font_path).render(
                selected_snapshot,
                scope_label=scope_label,
                temporary_policy=temporary_policy,
            )
            st.session_state["report_name"] = (
                f"weather_safety_{selected_snapshot.generated_at:%Y%m%d_%H%M}.pdf"
            )
            st.session_state["report_fingerprint"] = fingerprint
        except Exception as exc:
            st.error(f"PDF를 생성하지 못했습니다: {exc}")
    if (
        st.session_state.get("report_pdf")
        and st.session_state.get("report_fingerprint") == fingerprint
    ):
        st.download_button(
            "PDF 다운로드",
            data=st.session_state["report_pdf"],
            file_name=st.session_state["report_name"],
            mime="application/pdf",
            width="stretch",
            key=f"pdf-download-{fingerprint}",
        )
