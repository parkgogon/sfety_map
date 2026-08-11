"""기상청 초단기실황을 시설 위치 기준으로 조회합니다."""

from __future__ import annotations

import datetime as dt
from typing import Any

import requests

from safety_dashboard.domain.enums import DataHealth
from safety_dashboard.domain.models import GeoPoint, WeatherObservation


GRID_URL = "https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-dfs_xy_lonlat"
OBSERVATION_URL = (
    "https://apihub.kma.go.kr/api/typ02/openApi/"
    "VilageFcstInfoService_2.0/getUltraSrtNcst"
)
KST = dt.timezone(dt.timedelta(hours=9))


class CurrentWeatherProvider:
    """Streamlit이나 임의 기본 격자에 의존하지 않는 현재 기상 제공자."""

    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = 7,
        session: Any = requests,
    ) -> None:
        self.api_key = str(api_key or "").strip()
        self.timeout = timeout
        self.session = session

    def fetch(
        self,
        location: GeoPoint,
        now: dt.datetime | None = None,
    ) -> WeatherObservation:
        reference = now or dt.datetime.now(KST)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=KST)
        if not self.api_key:
            return self._error(reference, "KMA API 키가 설정되지 않았습니다.")

        try:
            nx, ny = self._grid_for(location)
            base = reference.astimezone(KST)
            if base.minute < 40:
                base -= dt.timedelta(hours=1)
            base = base.replace(minute=0, second=0, microsecond=0)
            response = self.session.get(
                OBSERVATION_URL,
                params={
                    "pageNo": 1,
                    "numOfRows": 10,
                    "dataType": "JSON",
                    "base_date": base.strftime("%Y%m%d"),
                    "base_time": base.strftime("%H%M"),
                    "nx": nx,
                    "ny": ny,
                    "authKey": self.api_key,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            header = payload.get("response", {}).get("header", {})
            if str(header.get("resultCode", "00")) not in {"0", "00"}:
                detail = str(header.get("resultMsg", "응답 오류")).strip()
                raise ValueError(detail)
            items = (
                payload.get("response", {})
                .get("body", {})
                .get("items", {})
                .get("item", [])
            )
            values = {
                str(item.get("category", "")): item.get("obsrValue")
                for item in items
            }
            if not values:
                raise ValueError("관측 항목이 없습니다.")
            return WeatherObservation(
                observed_at=_observation_time(items, base),
                health=DataHealth.LIVE,
                temperature_c=_number(values.get("T1H")),
                rainfall_1h_mm=_number(values.get("RN1")),
                wind_speed_ms=_number(values.get("WSD")),
                wind_direction_deg=_number(values.get("VEC")),
                message="기상청 초단기실황",
            )
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            return self._error(reference, f"현재 기상 조회 실패: {type(exc).__name__}")

    def _grid_for(self, location: GeoPoint) -> tuple[str, str]:
        response = self.session.get(
            GRID_URL,
            params={
                "lon": location.longitude,
                "lat": location.latitude,
                "help": "0",
                "authKey": self.api_key,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        for line in response.text.splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = [part.strip() for part in line.split(",")]
            if len(parts) >= 4 and parts[2] and parts[3]:
                return parts[2], parts[3]
        raise ValueError("시설 위치의 기상청 격자를 확인할 수 없습니다.")

    @staticmethod
    def _error(reference: dt.datetime, message: str) -> WeatherObservation:
        return WeatherObservation(
            observed_at=reference,
            health=DataHealth.ERROR,
            message=message,
        )


def _number(value: object) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _observation_time(items: object, fallback: dt.datetime) -> dt.datetime:
    if not isinstance(items, list) or not items:
        return fallback
    first = items[0] if isinstance(items[0], dict) else {}
    raw = f"{first.get('baseDate', '')}{first.get('baseTime', '')}"
    try:
        return dt.datetime.strptime(raw, "%Y%m%d%H%M").replace(tzinfo=KST)
    except ValueError:
        return fallback
