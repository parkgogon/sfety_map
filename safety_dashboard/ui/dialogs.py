"""조회에서 확정한 대상을 사용하는 Telegram·PDF 작업창."""

from __future__ import annotations

from pathlib import Path
import uuid

import requests
import streamlit as st

from safety_dashboard.adapters.pdf_report import PdfReportRenderer
from safety_dashboard.application.deep_links import dashboard_home_url
from safety_dashboard.application.notifications import build_manual_telegram_payloads
from safety_dashboard.alerts.domain import ManualTelegramCategory
from safety_dashboard.domain.models import DashboardSnapshot


def _render_summary(snapshot: DashboardSnapshot) -> None:
    columns = st.columns(3)
    columns[0].metric("선택 시설", len(snapshot.facilities))
    columns[1].metric("연결 특보", len(snapshot.warning_feed.warnings))
    columns[2].metric("상 위험", snapshot.summary.high_risk_count)


_MANUAL_CATEGORY_LABELS = {
    ManualTelegramCategory.REMINDER: "재공지",
    ManualTelegramCategory.CORRECTION: "정정",
    ManualTelegramCategory.ADDITIONAL: "추가안내",
    ManualTelegramCategory.DRILL: "훈련",
}


@st.dialog("시설담당자 그룹 수동 전파", width="large")
def telegram_dialog(
    selected_snapshot: DashboardSnapshot,
    scope_label: str,
    fingerprint: str,
    simulation: bool,
    admin_api_url: str,
    admin_token: str,
    temporary_policy: bool = False,
    dashboard_base_url: str = "",
) -> None:
    _render_summary(selected_snapshot)
    result_key = f"manual-result-{fingerprint}"
    previous_result = st.session_state.get(result_key)
    if isinstance(previous_result, dict):
        if previous_result.get("status") == "SENT":
            st.success("시설담당자 그룹에 수동 전파를 완료했습니다.")
        else:
            st.warning("즉시 발송에 실패해 최대 30분 재시도를 예약했습니다.")
        st.caption(f"요청 ID · {previous_result.get('dispatch_id', '-')}")
        if st.button(
            "새 수동 전파 작성",
            icon=":material/replay:",
            width="stretch",
            key=f"manual-new-{fingerprint}",
        ):
            for key in (
                result_key,
                f"manual-request-id-{fingerprint}",
                f"manual-duplicate-{fingerprint}",
                f"manual-confirm-{fingerprint}",
                f"manual-drill-confirm-{fingerprint}",
                f"manual-policy-confirm-{fingerprint}",
                f"manual-duplicate-confirm-{fingerprint}",
            ):
                st.session_state.pop(key, None)
            st.rerun()
        return
    st.caption(
        f"수신 그룹 · K-ECO 시설 재난특보 · 조회 범위 · {scope_label}"
    )
    if simulation:
        category = ManualTelegramCategory.DRILL
        st.warning(
            "모의훈련 자료입니다. 시설담당자 그룹에 실제 재난이 아닌 훈련 메시지로 "
            "명확히 표시해 전파합니다."
        )
    else:
        category = st.selectbox(
            "전파 구분",
            options=(
                ManualTelegramCategory.REMINDER,
                ManualTelegramCategory.CORRECTION,
                ManualTelegramCategory.ADDITIONAL,
            ),
            format_func=lambda item: _MANUAL_CATEGORY_LABELS[item],
            key=f"manual-category-{fingerprint}",
        )
    note = st.text_area(
        "관리자 메모",
        max_chars=200,
        placeholder=(
            "정정할 내용 또는 추가 현장 안내를 입력하세요."
            if category in {
                ManualTelegramCategory.CORRECTION,
                ManualTelegramCategory.ADDITIONAL,
            }
            else "필요한 경우 짧은 안내를 덧붙이세요."
        ),
        key=f"manual-note-{fingerprint}",
    )
    st.caption("발송자 · 중앙관제 관리자 · 최대 200자")
    note_required = category in {
        ManualTelegramCategory.CORRECTION,
        ManualTelegramCategory.ADDITIONAL,
    }
    if note_required and not note.strip():
        st.info("정정·추가안내에는 관리자 메모가 필요합니다.")
    messages = build_manual_telegram_payloads(
        selected_snapshot,
        category,
        note,
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
    st.markdown("#### 최종 확인")
    confirmed = st.checkbox(
        f"시설담당자 그룹에 시설 {len(selected_snapshot.facilities)}곳, "
        f"메시지 {len(messages)}건을 수동 전파합니다.",
        key=f"manual-confirm-{fingerprint}",
    )
    drill_confirmed = not simulation or st.checkbox(
        "모의훈련이며 실제 재난 알림이 아님을 확인했습니다.",
        key=f"manual-drill-confirm-{fingerprint}",
    )
    temporary_confirmed = not temporary_policy or st.checkbox(
        "현재 브라우저의 임시 위험도 기준이 포함됨을 확인했습니다.",
        key=f"manual-policy-confirm-{fingerprint}",
    )
    duplicate = st.session_state.get(f"manual-duplicate-{fingerprint}")
    duplicate_confirmed = duplicate is None
    if isinstance(duplicate, dict):
        st.warning(
            "최근 30분 내 유사 전파가 있습니다. · "
            f"{duplicate.get('source', '-')} · {duplicate.get('event', '-')} · "
            f"{duplicate.get('occurred_at', '-')}"
        )
        duplicate_confirmed = st.checkbox(
            "중복 가능성을 확인했으며 다시 전파합니다.",
            key=f"manual-duplicate-confirm-{fingerprint}",
        )
    request_key = f"manual-request-id-{fingerprint}"
    if request_key not in st.session_state:
        st.session_state[request_key] = f"manual-{uuid.uuid4().hex}"
    if not admin_api_url or not admin_token:
        st.error(
            "관리자 전파 API가 설정되지 않아 발송할 수 없습니다. "
            "관리자 API 주소와 토큰을 확인해 주세요."
        )
    can_send = bool(
        admin_api_url
        and admin_token
        and confirmed
        and drill_confirmed
        and temporary_confirmed
        and duplicate_confirmed
        and (not note_required or note.strip())
    )
    if st.button(
        "시설담당자 그룹에 수동 전파",
        type="primary",
        disabled=not can_send,
        key=f"manual-send-{fingerprint}",
        width="stretch",
    ):
        warning_keys = tuple(sorted({
            f"{warning.region_code}|{warning.warning_type}"
            for warning in selected_snapshot.warning_feed.warnings
        }))
        payload = {
            "request_id": st.session_state[request_key],
            "category": category.value,
            "mode": "simulation" if simulation else "live",
            "note": note.strip(),
            "facility_ids": [item.id for item in selected_snapshot.facilities],
            "warning_keys": list(warning_keys),
            "messages": [
                {
                    "text": item.text,
                    "silent": item.silent,
                    "action_label": item.action_label,
                    "action_url": item.action_url,
                }
                for item in messages
            ],
            "policy_version": selected_snapshot.policy_version,
            "temporary_policy": temporary_policy,
            "allow_duplicate": isinstance(duplicate, dict) and duplicate_confirmed,
        }
        try:
            response = requests.post(
                admin_api_url.rstrip("/") + "/internal/v1/notifications/manual",
                headers={"X-Alert-Admin-Token": admin_token},
                json=payload,
                timeout=15,
            )
            if response.status_code == 409:
                detail = response.json().get("detail", {})
                duplicate_value = (
                    detail.get("duplicate", {})
                    if isinstance(detail, dict)
                    else {}
                )
                st.session_state[f"manual-duplicate-{fingerprint}"] = duplicate_value
                st.rerun()
            response.raise_for_status()
            result = response.json()
            status = str(result.get("status", ""))
            if status not in {"SENT", "RETRY_QUEUED"}:
                raise ValueError(
                    str(result.get("detail", "수동 전파 요청 결과를 확인할 수 없습니다."))
                )
            st.session_state[result_key] = result
            st.session_state.pop(f"manual-duplicate-{fingerprint}", None)
            st.rerun()
        except (requests.RequestException, ValueError) as exc:
            st.error(f"수동 전파를 처리하지 못했습니다 ({type(exc).__name__}).")


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
