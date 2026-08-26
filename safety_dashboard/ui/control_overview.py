"""중앙 관제의 실시간 운영 상태와 현재 상황 요약."""

from __future__ import annotations

import datetime as dt
import html

import pandas as pd
import requests
import streamlit as st
from streamlit_folium import st_folium

from safety_dashboard.application.selection import action_snapshot
from safety_dashboard.domain.enums import DataHealth, RiskGrade
from safety_dashboard.ui.alert_metrics import get_alert_json
from safety_dashboard.ui.app_context import monitoring_context, secret
from safety_dashboard.ui.map_view import build_monitoring_map
from safety_dashboard.ui.workflow import GRADE_RANK, grade_label, render_metric_grid, warning_text


_MODE_LABEL = {"live": "운영", "preview": "미리보기", "paused": "중지"}


def render_control_overview() -> None:
    _render_health_fragment()
    try:
        context = monitoring_context(False)
    except Exception as exc:
        st.error(f"현재 관제 상황을 구성할 수 없습니다 ({type(exc).__name__}).")
        return

    snapshot = context.snapshot
    feed_failed = snapshot.warning_feed.health is DataHealth.ERROR
    feed_stale = snapshot.warning_feed.health is DataHealth.STALE
    if feed_stale:
        st.warning(
            snapshot.warning_feed.message
            or "KMA 수신이 지연되어 마지막 정상 관제 자료를 표시합니다."
        )
    render_metric_grid((
        (
            "활성 특보",
            "—" if feed_failed else snapshot.summary.active_warning_count,
            "KMA 조회 실패" if feed_failed else "공식 KMA 특보",
        ),
        (
            "영향 시설",
            "—" if feed_failed else snapshot.summary.affected_facility_count,
            "판정 중단" if feed_failed else f"전체 {len(snapshot.facilities)}곳 중",
        ),
        (
            "상 위험",
            "—" if feed_failed else snapshot.summary.high_risk_count,
            "즉시 확인 우선",
        ),
        (
            "미판정",
            "—" if feed_failed else snapshot.summary.unassessed_count,
            "관리자 판단 필요",
        ),
    ))

    affected = sorted(
        (
            item
            for item in snapshot.assessments
            if item.grade is not RiskGrade.NONE
        ),
        key=lambda item: (GRADE_RANK[item.grade], item.facility.name),
    )
    list_column, map_column = st.columns((1, 1.55), gap="large")
    with list_column:
        st.markdown("#### 점검 우선순위")
        if feed_failed:
            st.error("KMA 자료 미수신으로 현재 우선순위를 계산하지 못했습니다.")
        elif not affected:
            st.success("현재 특보 영향 시설이 없습니다.")
        else:
            rows = [
                {
                    "등급": grade_label(item.grade),
                    "시설": item.facility.name,
                    "특보": warning_text(item),
                }
                for item in affected[:10]
            ]
            st.dataframe(
                pd.DataFrame(rows),
                hide_index=True,
                width="stretch",
                height=min(390, 38 + 35 * len(rows)),
            )
            if len(affected) > 10:
                st.caption(f"상위 10곳 표시 · 나머지 {len(affected) - 10}곳")
        if st.button(
            "대상 분석·전파에서 확인",
            icon=":material/arrow_forward:",
            width="stretch",
            key="overview-open-analysis",
            on_click=_open_analysis,
        ):
            pass

    with map_column:
        st.markdown("#### 현재 영향시설 위치")
        map_snapshot = (
            action_snapshot(snapshot, [item.facility.id for item in affected])
            if affected
            else snapshot
        )
        st_folium(
            build_monitoring_map(
                map_snapshot,
                context.zone_data,
                mobile_initially_locked=True,
            ),
            use_container_width=True,
            height=470,
            returned_objects=[],
            key=f"control-overview-map-{snapshot.generated_at:%Y%m%d%H%M}",
        )
        st.caption(
            "영향시설이 없으면 전체 시설 위치를 표시합니다. 상세 필터와 대상 선택은 "
            "대상 분석·전파 화면에서 수행합니다."
        )

    _render_recent_events()


@st.fragment(run_every=60)
def _render_health_fragment() -> None:
    st.markdown("#### 운영 경로 상태")
    base_url, token = _admin_connection()
    if not base_url or not token:
        st.info("자동 알림 관리자 API를 설정하면 운영 경로 상태가 표시됩니다.")
        return
    try:
        overview = get_alert_json(
            base_url,
            "/internal/v1/notifications/overview",
            token,
            cache_bucket=int(dt.datetime.now().timestamp() // 60),
        )
    except (requests.RequestException, ValueError) as exc:
        st.error(f"운영 상태를 불러오지 못했습니다 ({type(exc).__name__}).")
        return

    mode = _MODE_LABEL.get(str(overview.get("mode", "")), str(overview.get("mode", "-")))
    kma_live = overview.get("kma_health") == "LIVE"
    worker_fresh = bool(overview.get("worker_fresh"))
    checks = {
        str(item.get("name", "")): item
        for item in overview.get("checks", [])
        if isinstance(item, dict)
    }
    web_check = checks.get("사용자 웹", {})
    api_check = checks.get("공개 API", {})
    telegram_check = checks.get("사용자 Telegram", {})
    cards = (
        ("자동 관제", mode, mode == "운영", _short_time(overview.get("last_run_at"))),
        ("작업자", "정상" if worker_fresh else "지연", worker_fresh, str(overview.get("worker_detail", ""))),
        (
            "KMA",
            "정상" if kma_live else "이상",
            kma_live,
            f"최근 정상 {_short_time(overview.get('kma_last_success_at'))} · "
            f"연속 실패 {int(overview.get('kma_consecutive_errors', 0))}회",
        ),
        (
            "사용자 웹",
            "정상" if web_check.get("healthy") else "이상",
            bool(web_check.get("healthy")),
            str(web_check.get("detail", "확인 기록 없음")),
        ),
        (
            "공개 API",
            "정상" if api_check.get("healthy") else "이상",
            bool(api_check.get("healthy")),
            str(api_check.get("detail", "확인 기록 없음")),
        ),
        (
            "사용자 Telegram",
            "정상" if telegram_check.get("healthy") else "이상",
            bool(telegram_check.get("healthy")),
            f"{telegram_check.get('detail', '확인 기록 없음')} · 최근 발송 "
            f"{_short_time(overview.get('last_user_telegram_at'))}",
        ),
        (
            "전달 방식",
            "Telegram" if overview.get("user_delivery_mode") == "telegram" else "SMS 우선",
            True,
            f"배포 {str(overview.get('app_revision', '-'))[:8]}",
        ),
    )
    card_html = "".join(
        '<div class="ops-status-card">'
        f'<span class="ops-status-dot {"ok" if healthy else "error"}"></span>'
        f'<span class="ops-status-label">{html.escape(label)}</span>'
        f'<strong>{html.escape(value)}</strong>'
        f'<small>{html.escape(detail or "기록 없음")}</small>'
        "</div>"
        for label, value, healthy, detail in cards
    )
    st.markdown(f'<div class="ops-status-grid">{card_html}</div>', unsafe_allow_html=True)

    checks = overview.get("checks", [])
    unhealthy = [
        item for item in checks
        if isinstance(item, dict) and not bool(item.get("healthy"))
    ]
    if not bool(overview.get("healthy")):
        details = " · ".join(
            f"{item.get('name', '경로')} {item.get('detail', '확인 필요')}"
            for item in unhealthy
        )
        st.warning(details or "자동 관제 상태를 확인해 주세요.")
    else:
        paths = " · ".join(
            f"{item.get('name')} {item.get('detail')}"
            for item in checks
            if isinstance(item, dict)
        )
        st.caption(f"운영 경로 정상 · {paths}" if paths else "운영 경로 정상")


def _render_recent_events() -> None:
    base_url, token = _admin_connection()
    if not base_url or not token:
        return
    today = dt.date.today()
    try:
        values = get_alert_json(
            base_url,
            "/internal/v1/notifications/events",
            token,
            params=(
                ("from", (today - dt.timedelta(days=1)).isoformat()),
                ("to", today.isoformat()),
                ("limit", "5"),
            ),
            cache_bucket=int(dt.datetime.now().timestamp() // 60),
        )
    except (requests.RequestException, ValueError):
        return
    events = values.get("events", [])
    if not isinstance(events, list) or not events:
        return
    st.markdown("#### 최근 전파 이력")
    rows = [
        {
            "시각": _short_time(item.get("occurred_at")),
            "출처": "자동" if item.get("source") == "automatic" else "수동",
            "구분": item.get("event", "-"),
            "시설": f"{int(item.get('facility_count', 0))}곳",
            "상태": item.get("status", "-"),
        }
        for item in events
        if isinstance(item, dict)
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _admin_connection() -> tuple[str, str]:
    return (
        secret("alerting", "admin_api_url", "ALERT_ADMIN_API_URL"),
        secret("alerting", "admin_token", "ALERT_ADMIN_TOKEN"),
    )


def _open_analysis() -> None:
    st.session_state["control-workspace"] = "대상 분석·전파"


def _short_time(value: object) -> str:
    if not value:
        return "기록 없음"
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(dt.timezone(dt.timedelta(hours=9))).strftime(
            "%m-%d %H:%M"
        )
    except ValueError:
        return str(value)[:16]
