import streamlit as st
import pandas as pd
import zipfile
import re
import requests
import datetime
from xml.etree import ElementTree as ET
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
import folium
from streamlit_folium import st_folium
import math

# ==========================================
# 1. 전역 설정 및 초기화
# ==========================================
st.set_page_config(page_title="스마트 기상·재난 관제 대시보드", layout="wide", page_icon="📡")
API_KEY = "a7c780dkQDC3O_NHZOAwuw"
KMZ_FILE = "대구경북환경본부 소관시설 위치정보.kmz"

# 기본 기준 좌표 (대구·경북 중심부)
CENTER_LAT = 36.0
CENTER_LON = 128.5

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
# 2. 데이터 처리 및 KMA API 호출 모듈 (캐싱)
# ==========================================

import os

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
        except Exception as e:
            st.error("시설물 정보 파일 로딩 중 오류가 발생했습니다.")
            st.stop()
    else:
        st.error("시설물 참조 파일(facilities_info.csv)이 없습니다.")
        st.stop()

@st.cache_data(ttl=600)  # 10분마다 갱신
def get_current_warnings():
    """기상청 특보현황 조회(wrn_now_data_new.php) - 실시간 알림"""
    now = datetime.datetime.now()
    tm = now.strftime("%Y%m%d%H%M")
    url = f"https://apihub.kma.go.kr/api/typ01/url/wrn_now_data_new.php?fe=f&tm={tm}&disp=0&help=0&authKey={API_KEY}"
    
    warnings = []
    try:
        resp = requests.get(url, timeout=5)
        lines = resp.text.split('\n')
        for line in lines:
            if not line.startswith('#') and '=' in line:
                parts = [p.strip() for p in line.split(',')]
                if len(parts) >= 10:
                    reg_up_ko = parts[1]   # 상위구역 (예: 경상북도)
                    reg_ko = parts[3]      # 세부구역 (예: 포항시)
                    wrn_type = parts[6]    # 특보 (예: 강풍)
                    lvl = parts[7]         # 등급 (예: 주의보)
                    warnings.append({
                        "region_up": reg_up_ko,
                        "region": reg_ko,
                        "type": wrn_type,
                        "level": lvl
                    })
    except Exception as e:
        pass
    return pd.DataFrame(warnings)

@st.cache_data(ttl=3600) # Grid 위치 변환은 잘 안바뀌므로 1시간
def get_grid_coordinates(lon, lat):
    """위경도를 기상청 동네예보 격자로 변환"""
    url = f"https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-dfs_xy_lonlat?lon={lon}&lat={lat}&help=0&authKey={API_KEY}"
    try:
        resp = requests.get(url, timeout=5)
        for line in resp.text.split('\n'):
            if not line.startswith('#') and line.strip():
                parts = [p.strip() for p in line.split(',')]
                if len(parts) >= 4:
                    return parts[2], parts[3]
    except:
        pass
    return "87", "93"  # Default Daegu Grid

def get_ultra_short_weather(nx, ny):
    """초단기 실황조회 (특정 위치 기상 상태 파악) - ttl 금지 (실시간 용도)"""
    now = datetime.datetime.now()
    # KMA 초단기 실황은 수 분전 데이터를 제공하므로 안정성을 위해 30분 전 데이터를 호출할수도 있으나
    # API 규격에 맞춰 정시/분 단위를 맞춰 호출
    if now.minute < 30: # 대략적으로 매시간 30분 이후 실황 생성됨 (안전하게 1시간 전)
        now = now - datetime.timedelta(hours=1)
    
    base_date = now.strftime("%Y%m%d")
    base_time = now.strftime("%H00") # 정시 기준 호출
    
    url = f"https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getUltraSrtNcst?pageNo=1&numOfRows=10&dataType=JSON&base_date={base_date}&base_time={base_time}&nx={nx}&ny={ny}&authKey={API_KEY}"
    
    weather_data = {"기온(℃)": "-", "1시간강수량(mm)": "-", "풍향(deg)": "-", "풍속(m/s)": "-"}
    try:
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            items = resp.json().get('response', {}).get('body', {}).get('items', {}).get('item', [])
            for item in items:
                cat = item.get('category')
                val = item.get('obsrValue')
                if cat == 'T1H': weather_data["기온(℃)"] = val
                elif cat == 'RN1': weather_data["1시간강수량(mm)"] = val
                elif cat == 'VEC': weather_data["풍향(deg)"] = val
                elif cat == 'WSD': weather_data["풍속(m/s)"] = val
    except:
        pass
    return weather_data


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
    warn_df = pd.DataFrame([
        {"region_up": "경상북도", "region": "포항시", "type": "호우", "level": "경보"},
        {"region_up": "경상북도", "region": "구미시", "type": "강풍", "level": "주의보"},
        {"region_up": "대구광역시", "region": "달서구", "type": "폭염", "level": "경보"},
        {"region_up": "경상북도", "region": "안동시", "type": "태풍", "level": "경보"}
    ])
else:
    warn_df = get_current_warnings()

# ==========================================
# 패널 2: [좌측 상단] 실시간 재난·특보 알림 티커
# ==========================================
# 경북/대구 지역에 해당되는 특보만 필터링
daegu_gyeongbuk_warn = []
if not warn_df.empty:
    dg_df = warn_df[warn_df['region_up'].str.contains('대구|경북|경상북도', na=False)]
    for _, row in dg_df.iterrows():
        daegu_gyeongbuk_warn.append(f"🚨 [{row['region']}] {row['type']} {row['level']} 발효 중")

if daegu_gyeongbuk_warn:
    marquee_text = " &nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp; ".join(daegu_gyeongbuk_warn)
    st.markdown(f'<div class="ticker"><marquee>{marquee_text}</marquee></div>', unsafe_allow_html=True)
else:
    st.info("✅ 현재 대구/경북 지역에 발효 중인 기상 특보가 없습니다.")


st.markdown("---")


# ==========================================
# 메인 레이아웃 구성: 좌측(지도) / 우측(날씨 모니터링 & AX 점검 목록)
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
    m = folium.Map(location=[CENTER_LAT, CENTER_LON], zoom_start=8, tiles="CartoDB positron")

    # 기상청 임의지역 특보이미지 오버레이 (KMA API Image)
    # size=600px, range=200km 로 가정하여 bounds 계산
    now_tm = datetime.datetime.now().strftime("%Y%m%d%H%M")
    wrn_img_url = f"https://apihub.kma.go.kr/api/typ03/cgi/wrn/nph-wrn7?out=0&tmef=1&city=1&name=0&tm={now_tm}&lon={CENTER_LON}&lat={CENTER_LAT}&range=200&size=600&wrn=W,R,C,D,O,V,T,S,Y,H&authKey={API_KEY}"
    
    img_lat_delta = 200 / 111.32
    img_lon_delta = 200 / (111.32 * math.cos(math.radians(CENTER_LAT)))
    bounds = [
        [CENTER_LAT - img_lat_delta, CENTER_LON - img_lon_delta],
        [CENTER_LAT + img_lat_delta, CENTER_LON + img_lon_delta]
    ]

    folium.raster_layers.ImageOverlay(
        image=wrn_img_url,
        bounds=bounds,
        opacity=0.55,
        name="KMA 기상특보 구역"
    ).add_to(m)

    if sim_mode:
        sim_zones = [
            {"region": "포항시 (호우경보)", "lat": 36.019, "lon": 129.343, "color": "red"},
            {"region": "구미시 (강풍주의보)", "lat": 36.119, "lon": 128.344, "color": "orange"},
            {"region": "달서구 (폭염경보)", "lat": 35.829, "lon": 128.532, "color": "darkred"},
            {"region": "안동시 (태풍경보)", "lat": 36.568, "lon": 128.729, "color": "purple"}
        ]
        for zone in sim_zones:
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

    st_folium(m, width=700, height=800, use_container_width=True)

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
    grid_x, grid_y = get_grid_coordinates(f_info['longitude'], f_info['latitude'])
    
    if sim_mode:
        weather_now = {"기온(℃)": "32.5", "1시간강수량(mm)": "55.0", "풍향(deg)": "140", "풍속(m/s)": "22.5"}
        w_col1, w_col2, w_col3, w_col4 = st.columns(4)
        w_col1.metric("기온", f"{weather_now['기온(℃)']} ℃", delta="1.2 ℃")
        w_col2.metric("강수량 (1h)", f"{weather_now['1시간강수량(mm)']} mm", delta="55.0 mm", delta_color="inverse")
        w_col3.metric("풍향", f"{weather_now['풍향(deg)']} 도")
        w_col4.metric("풍속", f"{weather_now['풍속(m/s)']} m/s", delta="15.5 m/s", delta_color="inverse")
    else:
        weather_now = get_ultra_short_weather(grid_x, grid_y)
        w_col1, w_col2, w_col3, w_col4 = st.columns(4)
        w_col1.metric("기온", f"{weather_now['기온(℃)']} ℃")
        w_col2.metric("강수량 (1h)", f"{weather_now['1시간강수량(mm)']} mm")
        w_col3.metric("풍향", f"{weather_now['풍향(deg)']} 도")
        w_col4.metric("풍속", f"{weather_now['풍속(m/s)']} m/s")
    
    st.markdown("<br><hr>", unsafe_allow_html=True)
    
    # 패널 4: [우측 하단 패널] 재난 징후 연동 대상 자동 추출 목록
    st.subheader("⚠️ 재난 징후 연동: 긴급 점검 요망 대상")
    st.write("현재 특보 발효 구역 내에 포함되어 즉각적인 시설 안전 점검이 요구되는 리스트입니다.")
    
    if warn_df.empty:
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
            # 깔끔한 테이블 출력
            st.dataframe(target_df, use_container_width=True, hide_index=True)
            st.error(f"총 {len(target_df)}개의 선제 점검 대상 시설이 도출되었습니다.")
        else:
            st.success("현재 특보 발효 구역에 위치한 소관시설이 없습니다.")
