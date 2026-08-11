"""시설 담당자용 지도 중심 현장 화면."""

from __future__ import annotations

import datetime as dt
import html

import streamlit as st
from streamlit_folium import st_folium

from safety_dashboard.adapters.cctv import DEFAULT_API_URL as CCTV_API_URL
from safety_dashboard.adapters.disaster_messages import (
    DEFAULT_API_URL as DISASTER_API_URL,
)
from safety_dashboard.application.contacts import public_contact
from safety_dashboard.application.context_info import (
    build_news_search_url,
    resolve_facility_region,
)
from safety_dashboard.application.map_selection import resolve_map_selection
from safety_dashboard.application.selection import filter_snapshot
from safety_dashboard.domain.enums import DataHealth, RiskGrade
from safety_dashboard.ui.app_context import (
    DIRECTION_PATH,
    KST,
    clear_live_caches,
    load_cctv_directions,
    load_cctv_feed,
    load_current_weather,
    load_disaster_feed,
    monitoring_context,
    secret,
)
from safety_dashboard.ui.cctv_viewer import cctv_viewer_dialog
from safety_dashboard.ui.context_panel import render_facility_context
from safety_dashboard.ui.map_view import COLORS, build_monitoring_map
from safety_dashboard.ui.workflow import GRADE_ORDER, grade_label, scope_fingerprint


def _query_value(name: str) -> str:
    value = st.query_params.get(name, "")
    if isinstance(value, list):
        value = value[-1] if value else ""
    return str(value or "").strip()[:128]


def _clear_facility_query() -> None:
    if "facility_id" in st.query_params:
        del st.query_params["facility_id"]
    st.session_state.pop("field_deep_link_revision", None)


def _select_search_result() -> None:
    selected = str(st.session_state.get("field_facility_search", "") or "")
    if selected:
        st.session_state["field_selected_facility_id"] = selected
        st.session_state["field_focus_facility_id"] = selected
        st.query_params["facility_id"] = selected


try:
    context = monitoring_context(False)
except Exception as exc:
    st.error(f"현장 지도를 구성할 수 없습니다: {exc}")
    st.stop()

snapshot = context.snapshot
catalog = context.facility_groups
policy = context.policy
feed_failed = snapshot.warning_feed.health is DataHealth.ERROR
feed_label = {
    DataHealth.LIVE: "정상",
    DataHealth.SIMULATION: "훈련",
    DataHealth.ERROR: "조회 실패",
    DataHealth.FALLBACK: "내장본",
    DataHealth.STALE: "지연",
}[snapshot.warning_feed.health]

st.markdown(
    '<div class="app-kicker">K-ECO SAFETY MONITORING</div>',
    unsafe_allow_html=True,
)
st.markdown('<div class="app-title">현장 지도</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="app-subtitle field-intro">시설을 눌러 현재 특보 영향과 '
    '현장 참고정보를 확인합니다.</div>',
    unsafe_allow_html=True,
)
st.markdown(
    f'<div class="status-strip field-status-strip">'
    f'<span class="field-status-desktop">실시간 · KMA {html.escape(feed_label)}'
    f' · {snapshot.generated_at:%Y-%m-%d %H:%M} 기준'
    f' · 정책 {html.escape(policy.version)}</span>'
    f'<span class="field-status-mobile">KMA {html.escape(feed_label)}'
    f' · {snapshot.generated_at:%m-%d %H:%M}</span></div>',
    unsafe_allow_html=True,
)
if feed_failed:
    st.warning(
        snapshot.warning_feed.message
        or "KMA 자료를 조회하지 못했습니다. 시설 위치는 계속 확인할 수 있습니다."
    )
if context.zone_health is DataHealth.FALLBACK:
    st.info("최신 경계를 불러오지 못해 검증된 내장 특보구역을 사용 중입니다.")
if context.temporary_policy:
    st.warning("현재 브라우저의 임시 위험도 기준이 적용 중입니다.")

valid_groups = set(catalog.ids)
field_groups = [
    item
    for item in st.session_state.get("field_facility_groups", catalog.ids)
    if item in valid_groups
]
if not field_groups:
    field_groups = list(catalog.ids)

requested_id = _query_value("facility_id")
if requested_id:
    requested_assessment = next(
        (
            item
            for item in snapshot.assessments
            if item.facility.id == requested_id
        ),
        None,
    )
    if requested_assessment is None:
        st.warning("요청한 시설 ID를 찾을 수 없어 전체 현장 지도를 표시합니다.")
        st.button(
            "잘못된 시설 링크 지우기",
            on_click=_clear_facility_query,
            key="field-clear-invalid-link",
        )
    else:
        group_id = catalog.group_for_type(
            requested_assessment.facility.facility_type
        ).id
        if group_id not in field_groups:
            field_groups.append(group_id)
            st.session_state["field_facility_group_filter"] = field_groups
        revision = f"{requested_id}:{snapshot.policy_version}"
        if st.session_state.get("field_deep_link_revision") != revision:
            st.session_state["field_selected_facility_id"] = requested_id
            st.session_state["field_focus_facility_id"] = requested_id
            st.session_state["field_deep_link_revision"] = revision

st.session_state["field_facility_groups"] = field_groups
group_counts = catalog.counts(snapshot.facilities)
filter_column, refresh_column = st.columns((5, 1), vertical_alignment="bottom")
with filter_column:
    chosen_groups = st.pills(
        "시설 유형",
        options=list(catalog.ids),
        default=field_groups,
        selection_mode="multi",
        format_func=lambda value: (
            f"{catalog.definition(value).label} {group_counts[value]}"
        ),
        key="field_facility_group_filter",
        width="stretch",
    )
with refresh_column:
    if st.button(
        "새로고침",
        icon=":material/refresh:",
        width="stretch",
        key="field-refresh",
    ):
        clear_live_caches()
        st.rerun()

selected_groups = list(chosen_groups or [])
st.session_state["field_facility_groups"] = selected_groups
if not selected_groups:
    st.info("시설 유형을 하나 이상 선택해 주세요.")

field_snapshot = filter_snapshot(
    snapshot,
    catalog,
    selected_groups,
    list(GRADE_ORDER),
)
visible_ids = {item.id for item in field_snapshot.facilities}
search_options = sorted(visible_ids, key=lambda facility_id: next(
    item.name for item in field_snapshot.facilities if item.id == facility_id
))
st.selectbox(
    "시설명·주소 검색",
    options=search_options,
    index=None,
    placeholder="시설명이나 주소를 입력하세요",
    format_func=lambda facility_id: next(
        f"{item.name} · {item.address}"
        for item in field_snapshot.facilities
        if item.id == facility_id
    ),
    key="field_facility_search",
    on_change=_select_search_result,
)

selected_id = str(st.session_state.get("field_selected_facility_id", ""))
if selected_id not in visible_ids:
    selected_id = ""
    st.session_state.pop("field_selected_facility_id", None)
focus_id = str(st.session_state.get("field_focus_facility_id", ""))
if focus_id not in visible_ids:
    focus_id = ""
    st.session_state.pop("field_focus_facility_id", None)

reference = dt.datetime.now(KST).replace(second=0, microsecond=0)
reference_10m = reference.replace(minute=(reference.minute // 10) * 10)
context_loaded = (
    selected_id
    and st.session_state.get("field_context_facility_id") == selected_id
)
weather = None
disaster_feed = None
cctv_feed = None
cctv_direction_warning = ""
if context_loaded:
    selected_facility = next(
        item for item in snapshot.facilities if item.id == selected_id
    )
    weather = load_current_weather(
        secret("kma", "api_key", "KMA_API_KEY"),
        selected_facility.location.latitude,
        selected_facility.location.longitude,
        reference_10m.isoformat(),
    )
    region = resolve_facility_region(selected_facility.address)
    if region is not None:
        disaster_feed = load_disaster_feed(
            secret("safety_data", "api_key", "SAFETY_DATA_API_KEY"),
            secret("safety_data", "api_url", "SAFETY_DATA_API_URL")
            or DISASTER_API_URL,
            region.province,
            region.district,
            region.query_name,
            reference.isoformat(),
        )
    cctv_refresh_key = f"field-cctv-refresh-{selected_id}"
    cctv_feed = load_cctv_feed(
        secret("its_cctv", "api_key", "ITS_CCTV_API_KEY"),
        secret("its_cctv", "api_url", "ITS_CCTV_API_URL") or CCTV_API_URL,
        selected_facility.location.latitude,
        selected_facility.location.longitude,
        reference.isoformat(),
        str(st.session_state.get(cctv_refresh_key, "initial")),
    )
    try:
        direction_catalog, cctv_direction_warning = load_cctv_directions(
            DIRECTION_PATH.stat().st_mtime
        )
        cctv_feed = direction_catalog.enrich_feed(cctv_feed)
    except OSError as exc:
        cctv_direction_warning = str(exc)

nearby_cctvs = cctv_feed.cctvs if cctv_feed else ()
scope_key = scope_fingerprint(
    snapshot,
    False,
    selected_groups,
    list(GRADE_ORDER),
    configuration_revision=f"field:{policy.version}",
)


@st.fragment
def render_field_map_and_detail() -> None:
    current_selected_id = str(
        st.session_state.get("field_selected_facility_id", selected_id)
    )
    with st.container(key="field-map-caption"):
        st.caption(
            f"표시 시설 {len(field_snapshot.facilities)}개 · "
            "등급별 표시는 지도 오른쪽 아래 레이어에서 조절합니다."
        )
    with st.container(key="field-monitoring-map"):
        map_state = st_folium(
            build_monitoring_map(
                field_snapshot,
                context.zone_data,
                focus_facility_id=focus_id,
                nearby_cctvs=nearby_cctvs,
                cctv_focus_facility_id=(
                    current_selected_id if nearby_cctvs else ""
                ),
                selected_facility_id=current_selected_id,
                mobile_initially_locked=False,
                grade_layers=True,
            ),
            use_container_width=True,
            height=650,
            returned_objects=(
                "last_object_clicked",
                "last_object_clicked_count",
                "last_object_clicked_tooltip",
            ),
            key=f"field-map-{scope_key}-{bool(nearby_cctvs)}",
        ) or {}
    selection = resolve_map_selection(
        field_snapshot,
        nearby_cctvs,
        map_state.get("last_object_clicked_tooltip"),
        map_state.get("last_object_clicked"),
    )
    click_count = map_state.get("last_object_clicked_count")
    if selection is not None and click_count is not None:
        fingerprint = f"{scope_key}:{click_count}:{selection.kind}:"
        fingerprint += selection.facility_id or selection.cctv_id
        if st.session_state.get("field_handled_map_click") != fingerprint:
            st.session_state["field_handled_map_click"] = fingerprint
            if selection.kind == "facility":
                current_selected_id = selection.facility_id
                st.session_state["field_selected_facility_id"] = current_selected_id
                st.session_state.pop("field_focus_facility_id", None)
                st.query_params["facility_id"] = current_selected_id
                st.session_state["field_deep_link_revision"] = (
                    f"{current_selected_id}:{snapshot.policy_version}"
                )
                st.rerun(scope="fragment")
            elif selection.kind == "cctv":
                st.session_state["field_open_cctv_id"] = selection.cctv_id
                st.rerun()

    assessment = next(
        (
            item
            for item in field_snapshot.assessments
            if item.facility.id == current_selected_id
        ),
        None,
    )
    with st.container(key="field-detail-title"):
        st.markdown("### 선택 시설")
    if assessment is None:
        with st.container(key="field-empty-desktop"):
            st.info(
                "지도 마커를 누르거나 시설을 검색하면 상세정보가 표시됩니다."
            )
        st.markdown(
            '<div class="mobile-only field-empty-state">'
            '지도에서 시설을 선택하세요.</div>',
            unsafe_allow_html=True,
        )
        return
    definition = policy.definition(assessment.grade)
    reasons = " · ".join(
        dict.fromkeys(
            f"{item.warning_type} {item.raw_level} ({item.region})"
            for item in assessment.reasons
        )
    ) or "현재 영향 특보 없음"
    st.markdown(
        f'<div class="field-detail-card"><div class="field-detail-heading">'
        f'<span class="grade-pill" style="background:{COLORS[assessment.grade]}">'
        f'{html.escape(grade_label(assessment.grade))}</span>'
        f'<b>{html.escape(assessment.facility.name)}</b></div>'
        f'<div class="field-detail-grid">'
        f'<div><span>시설 유형</span><b>{html.escape(assessment.facility.facility_type)}</b></div>'
        f'<div><span>영향 특보</span><b>{html.escape(reasons)}</b></div>'
        f'<div><span>권장 행동</span><b>{html.escape(definition.action)}</b></div>'
        f'<div><span>담당</span><b>{html.escape(public_contact(assessment.facility))}</b></div>'
        f'<div class="field-address"><span>주소</span><b>{html.escape(assessment.facility.address)}</b></div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )
    loaded_for_current = (
        st.session_state.get("field_context_facility_id") == current_selected_id
    )
    if not loaded_for_current:
        if st.button(
            "현장 참고정보 불러오기",
            icon=":material/cloud_download:",
            type="primary",
            width="stretch",
            key=f"load-field-context-{current_selected_id}",
        ):
            st.session_state["field_context_facility_id"] = current_selected_id
            st.rerun()
        st.caption(
            "현재 기상·재난문자·인근 CCTV는 버튼을 누를 때만 조회합니다."
        )
        return

    facility_region = resolve_facility_region(assessment.facility.address)
    news_url = build_news_search_url(
        assessment.facility,
        facility_region,
        (item.warning_type for item in assessment.reasons),
    )
    render_facility_context(
        facility_region,
        disaster_feed,
        news_url,
        cctv_feed=cctv_feed,
        cctv_direction_warning=cctv_direction_warning,
        weather=weather,
    )


render_field_map_and_detail()

open_cctv_id = str(st.session_state.pop("field_open_cctv_id", ""))
reopen_cctv_id = str(st.session_state.pop("reopen_cctv_id", ""))
cctv_to_open = next(
    (
        item
        for item in nearby_cctvs
        if item.id == (reopen_cctv_id or open_cctv_id)
    ),
    None,
)
if cctv_to_open is not None and cctv_feed is not None and selected_id:
    cctv_viewer_dialog(
        cctv_to_open,
        cctv_feed.fetched_at,
        f"field-cctv-refresh-{selected_id}",
    )
