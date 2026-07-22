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
    st.subheader("🗺️ 실시간 특보 현황 & 소관시설 위치")

    # 지도 상태 관리 (줌/센터 유지)
    if "map_center" not in st.session_state:
        st.session_state["map_center"] = [CENTER_LAT, CENTER_LON]
    if "map_zoom" not in st.session_state:
        st.session_state["map_zoom"] = 8

    m = folium.Map(
        location=st.session_state["map_center"],
        zoom_start=st.session_state["map_zoom"],
        tiles=None,
    )

    # 한국어 지명 타일: OpenStreetMap Korea 사용
    folium.TileLayer(
        tiles="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png",
        attr='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
        name="지도",
        overlay=False,
        control=True,
    ).add_to(m)

    # ── 특보 색상 정의 (같은 계열, 경보=진하게 / 주의보=연하게) ──
    WARNING_COLORS = {
        "호우": {"경보": "#1565C0", "주의보": "#90CAF9"},   # 파란계열
        "대설": {"경보": "#4527A0", "주의보": "#B39DDB"},   # 보라계열
        "폭염": {"경보": "#D84315", "주의보": "#FFAB91"},   # 주황-빨강계열
        "한파": {"경보": "#00695C", "주의보": "#80CBC4"},   # 청록계열
        "강풍": {"경보": "#37474F", "주의보": "#B0BEC5"},   # 회색계열
        "풍랑": {"경보": "#01579B", "주의보": "#81D4FA"},   # 하늘색계열
        "태풍": {"경보": "#B71C1C", "주의보": "#EF9A9A"},   # 빨강계열
        "건조": {"경보": "#E65100", "주의보": "#FFCC80"},   # 오렌지계열
        "해일": {"경보": "#1A237E", "주의보": "#9FA8DA"},   # 남색계열
        "황사": {"경보": "#F9A825", "주의보": "#FFF59D"},   # 노랑계열
        "폭풍해일": {"경보": "#1A237E", "주의보": "#9FA8DA"},
        "안개": {"경보": "#424242", "주의보": "#E0E0E0"},
    }
    DEFAULT_COLOR = {"경보": "#D32F2F", "주의보": "#FFCDD2"}

    # ── 행정구역 경계 GeoJSON 로드 ──
    @st.cache_data(show_spinner=False)
    def load_boundary_geojson():
        boundary_file = os.path.join(os.path.dirname(__file__), "daegu_gyeongbuk_boundaries.json")
        if os.path.exists(boundary_file):
            import json
            with open(boundary_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None

    boundary_data = load_boundary_geojson()

    # ── 특보 데이터 기반 행정구역 폴리곤 레이어 ──
    active_warning_types = set()
    warning_display = warn_df if not warn_df.empty else pd.DataFrame()

    # 특보 발효 지역별 색상/투명도 매핑 생성
    warning_region_style = {}  # { region_name: (fill_color, opacity, tooltip_text) }

    if not warning_display.empty:
        dg_warn = warning_display[warning_display['region_up'].str.contains('대구|경북|경상북도', na=False)]
        for _, row in dg_warn.iterrows():
            region = row['region']
            wtype = row['type']
            level = row['level']

            color_set = WARNING_COLORS.get(wtype, DEFAULT_COLOR)
            color = color_set.get(level, color_set.get("주의보", "#FFCDD2"))
            opacity = 0.55 if level == "경보" else 0.35
            active_warning_types.add((wtype, level))
            warning_region_style[region] = (color, opacity, f"⚠️ {region} | {wtype} {level}")

    if sim_mode:
        sim_region_map = {
            "포항시": ("호우", "경보"), "구미시": ("강풍", "주의보"),
            "달서구": ("폭염", "경보"), "안동시": ("태풍", "경보"),
        }
        for region, (wtype, level) in sim_region_map.items():
            color_set = WARNING_COLORS.get(wtype, DEFAULT_COLOR)
            color = color_set.get(level, "#D32F2F")
            opacity = 0.55 if level == "경보" else 0.35
            active_warning_types.add((wtype, level))
            warning_region_style[region] = (color, opacity, f"🚨 모의: {region} | {wtype} {level}")

    # GeoJSON 폴리곤으로 특보 구역 표시
    if boundary_data and warning_region_style:
        import json as _json
        for feature in boundary_data['features']:
            feat_name = feature['properties']['name']
            style_info = warning_region_style.get(feat_name)
            if style_info is None:
                continue

            fill_color, opacity, tooltip_text = style_info

            # 개별 Feature를 GeoJson으로 추가
            folium.GeoJson(
                {"type": "FeatureCollection", "features": [feature]},
                style_function=lambda x, fc=fill_color, op=opacity: {
                    'fillColor': fc,
                    'color': fc,
                    'weight': 2,
                    'fillOpacity': op,
                },
                tooltip=tooltip_text,
            ).add_to(m)

    # ── 고정 범례 (지도 줌/패닝에 영향받지 않음) ──
    if active_warning_types:
        legend_items = ""
        for wtype, level in sorted(active_warning_types, key=lambda x: (x[0], x[1])):
            color_set = WARNING_COLORS.get(wtype, DEFAULT_COLOR)
            color = color_set.get(level, "#FFCDD2")
            legend_items += (
                f'<div style="display:flex;align-items:center;margin:3px 0;">'
                f'<span style="display:inline-block;width:14px;height:14px;'
                f'border-radius:50%;background:{color};margin-right:6px;'
                f'border:1px solid rgba(0,0,0,0.2);"></span>'
                f'<span style="font-size:12px;color:#333;">{wtype} {level}</span></div>'
            )
        legend_html = f"""
        <div style="
            position: fixed;
            bottom: 40px; left: 40px;
            z-index: 9999;
            background: rgba(255,255,255,0.92);
            border-radius: 8px;
            padding: 10px 14px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.15);
            font-family: 'Pretendard', 'Noto Sans KR', sans-serif;
            max-width: 180px;
        ">
            <div style="font-weight:700;font-size:13px;margin-bottom:6px;color:#222;">⚠️ 기상 특보</div>
            {legend_items}
        </div>
        """
        m.get_root().html.add_child(folium.Element(legend_html))

    # ── 소관시설 마커 (FontAwesome 아이콘) ──
    # 시설구분별 FontAwesome 아이콘 및 색상 매핑
    FACILITY_ICON_MAP = {
        "측정소":           {"icon": "thermometer-half", "color": "#2196F3", "prefix": "fa"},
        "공공하수처리시설":   {"icon": "tint",         "color": "#00897B", "prefix": "fa"},
        "시험실":           {"icon": "flask",          "color": "#7B1FA2", "prefix": "fa"},
        "청사":             {"icon": "building",       "color": "#455A64", "prefix": "fa"},
        "홍보관":           {"icon": "bullhorn",       "color": "#F57C00", "prefix": "fa"},
        "영농폐비닐 재활용시설": {"icon": "recycle",    "color": "#388E3C", "prefix": "fa"},
        "재활용품 비축기지":  {"icon": "cubes",         "color": "#5D4037", "prefix": "fa"},
        "영농폐기물 수거사업소": {"icon": "truck",      "color": "#6D4C41", "prefix": "fa"},
        "미래폐자원 거점수거센터": {"icon": "dot-circle-o", "color": "#00695C", "prefix": "fa"},
        "압수폐기물 보관창고": {"icon": "archive",      "color": "#795548", "prefix": "fa"},
        "기타":             {"icon": "map-marker",     "color": "#757575", "prefix": "fa"},
    }
    DEFAULT_FACILITY_ICON = {"icon": "map-marker", "color": "#9E9E9E", "prefix": "fa"}

    for idx, row in filtered_facility_df.iterrows():
        cat = row.get('시설구분', '')
        icon_info = FACILITY_ICON_MAP.get(cat, DEFAULT_FACILITY_ICON)
        dept = row.get('담당부서', '-')
        manager = row.get('부서 담당자', '-')
        code = row.get('시설코드', '-')
        note = row.get('비고', '-')

        popup_html = f"""
        <div style="font-family: 'Noto Sans KR', Arial, sans-serif; font-size:13px; line-height:1.6; min-width: 250px;">
            <h4 style="margin:0; color:#1565C0;">{row['name']}</h4>
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
            icon=folium.Icon(
                color='white',
                icon_color=icon_info["color"],
                icon=icon_info["icon"],
                prefix=icon_info["prefix"],
            )
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
