import streamlit as st
import pandas as pd
import datetime
import os
import math

import telegram_utils

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
        /* ── Google Fonts ── */
        @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700;900&display=swap');

        /* ── 글로벌 기본 (Material Symbols 폰트 보존) ── */
        html, body, p, span, div, input, button, select, textarea, td, th, li, a, label, h1, h2, h3, h4, h5, h6 {
            font-family: 'Noto Sans KR', -apple-system, BlinkMacSystemFont, sans-serif;
        }

        /* ── 헤더 영역 ── */
        .header-title { color: #1565C0; font-weight: 800; }

        /* ── 특보 티커 ── */
        .ticker {
            background: linear-gradient(135deg, #D32F2F 0%, #B71C1C 100%);
            color: white;
            padding: 10px 16px;
            font-weight: 600;
            font-size: 14px;
            border-radius: 8px;
            margin-bottom: 16px;
            box-shadow: 0 2px 8px rgba(211,47,47,0.3);
            letter-spacing: 0.02em;
        }

        /* ── 메트릭 카드 강화 ── */
        div[data-testid="stMetric"] {
            background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
            border-radius: 10px;
            padding: 12px 14px;
            border-left: 4px solid #1565C0;
            box-shadow: 0 1px 4px rgba(0,0,0,0.06);
        }
        div[data-testid="stMetric"] label {
            font-weight: 600 !important;
            color: #555 !important;
            font-size: 13px !important;
        }
        div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
            font-weight: 700 !important;
            color: #1a1a2e !important;
        }

        /* ── 서브헤더 ── */
        .stMarkdown h3 {
            color: #1565C0;
            font-weight: 700;
            border-bottom: 2px solid #e3f2fd;
            padding-bottom: 6px;
        }

        /* ── Expander 스타일 ── */
        .stExpander {
            border: 1px solid #e0e0e0;
            border-radius: 10px;
        }
        .stExpander > details > summary {
            font-weight: 600;
            color: #333;
        }

        /* ── 필터 체크박스 ── */
        .filter-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 4px 12px;
        }

        /* ── 점검 대상 테이블 (HTML) ── */
        .inspection-table {
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
            font-size: 13px;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 1px 4px rgba(0,0,0,0.08);
        }
        .inspection-table thead th {
            background: linear-gradient(135deg, #1565C0, #1976D2);
            color: white;
            padding: 8px 10px;
            font-weight: 600;
            font-size: 12px;
            text-align: center;
            white-space: nowrap;
        }
        .inspection-table tbody td {
            padding: 7px 10px;
            border-bottom: 1px solid #f0f0f0;
            font-size: 12px;
        }
        .inspection-table tbody tr:nth-child(even) {
            background: #f8fafe;
        }
        .inspection-table tbody tr:hover {
            background: #e3f2fd;
        }

        /* ── 구분선 ── */
        hr { border-color: #e3f2fd !important; }

        /* ── 다운로드 버튼 ── */
        .stDownloadButton > button {
            background: linear-gradient(135deg, #1565C0, #0D47A1) !important;
            border: none !important;
            border-radius: 8px !important;
            font-weight: 600 !important;
            letter-spacing: 0.02em !important;
            box-shadow: 0 2px 8px rgba(21,101,192,0.3) !important;
        }
        .stDownloadButton > button:hover {
            background: linear-gradient(135deg, #1976D2, #1565C0) !important;
            box-shadow: 0 4px 12px rgba(21,101,192,0.4) !important;
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
# 메인 레이아웃: 좌측(지도) / 우측(탭 패널)
# ==========================================

MAP_HEIGHT = 650

st.markdown(f"""
    <style>
        /* ── 메인 레이아웃: 미디어 쿼리로 반응형 처리 ── */
        
        /* [PC 모드] 가로 768px 이상 */
        @media (min-width: 768px) {{
            /* 부모 블록: flex-start 적용 (자식 sticky를 위해 필요) */
            div[data-testid="stHorizontalBlock"]:has(> div[data-testid="stColumn"] iframe) {{
                align-items: flex-start !important;
            }}
            /* 좌측: 지도(iframe)를 가진 stColumn → sticky 고정 */
            div[data-testid="stColumn"]:has(iframe) {{
                position: sticky !important;
                top: 60px !important;
                align-self: flex-start !important;
                z-index: 10;
            }}
            /* 우측: 지도 옆의 패널 컬럼 → 고정 높이 + 내부 스크롤 */
            div[data-testid="stHorizontalBlock"]:has(> div[data-testid="stColumn"] iframe) > div[data-testid="stColumn"]:not(:has(iframe)) {{
                max-height: {MAP_HEIGHT}px !important;
                overflow-y: auto !important;
                overflow-x: hidden !important;
                border: 1px solid #e0e0e0;
                border-radius: 12px;
                padding: 8px;
                background: #fafbfc;
                box-shadow: 0 2px 12px rgba(0,0,0,0.06);
            }}
        }}
        
        /* [모바일 모드] 가로 767px 이하 */
        @media (max-width: 767px) {{
            /* 모바일에서는 지도 높이를 축소 */
            div[data-testid="stColumn"]:has(iframe) iframe {{
                height: 400px !important;
            }}
            /* 우측 패널 디자인은 유지하되 스크롤 제한 해제 */
            div[data-testid="stHorizontalBlock"]:has(> div[data-testid="stColumn"] iframe) > div[data-testid="stColumn"]:not(:has(iframe)) {{
                border: 1px solid #e0e0e0;
                border-radius: 12px;
                padding: 8px;
                background: #fafbfc;
                box-shadow: 0 2px 12px rgba(0,0,0,0.06);
            }}
        }}
        /* 탭 헤더 sticky (우측 패널 내부에서) */
        div[data-testid="stTabs"] > div[role="tablist"] {{
            position: sticky;
            top: -8px;
            z-index: 100;
            background: #fafbfc;
            padding-top: 4px;
            border-bottom: 2px solid #e3f2fd;
        }}
        div[data-testid="stTabs"] button[role="tab"] {{
            font-weight: 600;
            font-size: 13px;
        }}
        div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {{
            color: #1565C0;
            border-bottom-color: #1565C0;
        }}
    </style>
""", unsafe_allow_html=True)

col_map, col_panel = st.columns([1.6, 1])

# ── 카테고리 필터 데이터 준비 (위젯 key 기반) ──
if '시설구분' in facility_df.columns:
    categories = sorted(facility_df['시설구분'].dropna().unique().tolist())
    # 위젯 key로 직접 상태 관리 (초기화만 1회)
    for cat in categories:
        if f"cb_{cat}" not in st.session_state:
            st.session_state[f"cb_{cat}"] = True
            
    def select_all_cats():
        for c in categories:
            st.session_state[f"cb_{c}"] = True
            
    def clear_all_cats():
        for c in categories:
            st.session_state[f"cb_{c}"] = False

    selected_categories = [cat for cat in categories if st.session_state.get(f"cb_{cat}", True)]
    filtered_facility_df = facility_df[facility_df['시설구분'].isin(selected_categories)]
else:
    categories = []
    filtered_facility_df = facility_df

# ------------------------------------------
# 좌측: 지도
# ------------------------------------------
with col_map:
    st.subheader("🗺️ 실시간 특보 현황 & 소관시설 위치")

    if "map_center" not in st.session_state:
        st.session_state["map_center"] = [CENTER_LAT, CENTER_LON]
    if "map_zoom" not in st.session_state:
        st.session_state["map_zoom"] = 8

    m = folium.Map(
        location=st.session_state["map_center"],
        zoom_start=st.session_state["map_zoom"],
        tiles=None,
    )
    folium.TileLayer(
        tiles="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png",
        attr='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
        name="지도", overlay=False, control=True,
    ).add_to(m)

    # ── 특보 색상 ──
    WARNING_COLORS = {
        "호우": {"경보": "#1565C0", "주의보": "#90CAF9"},
        "대설": {"경보": "#4527A0", "주의보": "#B39DDB"},
        "폭염": {"경보": "#D84315", "주의보": "#FFAB91"},
        "한파": {"경보": "#00695C", "주의보": "#80CBC4"},
        "강풍": {"경보": "#37474F", "주의보": "#B0BEC5"},
        "풍랑": {"경보": "#01579B", "주의보": "#81D4FA"},
        "태풍": {"경보": "#B71C1C", "주의보": "#EF9A9A"},
        "건조": {"경보": "#E65100", "주의보": "#FFCC80"},
        "해일": {"경보": "#1A237E", "주의보": "#9FA8DA"},
        "황사": {"경보": "#F9A825", "주의보": "#FFF59D"},
        "폭풍해일": {"경보": "#1A237E", "주의보": "#9FA8DA"},
        "안개": {"경보": "#424242", "주의보": "#E0E0E0"},
    }
    DEFAULT_COLOR = {"경보": "#D32F2F", "주의보": "#FFCDD2"}

    # ── GeoJSON 로드 ──
    @st.cache_data(show_spinner=False)
    def load_boundary_geojson():
        boundary_file = os.path.join(os.path.dirname(__file__), "daegu_gyeongbuk_boundaries.json")
        if os.path.exists(boundary_file):
            import json
            with open(boundary_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None

    boundary_data = load_boundary_geojson()

    # ── 특보 폴리곤 ──
    active_warning_types = set()
    warning_region_style = {}

    if not warn_df.empty:
        dg_warn_map = warn_df[warn_df['region_up'].str.contains('대구|경북|경상북도', na=False)]
        for _, row in dg_warn_map.iterrows():
            region, wtype, level = row['region'], row['type'], row['level']
            color_set = WARNING_COLORS.get(wtype, DEFAULT_COLOR)
            color = color_set.get(level, color_set.get("주의보", "#FFCDD2"))
            opacity = 0.55 if level == "경보" else 0.35
            active_warning_types.add((wtype, level))
            warning_region_style[region] = (color, opacity, f"⚠️ {region} | {wtype} {level}")

    if sim_mode:
        for region, (wtype, level) in {"포항시": ("호우", "경보"), "구미시": ("강풍", "주의보"), "달서구": ("폭염", "경보"), "안동시": ("태풍", "경보")}.items():
            color_set = WARNING_COLORS.get(wtype, DEFAULT_COLOR)
            color = color_set.get(level, "#D32F2F")
            opacity = 0.55 if level == "경보" else 0.35
            active_warning_types.add((wtype, level))
            warning_region_style[region] = (color, opacity, f"🚨 모의: {region} | {wtype} {level}")

    if boundary_data and warning_region_style:
        for feature in boundary_data['features']:
            feat_name = feature['properties']['name']
            style_info = warning_region_style.get(feat_name)
            if style_info is None:
                continue
            fill_color, opacity, tooltip_text = style_info
            folium.GeoJson(
                {"type": "FeatureCollection", "features": [feature]},
                style_function=lambda x, fc=fill_color, op=opacity: {
                    'fillColor': fc, 'color': fc, 'weight': 2, 'fillOpacity': op,
                },
                tooltip=tooltip_text,
            ).add_to(m)

    # ── 범례 ──
    if active_warning_types:
        legend_items = ""
        for wtype, level in sorted(active_warning_types):
            c = WARNING_COLORS.get(wtype, DEFAULT_COLOR).get(level, "#FFCDD2")
            legend_items += (
                f'<div style="display:flex;align-items:center;margin:3px 0;">'
                f'<span style="width:14px;height:14px;border-radius:50%;background:{c};'
                f'margin-right:6px;border:1px solid rgba(0,0,0,0.2);display:inline-block;"></span>'
                f'<span style="font-size:12px;color:#333;">{wtype} {level}</span></div>'
            )
        m.get_root().html.add_child(folium.Element(f"""
        <div style="position:fixed;bottom:40px;left:40px;z-index:9999;
            background:rgba(255,255,255,0.92);border-radius:8px;padding:10px 14px;
            box-shadow:0 2px 8px rgba(0,0,0,0.15);font-family:'Noto Sans KR',sans-serif;max-width:180px;">
            <div style="font-weight:700;font-size:13px;margin-bottom:6px;color:#222;">⚠️ 기상 특보</div>
            {legend_items}
        </div>"""))

    # ── 시설 마커 ──
    FACILITY_ICON_MAP = {
        "대기측정소": {"icon": "cloud", "color": "#78909C", "prefix": "fa"},
        "수질측정소": {"icon": "tint", "color": "#0288D1", "prefix": "fa"},
        "측정소": {"icon": "home", "color": "#607D8B", "prefix": "fa"},
        "공공하수처리시설": {"icon": "tint", "color": "#00897B", "prefix": "fa"},
        "시험실": {"icon": "flask", "color": "#7B1FA2", "prefix": "fa"},
        "청사": {"icon": "building", "color": "#455A64", "prefix": "fa"},
        "홍보관": {"icon": "bullhorn", "color": "#F57C00", "prefix": "fa"},
        "영농폐비닐 재활용시설": {"icon": "recycle", "color": "#388E3C", "prefix": "fa"},
        "재활용품 비축기지": {"icon": "cubes", "color": "#5D4037", "prefix": "fa"},
        "영농폐기물 수거사업소": {"icon": "truck", "color": "#6D4C41", "prefix": "fa"},
        "미래폐자원 거점수거센터": {"icon": "dot-circle-o", "color": "#00695C", "prefix": "fa"},
        "압수폐기물 보관창고": {"icon": "archive", "color": "#795548", "prefix": "fa"},
        "기타": {"icon": "map-marker", "color": "#757575", "prefix": "fa"},
    }
    DEFAULT_ICON = {"icon": "map-marker", "color": "#9E9E9E", "prefix": "fa"}

    for _, row in filtered_facility_df.iterrows():
        cat = row.get('시설구분', '')
        facility_name = str(row.get('name', ''))
        # 측정소의 경우 이름으로 대기/수질 구분
        if cat == '측정소':
            if '대기' in facility_name:
                ic = FACILITY_ICON_MAP['대기측정소']
                display_cat = '대기측정소'
            elif '수질' in facility_name:
                ic = FACILITY_ICON_MAP['수질측정소']
                display_cat = '수질측정소'
            else:
                ic = FACILITY_ICON_MAP['측정소']
                display_cat = '측정소'
        else:
            ic = FACILITY_ICON_MAP.get(cat, DEFAULT_ICON)
            display_cat = cat
        popup_html = f"""<div style="font-family:'Noto Sans KR',sans-serif;font-size:13px;min-width:200px;">
            <b style="color:#1565C0;">{facility_name}</b><hr style="margin:4px 0;">
            시설구분: {display_cat}<br>담당: {row.get('부서 담당자','-')}<br>
            <span style="font-size:11px;color:#555;">📍 {row['address']}</span></div>"""
        folium.Marker(
            location=[row['latitude'], row['longitude']],
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=f"{facility_name} ({display_cat})",
            icon=folium.Icon(color='white', icon_color=ic["color"], icon=ic["icon"], prefix=ic["prefix"]),
        ).add_to(m)

    st_folium(m, width="100%", height=MAP_HEIGHT, returned_objects=[])


# ------------------------------------------
# 우측: 탭 패널
# ------------------------------------------
with col_panel:
    tab1, tab2, tab3 = st.tabs(["🌤️ 날씨 실황", "⚠️ 긴급 점검", "📋 보고서"])

    # ━━━ 탭 1: 날씨 실황 ━━━
    with tab1:
        # 시설 필터 (콜백 활용)
        if categories:
            sel_cnt = sum(1 for cat in categories if st.session_state.get(f"cb_{cat}", True))
            with st.expander("시설 필터", expanded=True):
                st.caption(f"선택됨: {sel_cnt}/{len(categories)}개")
                c1, c2 = st.columns(2)
                c1.button("✅ 전체 선택", use_container_width=True, key="btn_all", on_click=select_all_cats)
                c2.button("⬜ 전체 해제", use_container_width=True, key="btn_none", on_click=clear_all_cats)
                st.markdown("---")
                cb_cols = st.columns(2)
                for i, cat in enumerate(categories):
                    with cb_cols[i % 2]:
                        st.checkbox(cat, key=f"cb_{cat}")

        st.markdown("#### 🌤️ 시설 주변 초단기 날씨 실황")
        facility_options = filtered_facility_df['name'].tolist() if not filtered_facility_df.empty else []
        selected_facility = st.selectbox("정밀 관제할 시설:", facility_options)

        if selected_facility:
            f_info = facility_df[facility_df['name'] == selected_facility].iloc[0]
            st.caption(f"📍 {f_info['address']}")
            st.caption(f"위도: {f_info['latitude']:.4f}, 경도: {f_info['longitude']:.4f}")

            if sim_mode:
                weather_now = SIMULATION_WEATHER
                wc1, wc2 = st.columns(2)
                wc1.metric("🌡️ 기온", f"{weather_now['기온(℃)']} ℃", delta="1.2 ℃")
                wc2.metric("🌧️ 강수량", f"{weather_now['1시간강수량(mm)']} mm", delta="55.0 mm", delta_color="inverse")
                wc3, wc4 = st.columns(2)
                wc3.metric("🧭 풍향", f"{weather_now['풍향(deg)']} 도")
                wc4.metric("💨 풍속", f"{weather_now['풍속(m/s)']} m/s", delta="15.5 m/s", delta_color="inverse")
            else:
                weather_now = kma.get_weather_at(f_info['latitude'], f_info['longitude'])
                wc1, wc2 = st.columns(2)
                wc1.metric("🌡️ 기온", f"{weather_now['기온(℃)']} ℃")
                wc2.metric("🌧️ 강수량", f"{weather_now['1시간강수량(mm)']} mm")
                wc3, wc4 = st.columns(2)
                wc3.metric("🧭 풍향", f"{weather_now['풍향(deg)']} 도")
                wc4.metric("💨 풍속", f"{weather_now['풍속(m/s)']} m/s")

    # ━━━ 탭 2: 긴급 점검 ━━━
    with tab2:
        st.markdown("#### ⚠️ 긴급 점검 요망 대상")
        st.caption("현재 특보 발효 구역 내 즉각적인 시설 안전 점검이 요구되는 리스트")

        if warn_df.empty or dg_df.empty:
            st.success("감지된 재난 징후가 없어 점검 대상이 없습니다.")
        else:
            active_regions = dg_df['region'].unique()
            target_indices = []
            for reg in active_regions:
                keyword = str(reg).replace("시", "").replace("군", "").replace("구", "")
                for idx, row in filtered_facility_df.iterrows():
                    if keyword in str(row['address']):
                        target_indices.append(idx)
            target_indices = list(set(target_indices))

            if target_indices:
                target_df = filtered_facility_df.loc[target_indices][['name', '시설구분', '부서 담당자', 'address']]
                st.error(f"🚨 총 {len(target_df)}개의 선제 점검 대상 시설")

                # --- 텔레그램 알림 발송 로직 ---
                if st.button("🚨 위험 시설 텔레그램 알림 발송", use_container_width=True, type="primary"):
                    try:
                        bot_token = st.secrets["telegram"]["bot_token"]
                        chat_id = st.secrets["telegram"]["chat_id"]
                        
                        # 특보별로 시설 매핑
                        warning_to_facilities = {}
                        for _, w_row in dg_df.iterrows():
                            # w_row['type'] (예: 폭염), w_row['level'] (예: 경보)
                            w_type = f"{w_row.get('type', '')}{w_row.get('level', '')}"
                            if not w_type:
                                w_type = "기타특보"
                                
                            reg_keyword = str(w_row['region']).replace("시", "").replace("군", "").replace("구", "")
                            
                            for _, f_row in target_df.iterrows():
                                if reg_keyword in str(f_row['address']):
                                    if w_type not in warning_to_facilities:
                                        warning_to_facilities[w_type] = []
                                    warning_to_facilities[w_type].append(f_row)
                        
                        msg = "⚠️ <b>[긴급 점검 요망]</b>\n"
                        
                        for w_type, facilities in warning_to_facilities.items():
                            # 중복 시설 제거 (같은 특보가 인접 지역에 겹쳐서 조회된 경우)
                            unique_facilities = {f['name']: f for f in facilities}.values()
                            msg += f" - <b>{w_type}</b>\n"
                            
                            # 시설 구분별로 그룹핑
                            cat_to_names = {}
                            for f in unique_facilities:
                                cat = f['시설구분']
                                if cat not in cat_to_names:
                                    cat_to_names[cat] = []
                                cat_to_names[cat].append(f['name'])
                            
                            for cat, names in cat_to_names.items():
                                names_str = ", ".join(names)
                                msg += f"  - {cat}: {names_str}\n"
                                
                        msg += "\n대시보드를 확인하고 현장 안전 점검을 실시해주시기 바랍니다."
                        
                        success, res_msg = telegram_utils.send_telegram_alert(bot_token, chat_id, msg)
                        if success:
                            st.success("✅ 텔레그램 알림이 발송되었습니다.")
                        else:
                            st.error(f"❌ 발송 실패: {res_msg}")
                    except Exception as e:
                        import traceback
                        st.error(f"❌ 알림 발송 중 오류가 발생했습니다.")
                        st.code(traceback.format_exc())
                # -----------------------------

                table_html = '<table class="inspection-table"><thead><tr>'
                for h in ['시설명', '시설구분', '담당자', '주소']:
                    table_html += f'<th>{h}</th>'
                table_html += '</tr></thead><tbody>'
                for _, r in target_df.iterrows():
                    addr = str(r['address'])
                    if len(addr) > 28:
                        addr = addr[:28] + '...'
                    table_html += f'<tr><td style="font-weight:500;">{r["name"]}</td>'
                    table_html += f'<td style="text-align:center;">{r["시설구분"]}</td>'
                    table_html += f'<td style="text-align:center;font-size:11px;">{r["부서 담당자"]}</td>'
                    table_html += f'<td style="font-size:11px;color:#555;">{addr}</td></tr>'
                table_html += '</tbody></table>'
                st.markdown(table_html, unsafe_allow_html=True)
            else:
                st.success("현재 특보 발효 구역에 위치한 소관시설이 없습니다.")

    # ━━━ 탭 3: 보고서 ━━━
    with tab3:
        st.markdown("#### 📋 기상재난 시설물 영향 분석 보고서")
        generate_report = st.button(
            "📄 보고서 생성", type="primary",
            help="현재 발효 중인 특보를 기반으로 시설물 위험도를 분석합니다.",
            use_container_width=True,
        )
        st.caption("시설물별 위험도(상/중/하) 자동 산정 → PDF 다운로드 가능")

        if generate_report or st.session_state.get("report_generated", False):
            st.session_state["report_generated"] = True

            with st.spinner("위험도 분석 중..."):
                analysis_warnings = dg_df if not warn_df.empty and not dg_df.empty else warn_df
                result_df, grade_groups = assess_all_facilities(facility_df, analysis_warnings)

            total_affected = sum(len(df) for df in grade_groups.values())

            if total_affected == 0:
                st.info("영향 받는 소관시설이 없습니다. 시뮬레이션 모드를 활성화하세요.")
            else:
                cnt_h = len(grade_groups.get('상', []))
                cnt_m = len(grade_groups.get('중', []))
                cnt_l = len(grade_groups.get('하', []))

                sc1, sc2 = st.columns(2)
                sc1.metric("영향 시설", f"{total_affected}개")
                sc2.metric("🔴 상급", f"{cnt_h}개")
                sc3, sc4 = st.columns(2)
                sc3.metric("🟠 중급", f"{cnt_m}개")
                sc4.metric("🟡 하급", f"{cnt_l}개")

                st.markdown("---")

                weather_data_map = {}
                affected_facilities = []
                for grade in ["상", "중", "하"]:
                    gdf = grade_groups.get(grade)
                    if gdf is not None:
                        affected_facilities.extend(gdf.to_dict("records"))

                with st.spinner("기상 실황 조회 중..."):
                    for fac in affected_facilities[:10]:
                        lat, lon, name = fac.get("latitude", 0), fac.get("longitude", 0), fac.get("facility_name", "")
                        if lat and lon and name:
                            weather_data_map[name] = SIMULATION_WEATHER if sim_mode else kma.get_weather_at(lat, lon)

                html_report = generate_html_report(analysis_warnings, grade_groups, weather_data_map)
                st.html(html_report)

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
                    st.warning("PDF 생성 라이브러리(fpdf2)가 설치되지 않았습니다.")


