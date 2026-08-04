"""기상재난 시설 관제 대시보드 v3 진입점."""

from __future__ import annotations

import html
import os
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from core.region_resolver import WarningZoneIndex
from safety_dashboard.adapters.facility_csv import CsvFacilityRepository
from safety_dashboard.adapters.kma import (
    FeedWarningProvider,
    KmaWarningProvider,
    StaticWarningProvider,
    WarningZoneRepository,
    simulation_warnings,
)
from safety_dashboard.adapters.region_matcher import OfficialZoneMatcher
from safety_dashboard.application.facility_groups import FacilityGroupCatalog
from safety_dashboard.application.monitoring import MonitoringService
from safety_dashboard.application.selection import action_snapshot, filter_snapshot
from safety_dashboard.domain.enums import DataHealth, RiskGrade
from safety_dashboard.domain.risk_policy import RiskPolicy
from safety_dashboard.ui.dialogs import report_dialog, telegram_dialog
from safety_dashboard.ui.map_view import COLORS, build_monitoring_map
from safety_dashboard.ui.policy_editor import effective_policy, policy_editor_dialog
from safety_dashboard.ui.workflow import (
    GRADE_ORDER,
    GRADE_RANK,
    action_fingerprint,
    grade_label,
    make_scope_label,
    render_metric,
    scope_fingerprint,
    warning_text,
)


ROOT = Path(__file__).resolve().parent
POLICY_PATH = ROOT / "safety_dashboard" / "config" / "risk_policy.toml"
GROUP_PATH = ROOT / "safety_dashboard" / "config" / "facility_groups.toml"
FACILITY_PATH = ROOT / "facilities_info.csv"
ZONE_FALLBACK_PATH = ROOT / "data" / "kma_warning_zones.geojson.gz"
FONT_PATH = ROOT / "fonts" / "NotoSansKR.ttf"

st.set_page_config(
    page_title="기상재난 시설 관제",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.markdown(
    f"<style>{(ROOT / 'safety_dashboard/ui/style.css').read_text()}</style>",
    unsafe_allow_html=True,
)


def secret(section: str, key: str, env_name: str) -> str:
    env_value = os.getenv(env_name, "").strip()
    if env_value:
        return env_value
    try:
        return str(st.secrets[section][key]).strip()
    except (KeyError, TypeError, FileNotFoundError):
        return ""


@st.cache_resource
def load_policy(modified_at: float) -> RiskPolicy:
    del modified_at
    return RiskPolicy.load(POLICY_PATH)


@st.cache_resource
def load_facility_groups(modified_at: float) -> FacilityGroupCatalog:
    del modified_at
    return FacilityGroupCatalog.load(GROUP_PATH)


@st.cache_data(ttl=86400, show_spinner=False)
def load_zones() -> tuple[dict, DataHealth, str]:
    return WarningZoneRepository(ZONE_FALLBACK_PATH).load()


@st.cache_data(ttl=600, show_spinner=False)
def load_live_feed(api_key: str, policy_modified_at: float):
    policy = RiskPolicy.load(POLICY_PATH)
    return KmaWarningProvider(api_key, policy).fetch_active()


def make_snapshot(simulation: bool, policy: RiskPolicy):
    zone_data, zone_health, zone_message = load_zones()
    zone_index = WarningZoneIndex.from_geojson(zone_data)
    if simulation:
        provider = StaticWarningProvider(simulation_warnings(policy))
    else:
        api_key = secret("kma", "api_key", "KMA_API_KEY")
        feed = load_live_feed(api_key, POLICY_PATH.stat().st_mtime)
        provider = FeedWarningProvider(feed)
    service = MonitoringService(
        CsvFacilityRepository(FACILITY_PATH),
        provider,
        OfficialZoneMatcher(zone_index),
        policy,
    )
    return service.get_snapshot(), zone_data, zone_health, zone_message


with st.sidebar:
    st.markdown("### 관제 설정")
    simulation = st.toggle(
        "모의훈련 모드",
        value=False,
        help="실제 KMA 자료 대신 고정 훈련 시나리오를 사용합니다.",
    )
    if st.button("지금 새로고침", width="stretch"):
        load_live_feed.clear()
        load_zones.clear()
        st.rerun()
    st.caption("관제 권역")
    st.write("대구 · 경북 · 부산 · 울산 · 경남")
    st.caption("업무 흐름")
    st.write("조회 범위 설정 → 대상 선택 → 발송·보고서")

try:
    base_policy = load_policy(POLICY_PATH.stat().st_mtime)
    policy, temporary_policy = effective_policy(base_policy)
    snapshot, zone_data, zone_health, zone_message = make_snapshot(simulation, policy)
    catalog = load_facility_groups(GROUP_PATH.stat().st_mtime)
except Exception as exc:
    st.error(f"대시보드를 구성할 수 없습니다: {exc}")
    st.stop()

mode_label = "모의훈련" if simulation else "실시간"
feed_label = {
    DataHealth.LIVE: "정상",
    DataHealth.SIMULATION: "훈련",
    DataHealth.ERROR: "조회 실패",
    DataHealth.FALLBACK: "내장본",
    DataHealth.STALE: "지연",
}[snapshot.warning_feed.health]
feed_failed = snapshot.warning_feed.health is DataHealth.ERROR

st.markdown(
    '<div class="app-kicker">K-ECO SAFETY MONITORING</div>',
    unsafe_allow_html=True,
)
st.markdown('<div class="app-title">기상재난 시설 관제</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="app-subtitle">시설 범위를 정한 뒤 같은 대상으로 알림과 보고서를 만듭니다.</div>',
    unsafe_allow_html=True,
)
st.markdown(
    f'<div class="status-strip">{mode_label} · KMA {feed_label} · 경계 {zone_message} · '
    f'{snapshot.generated_at:%Y-%m-%d %H:%M} 기준 · 정책 {policy.version}</div>',
    unsafe_allow_html=True,
)
if feed_failed:
    st.warning(
        snapshot.warning_feed.message
        or "KMA 자료를 조회하지 못했습니다. API 키와 네트워크를 확인하세요."
    )
if zone_health is DataHealth.FALLBACK:
    st.info("최신 경계를 불러오지 못해 검증된 내장 특보구역을 사용 중입니다.")
if temporary_policy:
    st.warning(
        "임시 위험도 기준 적용 중 · 현재 브라우저 세션의 "
        "지도·지표·Telegram·PDF에만 반영됩니다."
    )

group_counts = catalog.counts(snapshot.facilities)
with st.container(border=True):
    heading_column, policy_column = st.columns((5, 1.35), vertical_alignment="center")
    heading_column.markdown("#### 조회 범위")
    if policy_column.button(
        "위험도 기준 설정",
        width="stretch",
        key="open-risk-policy-editor",
    ):
        policy_editor_dialog(
            base_policy,
            policy,
            snapshot.warning_feed.warnings,
        )

    valid_group_ids = set(catalog.ids)
    applied_group_ids = [
        item
        for item in st.session_state.get("applied_facility_groups", catalog.ids)
        if item in valid_group_ids
    ]
    valid_grades = set(GRADE_ORDER)
    applied_grades = [
        item
        for item in st.session_state.get("applied_risk_grades", GRADE_ORDER)
        if item in valid_grades
    ]
    st.session_state["applied_facility_groups"] = applied_group_ids
    st.session_state["applied_risk_grades"] = applied_grades

    with st.form("scope-filter-form", border=False):
        draft_group_ids = st.pills(
            "시설 유형",
            options=list(catalog.ids),
            default=applied_group_ids,
            selection_mode="multi",
            format_func=lambda value: (
                f"{catalog.definition(value).label} {group_counts[value]}"
            ),
            key="facility-group-filter-draft",
            width="stretch",
        )
        draft_grades = st.pills(
            "지도 표시 등급",
            options=list(GRADE_ORDER),
            default=applied_grades,
            selection_mode="multi",
            format_func=grade_label,
            key="risk-grade-filter-draft",
            width="stretch",
        )
        apply_scope = st.form_submit_button(
            "조회 범위 적용",
            type="primary",
            width="stretch",
        )
    if apply_scope:
        st.session_state["applied_facility_groups"] = list(draft_group_ids or [])
        st.session_state["applied_risk_grades"] = list(draft_grades or [])
        st.rerun()

selected_group_ids = list(st.session_state["applied_facility_groups"])
selected_grades = list(st.session_state["applied_risk_grades"])
if not selected_group_ids or not selected_grades:
    st.info("시설 유형과 위험도를 하나 이상 선택하면 조회 결과가 표시됩니다.")
filtered_snapshot = filter_snapshot(
    snapshot,
    catalog,
    selected_group_ids,
    selected_grades,
)
scope_label = make_scope_label(catalog, selected_group_ids, selected_grades)
scope_key = scope_fingerprint(
    snapshot,
    simulation,
    selected_group_ids,
    selected_grades,
    configuration_revision=(
        f"{POLICY_PATH.stat().st_mtime_ns}:{GROUP_PATH.stat().st_mtime_ns}"
    ),
)
if st.session_state.get("active_scope_key") != scope_key:
    st.session_state["active_scope_key"] = scope_key
    st.session_state.pop("report_pdf", None)
    st.session_state.pop("report_name", None)
    st.session_state.pop("report_fingerprint", None)

metric_columns = st.columns(3)
with metric_columns[0]:
    render_metric(
        "영향 특보",
        "—" if feed_failed else filtered_snapshot.summary.active_warning_count,
        "조회 실패" if feed_failed else "현재 표시 시설에 연결",
    )
with metric_columns[1]:
    render_metric(
        "영향 시설",
        "—" if feed_failed else filtered_snapshot.summary.affected_facility_count,
        "판정 중단" if feed_failed else f"표시 시설 {len(filtered_snapshot.facilities)}개 중",
    )
with metric_columns[2]:
    note = (
        f"미판정 {filtered_snapshot.summary.unassessed_count}개"
        if filtered_snapshot.summary.unassessed_count
        else "즉시 확인 우선순위"
    )
    render_metric(
        "상 위험",
        "—" if feed_failed else filtered_snapshot.summary.high_risk_count,
        "판정 중단" if feed_failed else note,
    )

filtered_affected = sorted(
    (
        item
        for item in filtered_snapshot.assessments
        if item.grade is not RiskGrade.NONE
    ),
    key=lambda item: (GRADE_RANK[item.grade], item.facility.name),
)

map_column, detail_column = st.columns((1.65, 1), gap="large")
with map_column:
    st.markdown("#### 특보와 시설 위치")
    st.caption(f"현재 범위 · {scope_label}")
    st_folium(
        build_monitoring_map(filtered_snapshot, zone_data),
        use_container_width=True,
        height=620,
        returned_objects=[],
        key=f"monitoring-map-{scope_key}",
    )

with detail_column:
    st.markdown("#### 확인 우선순위")
    if not filtered_affected:
        if feed_failed:
            st.error("KMA 조회 실패로 확인 우선순위를 계산하지 못했습니다.")
        else:
            st.success("현재 조회 범위에 특보 영향 시설이 없습니다.")
    else:
        detail_id = st.selectbox(
            "상세 시설",
            options=[item.facility.id for item in filtered_affected],
            format_func=lambda value: next(
                f"[{grade_label(item.grade)}] {item.facility.name}"
                for item in filtered_affected
                if item.facility.id == value
            ),
            label_visibility="collapsed",
            key=f"facility-detail-{scope_key}",
        )
        detail = next(
            item for item in filtered_affected if item.facility.id == detail_id
        )
        definition = policy.definition(detail.grade)
        reasons = html.escape(
            " · ".join(
                dict.fromkeys(
                    f"{item.warning_type} {item.raw_level} ({item.region})"
                    for item in detail.reasons
                )
            )
            or "정책 확인 필요"
        )
        st.markdown(
            f'<div class="detail-card"><span class="grade-pill" '
            f'style="background:{COLORS[detail.grade]}">{html.escape(definition.label)}</span> '
            f'<b>{html.escape(detail.facility.name)}</b><br><br>'
            f'<b>판정 근거</b><br>{reasons}<br><br>'
            f'<b>권장 행동</b><br>{html.escape(definition.action)}<br><br>'
            f'<b>담당</b> {html.escape(detail.facility.manager)}<br>'
            f'<b>주소</b> {html.escape(detail.facility.address)}</div>',
            unsafe_allow_html=True,
        )

st.markdown("#### 후속 작업 대상")
st.caption(
    "포함 여부를 여러 개 수정한 뒤 작업 버튼을 누르면 한 번에 반영됩니다. "
    "Telegram과 PDF는 이 표에서 체크한 시설과 연결 특보만 사용합니다."
)
if not filtered_affected:
    if feed_failed:
        st.error("KMA 조회 실패로 후속 작업 대상 선정을 중단했습니다.")
    else:
        st.success("현재 조회 범위에서 선택할 영향 시설이 없습니다.")
    with st.form(f"empty-target-form-{scope_key}", border=False):
        empty_action_columns = st.columns(4)
        empty_action_columns[0].form_submit_button(
            "전체 선택",
            disabled=True,
            width="stretch",
        )
        empty_action_columns[1].form_submit_button(
            "전체 해제",
            disabled=True,
            width="stretch",
        )
        empty_telegram = empty_action_columns[2].form_submit_button(
            "Telegram 발송",
            type="primary",
            disabled=feed_failed,
            width="stretch",
        )
        empty_report = empty_action_columns[3].form_submit_button(
            "PDF 보고서",
            disabled=feed_failed,
            width="stretch",
        )
    if feed_failed:
        st.caption("KMA 조회 실패 상태에서는 발송과 보고서를 사용할 수 없습니다.")
    elif empty_telegram or empty_report:
        st.warning(
            "작업 대상이 없습니다. 영향 시설이 있는 조회 범위를 "
            "적용한 뒤 다시 실행해 주세요."
        )
else:
    available_target_ids = [item.facility.id for item in filtered_affected]
    target_state_key = f"target-selection-{scope_key}"
    target_revision_key = f"target-revision-{scope_key}"
    if target_state_key not in st.session_state:
        st.session_state[target_state_key] = available_target_ids
    else:
        available_set = set(available_target_ids)
        st.session_state[target_state_key] = [
            item
            for item in st.session_state[target_state_key]
            if item in available_set
        ]
    target_revision = int(st.session_state.get(target_revision_key, 0))
    stored_target_ids = set(st.session_state[target_state_key])

    with st.form(f"target-form-{scope_key}-{target_revision}", border=False):
        target_rows = pd.DataFrame(
            [
                {
                    "포함": item.facility.id in stored_target_ids,
                    "시설 ID": item.facility.id,
                    "등급": grade_label(item.grade),
                    "시설": item.facility.name,
                    "유형": catalog.group_for_type(item.facility.facility_type).label,
                    "특보": warning_text(item),
                    "담당자": item.facility.manager,
                }
                for item in filtered_affected
            ]
        )
        edited_targets = st.data_editor(
            target_rows,
            hide_index=True,
            width="stretch",
            height=460,
            column_order=("포함", "등급", "시설", "유형", "특보", "담당자"),
            column_config={
                "포함": st.column_config.CheckboxColumn("포함", width="small"),
                "등급": st.column_config.TextColumn("등급", width="small"),
                "시설": st.column_config.TextColumn("시설", width="medium"),
                "유형": st.column_config.TextColumn("유형", width="medium"),
                "특보": st.column_config.TextColumn("특보", width="large"),
                "담당자": st.column_config.TextColumn("담당자", width="medium"),
            },
            disabled=("시설 ID", "등급", "시설", "유형", "특보", "담당자"),
            key=f"target-editor-{scope_key}-{target_revision}",
        )
        action_columns = st.columns(4)
        select_all_clicked = action_columns[0].form_submit_button(
            "전체 선택",
            width="stretch",
        )
        select_none_clicked = action_columns[1].form_submit_button(
            "전체 해제",
            width="stretch",
        )
        telegram_clicked = action_columns[2].form_submit_button(
            "Telegram 발송",
            type="primary",
            disabled=feed_failed,
            width="stretch",
        )
        report_clicked = action_columns[3].form_submit_button(
            "PDF 보고서",
            disabled=feed_failed,
            width="stretch",
        )

    if feed_failed:
        st.caption("KMA 조회 실패 상태에서는 발송과 보고서를 사용할 수 없습니다.")
    if select_all_clicked or select_none_clicked:
        st.session_state[target_state_key] = (
            available_target_ids if select_all_clicked else []
        )
        st.session_state[target_revision_key] = target_revision + 1
        st.rerun()
    if telegram_clicked or report_clicked:
        selected_target_ids = (
            edited_targets.loc[edited_targets["포함"], "시설 ID"]
            .astype(str)
            .tolist()
        )
        st.session_state[target_state_key] = selected_target_ids
        if not selected_target_ids:
            st.warning(
                "작업 대상이 없습니다. 시설을 하나 이상 체크한 뒤 "
                "다시 실행해 주세요."
            )
        else:
            selected_snapshot = action_snapshot(
                filtered_snapshot,
                selected_target_ids,
            )
            fingerprint = action_fingerprint(scope_key, selected_target_ids)
            if st.session_state.get("report_fingerprint") not in (
                None,
                fingerprint,
            ):
                st.session_state.pop("report_pdf", None)
                st.session_state.pop("report_name", None)
                st.session_state.pop("report_fingerprint", None)
            if telegram_clicked:
                telegram_dialog(
                    selected_snapshot,
                    scope_label,
                    fingerprint,
                    simulation,
                    secret("telegram", "bot_token", "TELEGRAM_BOT_TOKEN"),
                    secret("telegram", "chat_id", "TELEGRAM_CHAT_ID"),
                    temporary_policy=temporary_policy,
                )
            else:
                report_dialog(
                    selected_snapshot,
                    scope_label,
                    fingerprint,
                    FONT_PATH,
                    temporary_policy=temporary_policy,
                )

with st.expander("현재 조회 범위의 특보 원문"):
    warning_rows = [
        {
            "광역": item.region_up,
            "구역": item.region,
            "종류": item.warning_type,
            "단계": item.raw_level,
            "발표": item.issued_at,
            "발효": item.effective_at,
        }
        for item in filtered_snapshot.warning_feed.warnings
    ]
    st.dataframe(
        pd.DataFrame(
            warning_rows,
            columns=("광역", "구역", "종류", "단계", "발표", "발효"),
        ),
        hide_index=True,
        width="stretch",
    )
