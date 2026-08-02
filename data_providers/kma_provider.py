"""
기상청(KMA) 데이터 제공자 모듈

기상청 API Hub의 다음 API를 사용합니다:
- 특보현황 조회 (wrn_now_data_new.php)
- 동네예보 격자 변환 (nph-dfs_xy_lonlat)
- 초단기 실황 조회 (getUltraSrtNcst)
- 특보 이미지 (nph-wrn7)
"""

import datetime
import math
import os
from typing import Dict, Optional, Tuple

import pandas as pd
import requests
import streamlit as st

from data_providers import BaseWarningProvider

# 기본 기준 좌표 (대구·경북 중심부)
CENTER_LAT = 36.0
CENTER_LON = 128.5


def get_kma_api_key() -> str:
    """환경변수 또는 Streamlit secrets에서 KMA API 키를 읽습니다."""

    env_key = os.getenv("KMA_API_KEY", "").strip()
    if env_key:
        return env_key

    try:
        return str(st.secrets["kma"]["api_key"]).strip()
    except (KeyError, TypeError, FileNotFoundError):
        return ""


def _warning_frame(
    warnings: list[dict],
    *,
    status: str,
    message: str = "",
) -> pd.DataFrame:
    df = pd.DataFrame(
        warnings,
        columns=["region_up", "region", "type", "level", "source"],
    )
    df.attrs["fetch_status"] = status
    df.attrs["fetch_message"] = message
    df.attrs["fetched_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    return df


class KMAProvider(BaseWarningProvider):
    """기상청 특보/기상 데이터 제공자"""

    source_name = "기상청"

    # ──────────────────────────────────────────────
    # 특보현황 조회
    # ──────────────────────────────────────────────
    @staticmethod
    @st.cache_data(ttl=600)  # 10분마다 갱신
    def _fetch_warnings() -> pd.DataFrame:
        """기상청 특보현황 조회(wrn_now_data_new.php) - 전국 기준"""
        api_key = get_kma_api_key()
        if not api_key:
            return _warning_frame(
                [],
                status="error",
                message="KMA API 키가 설정되지 않았습니다.",
            )

        now = datetime.datetime.now()
        tm = now.strftime("%Y%m%d%H%M")
        url = "https://apihub.kma.go.kr/api/typ01/url/wrn_now_data_new.php"
        params = {
            "fe": "f",
            "tm": tm,
            "disp": "0",
            "help": "0",
            "authKey": api_key,
        }

        warnings = []
        try:
            resp = requests.get(url, params=params, timeout=7)
            resp.raise_for_status()
            lines = resp.text.split("\n")
            for line in lines:
                if not line.startswith("#") and "=" in line:
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 10:
                        warnings.append(
                            {
                                "region_up": parts[1],
                                "region": parts[3],
                                "type": parts[6],
                                "level": parts[7],
                                "source": "기상청",
                            }
                        )
        except (requests.RequestException, ValueError) as exc:
            return _warning_frame(
                [],
                status="error",
                message=f"기상청 특보 조회 실패: {type(exc).__name__}",
            )
        return _warning_frame(warnings, status="ok")

    def get_warnings(self, region_filter: Optional[str] = None) -> pd.DataFrame:
        df = self._fetch_warnings()
        attrs = dict(df.attrs)
        if region_filter and not df.empty:
            df = df[df["region_up"].str.contains(region_filter, na=False)]
            df.attrs.update(attrs)
        return df

    # ──────────────────────────────────────────────
    # 격자 변환 및 초단기 실황
    # ──────────────────────────────────────────────
    @staticmethod
    @st.cache_data(ttl=3600)
    def get_grid_coordinates(lon: float, lat: float) -> Tuple[str, str]:
        """위경도를 기상청 동네예보 격자로 변환"""
        api_key = get_kma_api_key()
        if not api_key:
            return "87", "93"

        url = "https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-dfs_xy_lonlat"
        params = {"lon": lon, "lat": lat, "help": "0", "authKey": api_key}
        try:
            resp = requests.get(url, params=params, timeout=7)
            resp.raise_for_status()
            for line in resp.text.split("\n"):
                if not line.startswith("#") and line.strip():
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 4:
                        return parts[2], parts[3]
        except Exception:
            pass
        return "87", "93"  # Default Daegu Grid

    @staticmethod
    def fetch_ultra_short_weather(nx: str, ny: str) -> Dict[str, str]:
        """초단기 실황조회 (특정 위치 기상 상태 파악)"""
        api_key = get_kma_api_key()
        now = datetime.datetime.now()
        if now.minute < 30:
            now = now - datetime.timedelta(hours=1)

        base_date = now.strftime("%Y%m%d")
        base_time = now.strftime("%H00")

        url = (
            "https://apihub.kma.go.kr/api/typ02/openApi/"
            "VilageFcstInfoService_2.0/getUltraSrtNcst"
        )
        params = {
            "pageNo": 1,
            "numOfRows": 10,
            "dataType": "JSON",
            "base_date": base_date,
            "base_time": base_time,
            "nx": nx,
            "ny": ny,
            "authKey": api_key,
        }

        weather_data = {
            "기온(℃)": "-",
            "1시간강수량(mm)": "-",
            "풍향(deg)": "-",
            "풍속(m/s)": "-",
            "_status": "error" if not api_key else "ok",
        }
        if not api_key:
            return weather_data

        try:
            resp = requests.get(url, params=params, timeout=7)
            resp.raise_for_status()
            if resp.status_code == 200:
                items = (
                    resp.json()
                    .get("response", {})
                    .get("body", {})
                    .get("items", {})
                    .get("item", [])
                )
                for item in items:
                    cat = item.get("category")
                    val = item.get("obsrValue")
                    if cat == "T1H":
                        weather_data["기온(℃)"] = val
                    elif cat == "RN1":
                        weather_data["1시간강수량(mm)"] = val
                    elif cat == "VEC":
                        weather_data["풍향(deg)"] = val
                    elif cat == "WSD":
                        weather_data["풍속(m/s)"] = val
        except (requests.RequestException, ValueError):
            weather_data["_status"] = "error"
        return weather_data

    def get_weather_at(self, lat: float, lon: float) -> Dict[str, str]:
        grid_x, grid_y = self.get_grid_coordinates(lon, lat)
        return self.fetch_ultra_short_weather(grid_x, grid_y)

    # ──────────────────────────────────────────────
    # 특보 이미지 URL 생성
    # ──────────────────────────────────────────────
    @staticmethod
    def get_warning_image_url(
        center_lat: float = CENTER_LAT,
        center_lon: float = CENTER_LON,
        range_km: int = 200,
        size_px: int = 600,
    ) -> str:
        """기상청 임의지역 특보이미지 URL 생성"""
        now_tm = datetime.datetime.now().strftime("%Y%m%d%H%M")
        api_key = get_kma_api_key()
        return (
            f"https://apihub.kma.go.kr/api/typ03/cgi/wrn/nph-wrn7"
            f"?out=0&tmef=1&city=1&name=0&tm={now_tm}"
            f"&lon={center_lon}&lat={center_lat}&range={range_km}&size={size_px}"
            f"&wrn=W,R,C,D,O,V,T,S,Y,H&authKey={api_key}"
        )

    @staticmethod
    def get_image_bounds(
        center_lat: float = CENTER_LAT,
        center_lon: float = CENTER_LON,
        range_km: int = 200,
    ):
        """특보 이미지 오버레이의 지도 바운드 계산"""
        lat_delta = range_km / 111.32
        lon_delta = range_km / (111.32 * math.cos(math.radians(center_lat)))
        return [
            [center_lat - lat_delta, center_lon - lon_delta],
            [center_lat + lat_delta, center_lon + lon_delta],
        ]


# 시뮬레이션 모드용 데이터
SIMULATION_WARNINGS = pd.DataFrame(
    [
        {"region_up": "경상북도", "region": "포항시", "type": "호우", "level": "경보", "source": "기상청"},
        {"region_up": "경상북도", "region": "구미시", "type": "강풍", "level": "주의보", "source": "기상청"},
        {"region_up": "대구광역시", "region": "달서구", "type": "폭염", "level": "경보", "source": "기상청"},
        {"region_up": "경상북도", "region": "안동시", "type": "태풍", "level": "경보", "source": "기상청"},
    ]
)

SIMULATION_WEATHER = {
    "기온(℃)": "32.5",
    "1시간강수량(mm)": "55.0",
    "풍향(deg)": "140",
    "풍속(m/s)": "22.5",
}

SIM_ZONES = [
    {"region": "포항시 (호우경보)", "lat": 36.019, "lon": 129.343, "color": "red"},
    {"region": "구미시 (강풍주의보)", "lat": 36.119, "lon": 128.344, "color": "orange"},
    {"region": "달서구 (폭염경보)", "lat": 35.829, "lon": 128.532, "color": "darkred"},
    {"region": "안동시 (태풍경보)", "lat": 36.568, "lon": 128.729, "color": "purple"},
]
