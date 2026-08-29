"""Streamlit과 pandas에 의존하지 않는 KMA HTTP 어댑터."""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

import requests

from safety_dashboard.domain.enums import DataHealth, KmaFailureCategory
from safety_dashboard.domain.models import KmaFailureDiagnostic, Warning, WarningFeed
from safety_dashboard.domain.region_resolver import (
    KMA_WARNING_SCOPE_PREFIXES,
    normalize_warning_zone_data,
)
from safety_dashboard.domain.risk_policy import RiskPolicy


WARNING_URL = "https://apihub.kma.go.kr/api/typ01/url/wrn_now_data_new.php"
ZONE_URL = "https://www.weather.go.kr/wgis-nuri/js/info/wrnArea.geojson"
KMA_PUBLIC_DELAY_MESSAGE = (
    "KMA 특보 자료 수신이 지연되고 있습니다. "
    "공식 특보를 함께 확인해 주세요."
)


def validate_warning_response(text: str) -> None:
    """HTML·공백·알 수 없는 200 응답을 정상 빈 특보로 오인하지 않는다."""

    stripped = text.strip()
    lowered = stripped.casefold()
    if not stripped:
        raise ValueError("KMA 응답이 비어 있음")
    if "<html" in lowered or "<!doctype" in lowered:
        raise ValueError("KMA 대신 HTML 응답 수신")
    has_header = "REG_UP" in stripped and "REG_ID" in stripped and "WRN" in stripped
    has_record = any(
        len(line.split(",")) >= 10 and not line.lstrip().startswith("#")
        for line in stripped.splitlines()
    )
    if not has_header and not has_record:
        raise ValueError("KMA 특보 응답 형식을 확인할 수 없음")


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
            return WarningFeed(
                (),
                DataHealth.ERROR,
                fetched_at,
                KMA_PUBLIC_DELAY_MESSAGE,
                KmaFailureDiagnostic(
                    KmaFailureCategory.AUTH_CONFIG,
                    "KMA API 키가 설정되지 않음",
                    "요청을 시작하기 전에 필수 설정값이 비어 있음",
                    cause_type="MissingApiKey",
                ),
            )
        params = {
            "fe": "f",
            "tm": fetched_at.strftime("%Y%m%d%H%M"),
            "disp": "0",
            "help": "0",
            "authKey": self.api_key,
        }
        try:
            response = requests.get(WARNING_URL, params=params, timeout=self.timeout)
            if response.status_code in {400, 401, 403}:
                return self._failure(
                    fetched_at,
                    KmaFailureCategory.AUTH_CONFIG,
                    "KMA API가 인증을 거부함",
                    f"HTTP {response.status_code}",
                    http_status=response.status_code,
                )
            if response.status_code == 429:
                return self._failure(
                    fetched_at,
                    KmaFailureCategory.QUOTA,
                    "KMA API 사용량 제한에 도달함",
                    "HTTP 429",
                    http_status=429,
                )
            if response.status_code >= 500:
                return self._failure(
                    fetched_at,
                    KmaFailureCategory.KMA_SERVER,
                    "KMA API 서버가 오류를 반환함",
                    f"HTTP {response.status_code}",
                    http_status=response.status_code,
                )
            response.raise_for_status()
            validate_warning_response(response.text)
            warnings = parse_warning_response(response.text, self.policy)
        except ValueError as exc:
            return self._failure(
                fetched_at,
                KmaFailureCategory.RESPONSE_FORMAT,
                "KMA 응답 형식을 해석할 수 없음",
                str(exc),
                cause_type=type(exc).__name__,
            )
        except requests.RequestException as exc:
            return self._failure(
                fetched_at,
                KmaFailureCategory.UNKNOWN,
                "KMA API와 연결하지 못함",
                type(exc).__name__,
                cause_type=type(exc).__name__,
            )
        return WarningFeed(warnings, DataHealth.LIVE, fetched_at)

    @staticmethod
    def _failure(
        fetched_at: dt.datetime,
        category: KmaFailureCategory,
        summary: str,
        evidence: str,
        *,
        cause_type: str = "",
        http_status: int | None = None,
    ) -> WarningFeed:
        return WarningFeed(
            (),
            DataHealth.ERROR,
            fetched_at,
            KMA_PUBLIC_DELAY_MESSAGE,
            KmaFailureDiagnostic(
                category,
                summary,
                evidence,
                cause_type=cause_type,
                http_status=http_status,
            ),
        )


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
    from safety_dashboard.simulation.scenarios import create_simulation_warnings

    return create_simulation_warnings(policy)


def _parse_datetime(value: object) -> dt.datetime | None:
    try:
        return dt.datetime.strptime(str(value).strip(), "%Y%m%d%H%M")
    except ValueError:
        return None
