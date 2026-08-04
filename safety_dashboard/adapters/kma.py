"""Streamlit과 pandas에 의존하지 않는 KMA HTTP 어댑터."""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

import requests

from core.region_resolver import KMA_WARNING_SCOPE_PREFIXES, normalize_warning_zone_data
from safety_dashboard.domain.enums import DataHealth
from safety_dashboard.domain.models import Warning, WarningFeed
from safety_dashboard.domain.risk_policy import RiskPolicy


WARNING_URL = "https://apihub.kma.go.kr/api/typ01/url/wrn_now_data_new.php"
ZONE_URL = "https://www.weather.go.kr/wgis-nuri/js/info/wrnArea.geojson"


def parse_warning_response(
    text: str,
    policy: RiskPolicy,
    scope_prefixes: Sequence[str] = KMA_WARNING_SCOPE_PREFIXES,
) -> tuple[Warning, ...]:
    """KMA 쉼표 구분 응답을 표준 Warning 모델로 변환합니다."""

    result: list[Warning] = []
    prefixes = tuple(scope_prefixes)
    for line in text.splitlines():
        if line.startswith("#") or "," not in line:
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 10:
            continue
        up_code, up_name, code, region = parts[:4]
        if not (up_code.startswith(prefixes) or code.startswith(prefixes)):
            continue
        issued_at = _parse_datetime(parts[4])
        effective_at = _parse_datetime(parts[5])
        warning_type, raw_level, command = parts[6:9]
        identity = "|".join((code, warning_type, raw_level, parts[4], command))
        result.append(
            Warning(
                id=hashlib.sha1(identity.encode("utf-8")).hexdigest()[:16],
                source="기상청",
                region_up_code=up_code,
                region_code=code,
                region_up=up_name,
                region=region,
                warning_type=warning_type,
                raw_level=raw_level,
                level=policy.normalize_level(raw_level),
                command=command,
                issued_at=issued_at,
                effective_at=effective_at,
            )
        )
    return tuple(result)


class KmaWarningProvider:
    def __init__(self, api_key: str, policy: RiskPolicy, timeout: float = 7) -> None:
        self.api_key = api_key.strip()
        self.policy = policy
        self.timeout = timeout

    def fetch_active(self) -> WarningFeed:
        fetched_at = dt.datetime.now()
        if not self.api_key:
            return WarningFeed((), DataHealth.ERROR, fetched_at, "KMA API 키가 없습니다.")
        params = {
            "fe": "f",
            "tm": fetched_at.strftime("%Y%m%d%H%M"),
            "disp": "0",
            "help": "0",
            "authKey": self.api_key,
        }
        try:
            response = requests.get(WARNING_URL, params=params, timeout=self.timeout)
            response.raise_for_status()
            warnings = parse_warning_response(response.text, self.policy)
        except (requests.RequestException, ValueError) as exc:
            return WarningFeed(
                (), DataHealth.ERROR, fetched_at,
                f"KMA 특보 조회 실패 ({type(exc).__name__})",
            )
        return WarningFeed(warnings, DataHealth.LIVE, fetched_at)


class WarningZoneRepository:
    def __init__(self, fallback_path: str | Path, timeout: float = 10) -> None:
        self.fallback_path = Path(fallback_path)
        self.timeout = timeout

    def load(self) -> tuple[dict[str, Any], DataHealth, str]:
        try:
            response = requests.get(ZONE_URL, timeout=self.timeout)
            response.raise_for_status()
            data = normalize_warning_zone_data(response.json())
            return data, DataHealth.LIVE, "KMA 공식 특보구역 최신본"
        except (requests.RequestException, ValueError, json.JSONDecodeError):
            try:
                with gzip.open(self.fallback_path, "rt", encoding="utf-8") as file:
                    data = normalize_warning_zone_data(json.load(file))
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError("KMA 특보구역을 불러올 수 없습니다.") from exc
            return data, DataHealth.FALLBACK, "KMA 특보구역 내장본"


class StaticWarningProvider:
    def __init__(self, warnings: Sequence[Warning], message: str = "모의훈련 데이터") -> None:
        self.warnings = tuple(warnings)
        self.message = message

    def fetch_active(self) -> WarningFeed:
        return WarningFeed(
            self.warnings,
            DataHealth.SIMULATION,
            dt.datetime.now(),
            self.message,
        )


class FeedWarningProvider:
    """이미 조회된 feed를 애플리케이션 서비스에 전달합니다."""

    def __init__(self, feed: WarningFeed) -> None:
        self.feed = feed

    def fetch_active(self) -> WarningFeed:
        return self.feed


def simulation_warnings(policy: RiskPolicy) -> tuple[Warning, ...]:
    now = dt.datetime.now().replace(minute=0, second=0, microsecond=0)
    values = (
        ("L1070000", "L1072400", "경상북도", "포항시", "호우", "경보"),
        ("L1070000", "L1070300", "경상북도", "구미시", "강풍", "주의보"),
        ("L1140000", "L1140100", "대구광역시", "대구중부", "폭염", "경보"),
        ("L1070000", "L1072700", "경상북도", "안동시", "태풍", "경보"),
    )
    return tuple(
        Warning(
            id=f"simulation-{index}", source="모의훈련", region_up_code=up_code,
            region_code=code, region_up=up_name, region=region,
            warning_type=kind, raw_level=level,
            level=policy.normalize_level(level), command="발표",
            issued_at=now, effective_at=now,
        )
        for index, (up_code, code, up_name, region, kind, level) in enumerate(values, 1)
    )


def _parse_datetime(value: object) -> dt.datetime | None:
    try:
        return dt.datetime.strptime(str(value).strip(), "%Y%m%d%H%M")
    except ValueError:
        return None
