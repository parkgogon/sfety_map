"""상황·대응 중심의 스마트 기상·재난 관제 대시보드 v2."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

import telegram_utils
from core.region_resolver import (
    KMA_WARNING_SCOPE_PREFIXES,
    WarningZoneIndex,
    warning_level_rank,
)
from data_providers.kma_provider import (
    KMAProvider,
    SIMULATION_WARNINGS,
    SIMULATION_WEATHER,
)
from report_generator import generate_html_report, generate_pdf_report
from services.dashboard_service import (
    FacilityDataError,
    assess_dashboard,
    build_telegram_messages,
    load_facilities,
    make_warning_snapshot,
    matched_warning_rows,
)
from ui.components import (
    render_action_cards,
    render_alert_summary,
    render_facility_metadata,
    render_header,
    render_section_heading,
    render_status_cards,
    render_weather_cards,
)
from ui.map_view import build_map
from ui.theme import THEME_CSS


BASE_DIR = Path(__file__).resolve().parent
FACILITY_FILE = BASE_DIR / "facilities_info.csv"
BOUNDARY_FALLBACK_FILE = BASE_DIR / "data" / "kma_warning_zones.geojson.gz"


st.set_page_config(
    page_title="스마트 기상·재난 관제",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.markdown(THEME_CSS, unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def load_facility_data(path: str, modified_at: float) -> pd.DataFrame:
    del modified_at
    return load_facilities(path)


@st.cache_data(ttl=600, show_spinner=False)
def load_weather(lat: float, lon: float) -> dict[str, str]:
    return KMAProvider().get_weather_at(lat, lon)


def open_report_panel() -> None:
    st.session_state["side_view"] = "보고서"


def clear_live_caches() -> None:
    KMAProvider._fetch_warnings.clear()
    KMAProvider._fetch_warning_zones.clear()
    KMAProvider.get_grid_coordinates.clear()
    load_weather.clear()


kma = KMAProvider()

try:
    facility_df = load_facility_data(
        str(FACILITY_FILE),
        FACILITY_FILE.stat().st_mtime,
    )
    boundary_data, boundary_status, boundary_note = kma.get_warning_zones(
        BOUNDARY_FALLBACK_FILE,
        KMA_WARNING_SCOPE_PREFIXES,
    )
    zone_index = WarningZoneIndex.from_geojson(boundary_data)
except (FacilityDataError, OSError, ValueError) as exc:
    st.error(f"대시보드 초기화 실패: {exc}")
    st.stop()


# ── 헤더와 전역 제어 ──────────────────────────────────────────────
header_main, header_controls = st.columns(
    [3.4, 1.25],
    gap="large",
    vertical_alignment="top",
)
with header_main:
    render_header()

with header_controls:
    sim_mode = st.toggle(
        "모의훈련 모드",
        value=False,
        help="실제 특보 대신 검증용 재난 시나리오를 사용합니다.",
    )
    with st.container(key="header-actions"):
        refresh_col, report_col = st.columns(2)
        refresh_requested = refresh_col.button(
            "새로고침",
            width="stretch",
            help="기상청 캐시를 비우고 최신 데이터를 조회합니다.",
        )
        report_col.button(
            "보고서",
            width="stretch",
            type="primary",
            on_click=open_report_panel,
        )

if refresh_requested:
    clear_live_caches()
    st.rerun()


# ── 특보 수집 및 위험도 산정 ───────────────────────────────────────
if sim_mode:
    warning_df = SIMULATION_WARNINGS.copy()
    warning_df.attrs.update(
        {
            "fetch_status": "ok",
            "fetch_message": "모의훈련 데이터",
            "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
        }
    )
else:
    warning_df = kma.get_warnings(
        region_code_prefixes=KMA_WARNING_SCOPE_PREFIXES,
    )

snapshot = make_warning_snapshot(warning_df)
_result_df, grade_groups, affected_df = assess_dashboard(
    facility_df,
    snapshot.warnings,
    zone_index,
)

highest_level = ""
if not warning_df.empty:
    highest_level = max(
        warning_df["level"].astype(str),
        key=warning_level_rank,
    )

fetched_note = (
    "모의훈련 데이터"
    if sim_mode
    else snapshot.fetched_at.strftime("%H:%M 기준")
)

if sim_mode:
    st.warning("모의훈련 모드입니다. 화면의 특보와 점검 대상은 실제 상황이 아닙니다.")
elif snapshot.status != "ok":
    st.error(
        snapshot.message
        or "기상청 데이터를 확인할 수 없습니다. 마지막 수신 상태를 점검해 주세요."
    )

render_status_cards(
    warning_count=len(warning_df),
    highest_level=highest_level,
    affected_count=len(affected_df),
    urgent_count=len(grade_groups.get("상", [])),
    source_status=snapshot.status,
    fetched_note=fetched_note,
)
if snapshot.status == "ok":
    render_alert_summary(warning_df)


# ── 지도 필터 ─────────────────────────────────────────────────────
facility_categories = sorted(
    facility_df["시설구분"].dropna().astype(str).unique().tolist()
)
warning_types = sorted(
    warning_df["type"].dropna().astype(str).unique().tolist()
) if not warning_df.empty else []

with st.container(border=True):
    filter_button_col, search_col, scope_col = st.columns(
        [1.0, 2.4, 1.15],
        vertical_alignment="center",
    )
    with filter_button_col:
        with st.popover("지도 필터", width="stretch"):
            selected_categories = st.multiselect(
                "시설 유형",
                facility_categories,
                default=facility_categories,
                key="facility_category_filter",
            )
            selected_warning_types = st.multiselect(
                "특보 유형",
                warning_types,
                default=warning_types,
                key="warning_type_filter",
            )
    with search_col:
        facility_search = st.text_input(
            "시설 검색",
            placeholder="시설명 또는 주소 검색",
            label_visibility="collapsed",
        )
    with scope_col:
        st.caption(
            f"지도 시설 {len(facility_df):,}개 · 특보 {len(warning_df):,}건"
        )

map_facilities = facility_df[
    facility_df["시설구분"].astype(str).isin(selected_categories)
].copy()
if facility_search.strip():
    keyword = facility_search.strip()
    map_facilities = map_facilities[
        map_facilities["name"].astype(str).str.contains(keyword, case=False, na=False)
        | map_facilities["address"].astype(str).str.contains(
            keyword,
            case=False,
            na=False,
        )
    ]

map_warnings = warning_df[
    warning_df["type"].astype(str).isin(selected_warning_types)
].copy() if not warning_df.empty else warning_df


# ── 지도와 대응 패널 ───────────────────────────────────────────────
map_column, side_column = st.columns(
    [1.65, 1],
    gap="large",
    vertical_alignment="top",
)

with map_column:
    render_section_heading(
        "통합 관제 지도",
        f"시설 {len(map_facilities)}개 표시",
    )
    map_object = build_map(map_facilities, map_warnings, boundary_data)
    st_folium(
        map_object,
        width="100%",
        height=620,
        returned_objects=[],
        key="operations_map",
    )
    if boundary_status == "fallback":
        st.caption(f"지도 경계: {boundary_note} · 최신본 연결 시 자동 갱신")

with side_column:
    if "side_view" not in st.session_state:
        st.session_state["side_view"] = "대응 현황"

    side_view = st.segmented_control(
        "업무 패널",
        ["대응 현황", "시설 상세", "보고서"],
        key="side_view",
        label_visibility="collapsed",
        width="stretch",
    )

    if side_view == "대응 현황":
        render_section_heading(
            "점검 우선순위",
            f"영향 시설 {len(affected_df)}개",
        )
        render_action_cards(affected_df)

        if not affected_df.empty:
            if st.button(
                "텔레그램 점검 요청 발송",
                type="primary",
                width="stretch",
            ):
                try:
                    token = st.secrets["telegram"]["bot_token"]
                    chat_id = st.secrets["telegram"]["chat_id"]
                    messages = build_telegram_messages(affected_df)
                    result = telegram_utils.send_telegram_alert_batch(
                        token,
                        chat_id,
                        messages,
                    )
                    if result.success:
                        st.success(result.message)
                    else:
                        st.error(result.message)
                except (KeyError, TypeError, FileNotFoundError):
                    st.error("텔레그램 설정이 없습니다. secrets.toml을 확인해 주세요.")

            with st.expander("전체 점검 대상 보기"):
                target_table = affected_df[
                    [
                        "facility_name",
                        "grade",
                        "facility_type",
                        "manager",
                        "address",
                    ]
                ].rename(
                    columns={
                        "facility_name": "시설명",
                        "grade": "등급",
                        "facility_type": "시설유형",
                        "manager": "담당자",
                        "address": "주소",
                    }
                )
                st.dataframe(
                    target_table,
                    hide_index=True,
                    width="stretch",
                )

    elif side_view == "시설 상세":
        render_section_heading("시설 상세", "기상 실황 · 담당자")
        detail_source = map_facilities if not map_facilities.empty else facility_df
        selected_name = st.selectbox(
            "시설 선택",
            detail_source["name"].astype(str).tolist(),
        )
        facility = facility_df[facility_df["name"] == selected_name].iloc[0]

        st.markdown(f"**{facility['name']}**")
        st.caption(str(facility["address"]))
        render_facility_metadata(
            facility.get("부서 담당자", "-"),
            facility.get("시설구분", "-"),
        )

        facility_warnings = matched_warning_rows(
            facility,
            warning_df,
            zone_index,
        )
        if facility_warnings.empty:
            st.success("현재 이 시설에 매칭된 특보가 없습니다.")
        else:
            warning_label = " · ".join(
                f"{row['type']} {row['level']}"
                for _, row in facility_warnings.iterrows()
            )
            st.warning(warning_label)

        if sim_mode:
            weather = SIMULATION_WEATHER
        else:
            with st.spinner("시설 주변 기상 실황 조회 중..."):
                weather = load_weather(
                    float(facility["latitude"]),
                    float(facility["longitude"]),
                )
        render_weather_cards(weather)
        if weather.get("_status") == "error":
            st.caption("기상 실황을 불러오지 못했습니다.")

    else:
        render_section_heading("영향 분석 보고서", "HTML · PDF")
        st.write(
            "현재 특보와 시설 위험도를 기준으로 배포 가능한 보고서를 생성합니다."
        )
        report_metric_a, report_metric_b = st.columns(2)
        report_metric_a.metric("영향 시설", f"{len(affected_df)}개")
        report_metric_b.metric(
            "상 등급",
            f"{len(grade_groups.get('상', []))}개",
        )

        generate_requested = st.button(
            "보고서 생성",
            type="primary",
            width="stretch",
            disabled=snapshot.status != "ok",
        )

        warning_signature = "|".join(
            warning_df.astype(str).agg(":".join, axis=1).tolist()
        )
        report_context = f"{sim_mode}:{warning_signature}"
        existing_report = st.session_state.get("report_payload")
        if existing_report and existing_report.get("context") != report_context:
            st.session_state.pop("report_payload", None)
            existing_report = None

        if generate_requested:
            weather_map: dict[str, dict] = {}
            with st.spinner("시설 영향과 기상 실황을 분석하고 있습니다..."):
                for facility_record in affected_df.head(10).to_dict("records"):
                    name = str(facility_record.get("facility_name", ""))
                    if not name:
                        continue
                    weather_map[name] = (
                        SIMULATION_WEATHER
                        if sim_mode
                        else load_weather(
                            float(facility_record["latitude"]),
                            float(facility_record["longitude"]),
                        )
                    )

                html_report = generate_html_report(
                    warning_df,
                    grade_groups,
                    weather_map,
                )
                pdf_report = generate_pdf_report(
                    warning_df,
                    grade_groups,
                    weather_map,
                )
                st.session_state["report_payload"] = {
                    "context": report_context,
                    "html": html_report,
                    "pdf": bytes(pdf_report) if pdf_report else None,
                    "created_at": dt.datetime.now(),
                }
                existing_report = st.session_state["report_payload"]

        if existing_report:
            created_at = existing_report["created_at"].strftime("%H:%M")
            st.success(f"{created_at}에 보고서를 생성했습니다.")
            if existing_report.get("pdf"):
                st.download_button(
                    "PDF 다운로드",
                    data=existing_report["pdf"],
                    file_name=(
                        "기상재난_시설영향분석_"
                        f"{dt.datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
                    ),
                    mime="application/pdf",
                    width="stretch",
                )


report_payload = st.session_state.get("report_payload")
if side_view == "보고서" and report_payload:
    st.divider()
    render_section_heading("보고서 미리보기", "화면 확인용")
    st.html(report_payload["html"])
