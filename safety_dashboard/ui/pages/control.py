"""중앙 관제 담당자용 일괄 조회·전파 페이지."""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from safety_dashboard.application.contacts import public_contact
from safety_dashboard.application.selection import action_snapshot, filter_snapshot
from safety_dashboard.domain.enums import DataHealth, RiskGrade
from safety_dashboard.ui.dialogs import report_dialog, telegram_dialog
from safety_dashboard.ui.alert_metrics import render_alert_metrics
from safety_dashboard.ui.control_overview import render_control_overview
from safety_dashboard.ui.map_view import COLORS, build_monitoring_map
from safety_dashboard.ui.app_context import (
    FONT_PATH,
    GROUP_PATH,
    POLICY_PATH,
    clear_live_caches,
    monitoring_context,
    secret,
)
from safety_dashboard.ui.workflow import (
    GRADE_ORDER,
    GRADE_RANK,
    action_fingerprint,
    grade_label,
    make_scope_label,
    render_metric_grid,
    scope_fingerprint,
    warning_text,
)


_WORKSPACE_DESCRIPTIONS = {
    "운영 상황": "자동 관제 경로와 현재 특보 영향을 한눈에 확인합니다.",
    "대상 분석·전파": "영향시설을 분석하고 PDF 또는 감사형 수동 상황전파를 수행합니다.",
    "실적·이력": "자동·수동 전파 실적과 처리 이력을 분리해 확인합니다.",
}
st.markdown(
    '<div class="app-kicker">K-ECO SAFETY MONITORING</div>',
    unsafe_allow_html=True,
)
st.markdown('<div class="app-title">중앙 관제</div>', unsafe_allow_html=True)
with st.container(key="control-workspace-navigation"):
    workspace = st.segmented_control(
        "중앙 관제 작업 화면",
        options=tuple(_WORKSPACE_DESCRIPTIONS),
        default="운영 상황",
        key="control-workspace",
        label_visibility="collapsed",
        width="stretch",
    ) or "운영 상황"
st.markdown(
    f'<div class="app-subtitle">{html.escape(_WORKSPACE_DESCRIPTIONS[workspace])}</div>',
    unsafe_allow_html=True,
)

if workspace == "운영 상황":
    render_control_overview()
    st.stop()
if workspace == "실적·이력":
    render_alert_metrics(standalone=True)
    st.stop()


with st.sidebar:
    st.markdown("### 관제 설정")
    simulation = st.toggle(
        "모의훈련 모드",
        value=False,
        help="실제 KMA 자료 대신 고정 훈련 시나리오를 사용합니다.",
    )
    if st.button("지금 새로고침", width="stretch"):
        clear_live_caches()
        st.rerun()
    st.caption("관제 권역")
    st.write("대구 · 경북 · 부산 · 울산 · 경남")
    st.caption("업무 흐름")
    st.write("조회 범위 설정 → 대상 선택 → 발송·보고서")

try:
    context = monitoring_context(simulation)
except Exception as exc:
    st.error(f"대시보드를 구성할 수 없습니다: {exc}")
    st.stop()

policy = context.policy
temporary_policy = context.temporary_policy
snapshot = context.snapshot
zone_data = context.zone_data
zone_health = context.zone_health
zone_message = context.zone_message
catalog = context.facility_groups

with st.sidebar:
    st.divider()
    st.markdown("### 정책")
    st.page_link(
        "safety_dashboard/ui/pages/settings.py",
        label="위험도 기준 설정 열기",
        icon=":material/tune:",
        width="stretch",
    )
    st.caption(f"현재 정책 · {policy.version}")

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
    f'<div class="status-strip"><span class="status-primary">'
    f'{html.escape(mode_label)} · KMA {html.escape(feed_label)}</span>'
    f'<span class="status-time-full"> · {snapshot.generated_at:%Y-%m-%d %H:%M} 기준</span>'
    f'<span class="status-time-mobile"> · {snapshot.generated_at:%m-%d %H:%M} 기준</span>'
    f'<span class="status-secondary"> · 경계 {html.escape(zone_message)} '
    f'· 정책 {html.escape(policy.version)}</span></div>',
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

valid_group_ids = set(catalog.ids)
applied_group_ids = [
    item
    for item in st.session_state.get(
        "control_applied_facility_groups", catalog.ids
    )
    if item in valid_group_ids
]
valid_grades = set(GRADE_ORDER)
applied_grades = [
    item
    for item in st.session_state.get("control_applied_risk_grades", GRADE_ORDER)
    if item in valid_grades
]
st.session_state["control_applied_facility_groups"] = applied_group_ids
st.session_state["control_applied_risk_grades"] = applied_grades

group_counts = catalog.counts(snapshot.facilities)
applied_scope_label = make_scope_label(catalog, applied_group_ids, applied_grades)
with st.container(border=True, key="scope-summary"):
    scope_text_column, scope_button_column = st.columns(
        (2.4, 1),
        vertical_alignment="center",
    )
    scope_text_column.markdown(
        '<div class="scope-summary-label">현재 조회 범위</div>'
        f'<div class="scope-summary-value" title="{html.escape(applied_scope_label)}">'
        f'{html.escape(applied_scope_label)}</div>',
        unsafe_allow_html=True,
    )
    with scope_button_column:
        with st.popover(
            "조회 범위 변경",
            icon=":material/filter_alt:",
            width="stretch",
        ):
            st.markdown("#### 조회 범위")
            st.caption("여러 항목을 바꾼 뒤 적용하면 결과를 한 번에 갱신합니다.")
            with st.form("scope-filter-form", border=False):
                group_default = (
                    {}
                    if "control_facility_group_filter_draft" in st.session_state
                    else {"default": applied_group_ids}
                )
                draft_group_ids = st.pills(
                    "시설 유형",
                    options=list(catalog.ids),
                    selection_mode="multi",
                    format_func=lambda value: (
                        f"{catalog.definition(value).label} {group_counts[value]}"
                    ),
                    key="control_facility_group_filter_draft",
                    width="stretch",
                    **group_default,
                )
                grade_default = (
                    {}
                    if "control_risk_grade_filter_draft" in st.session_state
                    else {"default": applied_grades}
                )
                draft_grades = st.pills(
                    "지도 표시 등급",
                    options=list(GRADE_ORDER),
                    selection_mode="multi",
                    format_func=grade_label,
                    key="control_risk_grade_filter_draft",
                    width="stretch",
                    **grade_default,
                )
                apply_scope = st.form_submit_button(
                    "조회 범위 적용",
                    type="primary",
                    width="stretch",
                )
            if apply_scope:
                st.session_state["control_applied_facility_groups"] = list(
                    draft_group_ids or []
                )
                st.session_state["control_applied_risk_grades"] = list(
                    draft_grades or []
                )
                st.rerun()

selected_group_ids = list(st.session_state["control_applied_facility_groups"])
selected_grades = list(st.session_state["control_applied_risk_grades"])
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
if st.session_state.get("control_active_scope_key") != scope_key:
    st.session_state["control_active_scope_key"] = scope_key
    st.session_state.pop("report_pdf", None)
    st.session_state.pop("report_name", None)
    st.session_state.pop("report_fingerprint", None)

note = (
    f"미판정 {filtered_snapshot.summary.unassessed_count}개"
    if filtered_snapshot.summary.unassessed_count
    else "점검 우선순위"
)
render_metric_grid(
    (
        (
            "영향 특보",
            "—" if feed_failed else filtered_snapshot.summary.active_warning_count,
            "조회 실패" if feed_failed else "현재 표시 시설에 연결",
        ),
        (
            "영향 시설",
            "—" if feed_failed else filtered_snapshot.summary.affected_facility_count,
            (
                "판정 중단"
                if feed_failed
                else f"표시 시설 {len(filtered_snapshot.facilities)}개 중"
            ),
        ),
        (
            "상 위험",
            "—" if feed_failed else filtered_snapshot.summary.high_risk_count,
            "판정 중단" if feed_failed else note,
        ),
    )
)

filtered_affected = sorted(
    (
        item
        for item in filtered_snapshot.assessments
        if item.grade is not RiskGrade.NONE
    ),
    key=lambda item: (GRADE_RANK[item.grade], item.facility.name),
)
detail_items = list(filtered_affected)

detail_key = f"control-facility-detail-{scope_key}"
detail_options = [item.facility.id for item in detail_items]
detail = None
if detail_options:
    if st.session_state.get(detail_key) not in detail_options:
        st.session_state[detail_key] = detail_options[0]
    selected_detail_id = st.session_state[detail_key]
    detail = next(
        item for item in detail_items if item.facility.id == selected_detail_id
    )

map_component_key = f"control-monitoring-map-{scope_key}"
map_column, detail_column = st.columns((1.65, 1), gap="large")
with map_column:
    st.markdown("#### 특보와 시설 위치")
    st.caption(f"현재 범위 · {scope_label}")
    st.markdown(
        '<div class="mobile-only mobile-map-help">'
        '한 손가락은 페이지 스크롤입니다. '
        '지도를 움직이려면 지도 안의 조작 버튼을 누르세요.</div>',
        unsafe_allow_html=True,
    )
    with st.container(key="monitoring-map"):
        st_folium(
            build_monitoring_map(
                filtered_snapshot,
                zone_data,
                mobile_initially_locked=True,
            ),
            use_container_width=True,
            height=620,
            returned_objects=[],
            key=map_component_key,
        )

with detail_column:
    st.markdown("#### 점검 우선순위 목록")
    if not detail_items:
        if feed_failed:
            st.error("KMA 조회 실패로 점검 우선순위 목록을 계산하지 못했습니다.")
        else:
            st.success("현재 조회 범위에 특보 영향 시설이 없습니다.")
    else:
        detail_id = st.selectbox(
            "상세 시설",
            options=detail_options,
            format_func=lambda value: next(
                f"[{grade_label(item.grade)}] {item.facility.name}"
                for item in detail_items
                if item.facility.id == value
            ),
            label_visibility="collapsed",
            key=detail_key,
        )
        detail = next(
            item for item in detail_items if item.facility.id == detail_id
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
        with st.expander("시설 상세 정보", expanded=False):
            st.markdown(
                f'<div class="detail-card"><span class="grade-pill" '
                f'style="background:{COLORS[detail.grade]}">{html.escape(definition.label)}</span> '
                f'<b>{html.escape(detail.facility.name)}</b><br><br>'
                f'<b>판정 근거</b><br>{reasons}<br><br>'
                f'<b>권장 행동</b><br>{html.escape(definition.action)}<br><br>'
                f'<b>담당</b> {html.escape(public_contact(detail.facility))}<br>'
                f'<b>주소</b> {html.escape(detail.facility.address)}</div>',
                unsafe_allow_html=True,
            )
        if st.button(
            "현장 지도에서 상세 확인",
            icon=":material/open_in_new:",
            width="stretch",
            key=f"open-field-map-{detail.facility.id}",
        ):
            st.query_params["facility_id"] = detail.facility.id
            st.switch_page("safety_dashboard/ui/pages/field_map.py")

targets_expander = st.expander(
    f"후속 작업 대상 · {len(filtered_affected)}개",
    expanded=False,
)
targets_expander.caption(
    "포함 여부를 여러 개 수정한 뒤 작업 버튼을 누르면 한 번에 반영됩니다. "
    "Telegram과 PDF는 이 표에서 체크한 시설과 연결 특보만 사용합니다."
)
if not filtered_affected:
    if feed_failed:
        targets_expander.error("KMA 조회 실패로 후속 작업 대상 선정을 중단했습니다.")
    else:
        targets_expander.success("현재 조회 범위에서 선택할 영향 시설이 없습니다.")
    with targets_expander.form(f"empty-target-form-{scope_key}", border=False):
        with st.container(key="target-selection-controls"):
            empty_selection_columns = st.columns(2)
            empty_selection_columns[0].form_submit_button(
                "전체 선택",
                disabled=True,
                width="stretch",
            )
            empty_selection_columns[1].form_submit_button(
                "전체 해제",
                disabled=True,
                width="stretch",
            )
        with st.container(key="target-action-controls"):
            empty_action_columns = st.columns(2)
            empty_telegram = empty_action_columns[0].form_submit_button(
                "사용자 채널 수동 전파",
                type="primary",
                disabled=feed_failed,
                width="stretch",
            )
            empty_report = empty_action_columns[1].form_submit_button(
                "PDF 보고서",
                disabled=feed_failed,
                width="stretch",
            )
    if feed_failed:
        targets_expander.caption(
            "KMA 조회 실패 상태에서는 발송과 보고서를 사용할 수 없습니다."
        )
    elif empty_telegram or empty_report:
        targets_expander.warning(
            "작업 대상이 없습니다. 영향 시설이 있는 조회 범위를 "
            "적용한 뒤 다시 실행해 주세요."
        )
else:
    available_target_ids = [item.facility.id for item in filtered_affected]
    target_state_key = f"control-target-selection-{scope_key}"
    target_revision_key = f"control-target-revision-{scope_key}"
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

    with targets_expander.form(
        f"target-form-{scope_key}-{target_revision}",
        border=False,
    ):
        target_rows = pd.DataFrame(
            [
                {
                    "포함": item.facility.id in stored_target_ids,
                    "시설 ID": item.facility.id,
                    "등급": grade_label(item.grade),
                    "시설": item.facility.name,
                    "유형": catalog.group_for_type(item.facility.facility_type).label,
                    "특보": warning_text(item),
                    "담당자": public_contact(item.facility),
                }
                for item in filtered_affected
            ]
        )
        st.markdown(
            '<div class="mobile-only mobile-table-help">'
            '포함·등급·시설을 먼저 확인하고, '
            '나머지 열은 표를 좌우로 밀어 확인하세요.</div>',
            unsafe_allow_html=True,
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
        with st.container(key="target-selection-controls"):
            selection_columns = st.columns(2)
            select_all_clicked = selection_columns[0].form_submit_button(
                "전체 선택",
                width="stretch",
            )
            select_none_clicked = selection_columns[1].form_submit_button(
                "전체 해제",
                width="stretch",
            )
        with st.container(key="target-action-controls"):
            action_columns = st.columns(2)
            telegram_clicked = action_columns[0].form_submit_button(
                "사용자 채널 수동 전파",
                type="primary",
                disabled=feed_failed,
                width="stretch",
            )
            report_clicked = action_columns[1].form_submit_button(
                "PDF 보고서",
                disabled=feed_failed,
                width="stretch",
            )

    if feed_failed:
        targets_expander.caption(
            "KMA 조회 실패 상태에서는 발송과 보고서를 사용할 수 없습니다."
        )
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
            targets_expander.warning(
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
                    secret("alerting", "admin_api_url", "ALERT_ADMIN_API_URL"),
                    secret("alerting", "admin_token", "ALERT_ADMIN_TOKEN"),
                    temporary_policy=temporary_policy,
                    dashboard_base_url=secret(
                        "dashboard",
                        "base_url",
                        "DASHBOARD_BASE_URL",
                    ),
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
