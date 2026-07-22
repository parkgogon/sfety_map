import streamlit as st
import pandas as pd
import datetime
import os
import math

import folium
from streamlit_folium import st_folium

# ==========================================
# 모듈 import (리팩토링된 구조)
# ==========================================
from data_providers import register_provider, get_all_warnings
from data_providers.kma_provider import (
    KMAProvider,
    SIMULATION_WARNINGS,
    SIMULATION_WEATHER,
    SIM_ZONES,
    CENTER_LAT,
    CENTER_LON,
)
from risk_engine import assess_all_facilities
from report_generator import generate_html_report, generate_pdf_report

# ==========================================
# 1. 전역 설정 및 초기화
# ==========================================
st.set_page_config(page_title="스마트 기상·재난 관제 대시보드", layout="wide", page_icon="📡")

# 데이터 프로바이더 등록 (최초 1회)
if "providers_registered" not in st.session_state:
    register_provider(KMAProvider())
    # 향후 추가 데이터 소스:
    # register_provider(FloodProvider())
    # register_provider(ForestProvider())
    st.session_state["providers_registered"] = True

kma = KMAProvider()

st.markdown("""
    <style>
        .ticker {
            background-color: #ff4b4b;
            color: white;
            padding: 10px;
            font-weight: bold;
            font-size: 16px;
            border-radius: 5px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .header-title {
            color: #1f77b4;
            font-weight: 800;
        }
    </style>
""", unsafe_allow_html=True)


# ==========================================
# 2. 시설물 데이터 로딩 (캐싱)
# ==========================================
@st.cache_data(show_spinner=False)
def load_facility_csv():
    """사용자가 작성한 시설 상세 정보 CSV 파일을 직접 로드합니다."""
    user_file = "facilities_info.csv"
    if os.path.exists(user_file):
        try:
            cached_df = pd.read_csv(user_file, encoding='utf-8-sig')
            cached_df['latitude'] = pd.to_numeric(cached_df['latitude'], errors='coerce').fillna(35.8714)
            cached_df['longitude'] = pd.to_numeric(cached_df['longitude'], errors='coerce').fillna(128.6014)
            return cached_df
        except Exception:
            st.error("시설물 정보 파일 로딩 중 오류가 발생했습니다.")
            st.stop()
    else:
        st.error("시설물 참조 파일(facilities_info.csv)이 없습니다.")
        st.stop()


# ==========================================
# 3. 데이터 로딩 및 사전 처리
# ==========================================
col_title, col_sim = st.columns([3, 1])
with col_title:
    st.title("🛡️ 한국환경공단 스마트 기상·재난 관제 대시보드")
    st.markdown("대구경북환경본부 소관시설 통합 안전관리 체계 (AI 기반 관제 MVP)")
with col_sim:
    st.markdown("<br><br>", unsafe_allow_html=True)
    sim_mode = st.toggle("🚨 모의 재난 시뮬레이션 모드", value=False, help="클릭 시 극한 기상(호우, 태풍) 모의 상황을 연출합니다.")

# 1) 소관 시설 로딩
facility_df = load_facility_csv()

# 2) 전역 기상 특보 데이터 로딩 (시뮬레이션 모드 지원)
if sim_mode:
    warn_df = SIMULATION_WARNINGS.copy()
else:
    warn_df = get_all_warnings(region_filter="대구|경북|경상북도")
    # get_all_warnings가 이미 필터링하지 않으므로 여기서 전체를 받고 아래서 필터링
    if warn_df.empty:
        # 단독 KMA 프로바이더 직접 호출 (fallback)
        warn_df = kma.get_warnings()

# ==========================================
# 패널 2: [좌측 상단] 실시간 재난·특보 알림 티커
# ==========================================
# 경북/대구 지역에 해당되는 특보만 필터링
daegu_gyeongbuk_warn = []
if not warn_df.empty:
    dg_df = warn_df[warn_df['region_up'].str.contains('대구|경북|경상북도', na=False)]
    for _, row in dg_df.iterrows():
        daegu_gyeongbuk_warn.append(f"🚨 [{row['region']}] {row['type']} {row['level']} 발효 중")
else:
    dg_df = pd.DataFrame()

if daegu_gyeongbuk_warn:
    marquee_text = " &nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp; ".join(daegu_gyeongbuk_warn)
    st.markdown(f'<div class="ticker"><marquee>{marquee_text}</marquee></div>', unsafe_allow_html=True)
else:
    st.info("✅ 현재 대구/경북 지역에 발효 중인 기상 특보가 없습니다.")


st.markdown("---")


# ==========================================
# 메인 레이아웃 구성: 좌측(지도) / 우측(날씨 모니터링 & 점검 목록)
# ==========================================
col_map, col_details = st.columns([1.6, 1])

# 필터 위젯을 우측 컬럼(col_details) 상단에 배치
if '시설구분' in facility_df.columns:
    categories = facility_df['시설구분'].dropna().unique().tolist()
    selected_categories = col_details.multiselect("🛠️ 지도에 표출할 시설 카테고리 필터링:", categories, default=categories)
    filtered_facility_df = facility_df[facility_df['시설구분'].isin(selected_categories)]
else:
    filtered_facility_df = facility_df

# ------------------------------------------
# 패널 1: 중앙 메인 화면 (실시간 기상특보 및 소관시설 통합 맵)
# ------------------------------------------
with col_map:
    st.subheader("🗺️ 실시간 재난 특보 레이어 & 소관시설 위치")

    # 지도 상태 관리 (줌/센터 유지)
    if "map_center" not in st.session_state:
        st.session_state["map_center"] = [CENTER_LAT, CENTER_LON]
    if "map_zoom" not in st.session_state:
        st.session_state["map_zoom"] = 8

    m = folium.Map(
        location=st.session_state["map_center"],
        zoom_start=st.session_state["map_zoom"],
        tiles="CartoDB positron",
    )

    # 기상청 특보이미지 오버레이
    wrn_img_url = kma.get_warning_image_url()
    bounds = kma.get_image_bounds()

    folium.raster_layers.ImageOverlay(
        image=wrn_img_url,
        bounds=bounds,
        opacity=0.55,
        name="KMA 기상특보 구역"
    ).add_to(m)

    if sim_mode:
        for zone in SIM_ZONES:
            folium.Circle(
                location=[zone["lat"], zone["lon"]],
                radius=15000,
                color=zone["color"],
                fill=True,
                fill_color=zone["color"],
                fill_opacity=0.4,
                tooltip=f"🚨 모의 재난 구역: {zone['region']}"
            ).add_to(m)

    # 소관시설 마커 추가 (카테고리별 색상 부여)
    colors = ['red', 'blue', 'green', 'purple', 'orange', 'darkred', 'beige', 'darkblue', 'darkgreen', 'cadetblue', 'darkpurple', 'pink', 'lightblue', 'lightgreen', 'gray', 'black']
    cats = facility_df['시설구분'].dropna().unique().tolist() if '시설구분' in facility_df.columns else []
    color_map = {cat: colors[i % len(colors)] for i, cat in enumerate(cats)}

    for idx, row in filtered_facility_df.iterrows():
        cat = row.get('시설구분', '')
        color = color_map.get(cat, 'blue')
        dept = row.get('담당부서', '-')
        manager = row.get('부서 담당자', '-')
        code = row.get('시설코드', '-')
        note = row.get('비고', '-')

        popup_html = f"""
        <div style="font-family: Arial, sans-serif; font-size:13px; line-height:1.6; min-width: 250px;">
            <h4 style="margin:0; color:#1f77b4;">{row['name']}</h4>
            <hr style="margin:5px 0;">
            <b>시설구분:</b> {cat}<br>
            <b>담당부서:</b> {dept}<br>
            <b>부서담당자:</b> {manager}<br>
            <b>시설코드:</b> {code}<br>
            <b>기타비고:</b> {note}<br>
            <hr style="margin:5px 0;">
            <span style="font-size:11px; color:#555;">📍 {row['address']}</span>
        </div>
        """
        folium.Marker(
            location=[row['latitude'], row['longitude']],
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=f"{row['name']} ({cat})",
            icon=folium.Icon(color=color, icon='info-sign')
        ).add_to(m)

    # ★ 핵심 수정: returned_objects=[]로 지도 이벤트가 Streamlit rerun을 유발하지 않도록 차단
    st_folium(m, width="100%", height=800, returned_objects=[])

# ------------------------------------------
# 상세 패널 (패널 3 & 패널 4)
# ------------------------------------------
with col_details:
    # 패널 3: [우측 상단 패널] 고위험 시설 맞춤형 초단기 날씨 실황
    st.subheader("🌤️ 시설 주변 초단기 날씨 실황")
    if filtered_facility_df.empty:
        facility_options = []
    else:
        facility_options = filtered_facility_df['name'].tolist()

    selected_facility = st.selectbox("정밀 관제할 시설을 선택하세요:", facility_options)

    # 선택된 시설의 좌표 조회
    f_info = facility_df[facility_df['name'] == selected_facility].iloc[0]
    st.caption(f"📍 위치: {f_info['address']} (위도: {f_info['latitude']:.4f}, 경도: {f_info['longitude']:.4f})")

    # 좌표 -> KMA 격자 변환 및 날씨 호출 (시뮬레이션 모드 지원)
    if sim_mode:
        weather_now = SIMULATION_WEATHER
        w_col1, w_col2, w_col3, w_col4 = st.columns(4)
        w_col1.metric("기온", f"{weather_now['기온(℃)']} ℃", delta="1.2 ℃")
        w_col2.metric("강수량 (1h)", f"{weather_now['1시간강수량(mm)']} mm", delta="55.0 mm", delta_color="inverse")
        w_col3.metric("풍향", f"{weather_now['풍향(deg)']} 도")
        w_col4.metric("풍속", f"{weather_now['풍속(m/s)']} m/s", delta="15.5 m/s", delta_color="inverse")
    else:
        weather_now = kma.get_weather_at(f_info['latitude'], f_info['longitude'])
        w_col1, w_col2, w_col3, w_col4 = st.columns(4)
        w_col1.metric("기온", f"{weather_now['기온(℃)']} ℃")
        w_col2.metric("강수량 (1h)", f"{weather_now['1시간강수량(mm)']} mm")
        w_col3.metric("풍향", f"{weather_now['풍향(deg)']} 도")
        w_col4.metric("풍속", f"{weather_now['풍속(m/s)']} m/s")

    st.markdown("<br><hr>", unsafe_allow_html=True)

    # 패널 4: [우측 하단 패널] 재난 징후 연동 대상 자동 추출 목록
    st.subheader("⚠️ 재난 징후 연동: 긴급 점검 요망 대상")
    st.write("현재 특보 발효 구역 내에 포함되어 즉각적인 시설 안전 점검이 요구되는 리스트입니다.")

    if warn_df.empty or dg_df.empty:
        st.success("데이터에 감지된 재난 징후가 없어 자동 점검 대상 목록이 없습니다.")
    else:
        # 경북지역 특보 발효 지역의 시군구 키워드 추출
        active_regions = dg_df['region'].unique()

        # 주소에 해당 지역 키워드가 포함되어 있는지 대조
        target_indices = []
        for reg in active_regions:
            # 예천군 -> '예천', 안동시 -> '안동'
            keyword = str(reg).replace("시", "").replace("군", "").replace("구", "")

            for idx, row in filtered_facility_df.iterrows():
                if keyword in str(row['address']):
                    target_indices.append(idx)

        # 중복 제거 후 점검 대상 출력
        target_indices = list(set(target_indices))

        if len(target_indices) > 0:
            target_df = filtered_facility_df.loc[target_indices][['name', '시설구분', '부서 담당자', 'address']]
            st.dataframe(target_df, width="stretch", hide_index=True)
            st.error(f"총 {len(target_df)}개의 선제 점검 대상 시설이 도출되었습니다.")
        else:
            st.success("현재 특보 발효 구역에 위치한 소관시설이 없습니다.")


# ==========================================
# 패널 5: 원페이지 보고서 생성
# ==========================================
st.markdown("---")
st.subheader("📋 기상재난 시설물 영향 분석 보고서")

col_report_btn, col_report_info = st.columns([1, 3])
with col_report_btn:
    generate_report = st.button(
        "📄 보고서 생성",
        type="primary",
        help="현재 발효 중인 특보를 기반으로 시설물 위험도를 분석하고 원페이지 보고서를 생성합니다.",
        use_container_width=True,
    )
with col_report_info:
    st.caption(
        "특보 발효 시 시설물별 위험도(상/중/하)를 자동 산정하여 보고서를 생성합니다. "
        "PDF로 다운로드하여 인쇄 보고가 가능합니다."
    )

if generate_report or st.session_state.get("report_generated", False):
    st.session_state["report_generated"] = True

    # 위험도 산정
    with st.spinner("시설물 위험도를 분석 중입니다..."):
        # 대구/경북 관련 특보 사용
        analysis_warnings = dg_df if not warn_df.empty and not dg_df.empty else warn_df
        result_df, grade_groups = assess_all_facilities(facility_df, analysis_warnings)

    total_affected = sum(len(df) for df in grade_groups.values())

    if total_affected == 0:
        st.info("현재 발효 중인 특보에 영향 받는 소관시설이 없습니다. 시뮬레이션 모드를 활성화하면 모의 보고서를 확인할 수 있습니다.")
    else:
        # 영향권 시설 기상 실황 수집
        weather_data_map = {}
        affected_facilities = []
        for grade in ["상", "중", "하"]:
            gdf = grade_groups.get(grade)
            if gdf is not None:
                affected_facilities.extend(gdf.to_dict("records"))

        # 상위 10개 시설만 기상 실황 조회 (API 부하 관리)
        with st.spinner("영향권 시설 기상 실황을 조회 중입니다..."):
            for fac in affected_facilities[:10]:
                lat = fac.get("latitude", 0)
                lon = fac.get("longitude", 0)
                name = fac.get("facility_name", "")
                if lat and lon and name:
                    if sim_mode:
                        weather_data_map[name] = SIMULATION_WEATHER
                    else:
                        weather_data_map[name] = kma.get_weather_at(lat, lon)

        # HTML 미리보기
        html_report = generate_html_report(analysis_warnings, grade_groups, weather_data_map)
        st.html(html_report)

        # PDF 다운로드 버튼
        st.markdown("<br>", unsafe_allow_html=True)
        pdf_bytes = generate_pdf_report(analysis_warnings, grade_groups, weather_data_map)
        if pdf_bytes:
            now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M")
            st.download_button(
                label="📥 PDF 보고서 다운로드",
                data=bytes(pdf_bytes),
                file_name=f"기상재난_시설영향분석_{now_str}.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True,
            )
        else:
            st.warning("PDF 생성 라이브러리(fpdf2)가 설치되지 않았습니다. `pip install fpdf2`를 실행해주세요.")
