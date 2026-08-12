"""중앙 관제의 전화번호 없는 자동 알림 실적 패널."""

from __future__ import annotations

import datetime as dt
from typing import Any

import requests
import streamlit as st

from safety_dashboard.ui.app_context import secret


_MODE_LABEL = {"preview": "미리보기", "live": "운영", "paused": "중지"}


@st.cache_data(ttl=60, show_spinner=False)
def _get_json(
    base_url: str,
    path: str,
    token: str,
    params: tuple[tuple[str, str], ...] = (),
) -> dict[str, Any]:
    response = requests.get(
        base_url.rstrip("/") + path,
        headers={"X-Alert-Admin-Token": token},
        params=dict(params),
        timeout=7,
    )
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, dict):
        raise ValueError("자동 알림 API 응답 형식이 올바르지 않습니다.")
    return value


def render_alert_metrics() -> None:
    with st.expander("자동 알림 실적", expanded=False):
        base_url = secret(
            "alerting",
            "admin_api_url",
            "ALERT_ADMIN_API_URL",
        )
        token = secret(
            "alerting",
            "admin_token",
            "ALERT_ADMIN_TOKEN",
        )
        if not base_url or not token:
            st.info(
                "자동 알림 작업자를 배포한 뒤 관리자 API 주소와 통계 토큰을 "
                "Streamlit secrets에 설정하면 실적이 표시됩니다."
            )
            return
        today = dt.date.today()
        default_start = dt.date(today.year, 1, 1)
        period_columns = st.columns(2)
        start = period_columns[0].date_input(
            "시작일",
            value=default_start,
            key="alert-metrics-start",
        )
        end = period_columns[1].date_input(
            "종료일",
            value=today,
            key="alert-metrics-end",
        )
        if st.button(
            "실적 불러오기",
            icon=":material/refresh:",
            key="load-alert-metrics",
        ):
            st.session_state["alert_metrics_loaded"] = True
        if not st.session_state.get("alert_metrics_loaded", False):
            st.caption("필요할 때만 조회해 중앙 관제 첫 로딩에 영향을 주지 않습니다.")
            return
        try:
            status = _get_json(base_url, "/internal/v1/notifications/status", token)
            metrics = _get_json(
                base_url,
                "/internal/v1/notifications/metrics",
                token,
                (("from", start.isoformat()), ("to", end.isoformat())),
            )
        except (requests.RequestException, ValueError) as exc:
            st.warning(f"자동 알림 실적을 불러오지 못했습니다 ({type(exc).__name__}).")
            return

        mode = _MODE_LABEL.get(str(status.get("mode", "")), str(status.get("mode", "-")))
        st.caption(
            f"운영 상태 · {mode} · 최근 결과 {status.get('last_result', '-')} · "
            f"정책 {status.get('policy_version', '-')} · "
            f"일일 상한 {status.get('daily_cap', 500)}건"
        )
        totals = metrics.get("totals", {})
        if not isinstance(totals, dict):
            totals = {}
        first = st.columns(4)
        first[0].metric("자동 관제", int(totals.get("poll_runs", 0)))
        first[1].metric("영향시설 통보", int(totals.get("affected_facility_events", 0)))
        first[2].metric("고유 수신자", int(totals.get("unique_recipients", 0)))
        first[3].metric("SOLAPI 접수", int(totals.get("sms_accepted", 0)))
        transitions = st.columns(3)
        transitions[0].metric("특보 발효", int(totals.get("warning_activated", 0)))
        transitions[1].metric("특보 격상", int(totals.get("warning_escalated", 0)))
        transitions[2].metric("특보 해제", int(totals.get("warning_cleared", 0)))
        second = st.columns(4)
        second[0].metric("문자 시도", int(totals.get("sms_attempted", 0)))
        second[1].metric("수신 완료", int(totals.get("sms_delivered", 0)))
        second[2].metric("실패·확인불가", (
            int(totals.get("sms_failed", 0)) + int(totals.get("sms_unknown", 0))
        ))
        success_rate = metrics.get("delivery_success_rate")
        second[3].metric(
            "전달 성공률",
            "—" if success_rate is None else f"{success_rate}%",
        )
        st.caption(
            "수신 완료는 통신사 결과이며 실제 열람을 의미하지 않습니다. "
            f"연락처 미매핑 {int(totals.get('unmapped_facilities', 0))}건 · "
            f"상한 차단 {int(totals.get('cap_blocked', 0))}건"
        )
        st.markdown("미리보기·시험 발송 · 운영 실적 제외")
        excluded = st.columns(4)
        excluded[0].metric(
            "미리보기 관제",
            int(totals.get("preview_poll_runs", 0)),
        )
        excluded[1].metric(
            "예상 문자",
            int(totals.get("preview_messages", 0)),
        )
        excluded[2].metric(
            "시험 발송",
            int(totals.get("test_sms_attempted", 0)),
        )
        excluded[3].metric(
            "시험 수신완료",
            int(totals.get("test_sms_delivered", 0)),
        )
        if mode == "미리보기":
            estimated_cost = int(status.get("preview_estimated_cost_krw", 0))
            st.caption(
                f"최근 변화 기준 예상 요금 · {estimated_cost:,}원 "
                "(LMS 45원·VAT 별도 가정)"
            )
            samples = status.get("preview_samples", [])
            if isinstance(samples, list) and samples:
                st.caption("전화번호를 제외한 최근 문자 미리보기")
                for index, sample in enumerate(samples, start=1):
                    if not isinstance(sample, dict):
                        continue
                    st.code(
                        str(sample.get("text", "")),
                        language=None,
                    )
        if st.button(
            "실적 CSV 준비",
            icon=":material/download:",
            key="prepare-alert-metrics-csv",
        ):
            try:
                response = requests.get(
                    base_url.rstrip("/") + "/internal/v1/notifications/export.csv",
                    headers={"X-Alert-Admin-Token": token},
                    params={"from": start.isoformat(), "to": end.isoformat()},
                    timeout=15,
                )
                response.raise_for_status()
                st.session_state["alert_metrics_csv"] = response.content
                st.session_state["alert_metrics_csv_name"] = (
                    f"automatic_alerts_{start}_{end}.csv"
                )
            except requests.RequestException as exc:
                st.warning(f"CSV를 준비하지 못했습니다 ({type(exc).__name__}).")
        if st.session_state.get("alert_metrics_csv"):
            st.download_button(
                "전화번호 없는 실적 CSV 다운로드",
                data=st.session_state["alert_metrics_csv"],
                file_name=st.session_state["alert_metrics_csv_name"],
                mime="text/csv",
                key="download-alert-metrics-csv",
            )
