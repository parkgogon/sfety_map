"""Cloud Run과 로컬 개발에서 공유하는 API 설정."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]


def _local_secrets() -> Mapping[str, Any]:
    """로컬 Streamlit secrets를 선택적으로 읽되 오류나 내용을 노출하지 않는다."""

    path = ROOT / ".streamlit" / "secrets.toml"
    try:
        with path.open("rb") as file:
            value = tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return value if isinstance(value, Mapping) else {}


def _secret(env_name: str, section: str, key: str) -> str:
    value = os.getenv(env_name, "").strip()
    if value:
        return value
    section_values = _local_secrets().get(section, {})
    if not isinstance(section_values, Mapping):
        return ""
    return str(section_values.get(key, "") or "").strip()


@dataclass(frozen=True)
class ApiSettings:
    kma_api_key: str
    its_cctv_api_key: str = ""
    its_cctv_api_url: str = "https://openapi.its.go.kr:9443/cctvInfo"
    facility_path: Path = ROOT / "facilities_info.csv"
    policy_path: Path = ROOT / "safety_dashboard" / "config" / "risk_policy.toml"
    group_path: Path = ROOT / "safety_dashboard" / "config" / "facility_groups.toml"
    zone_fallback_path: Path = ROOT / "data" / "kma_warning_zones.geojson.gz"
    cctv_direction_path: Path = (
        ROOT / "safety_dashboard" / "config" / "cctv_directions.toml"
    )
    monitoring_cache_seconds: int = 300
    zone_cache_seconds: int = 86400
    weather_cache_seconds: int = 600
    cctv_cache_seconds: int = 60
    context_error_cache_seconds: int = 30

    @classmethod
    def from_environment(cls) -> "ApiSettings":
        def seconds(name: str, default: int, minimum: int) -> int:
            try:
                return max(minimum, int(os.getenv(name, str(default))))
            except ValueError:
                return default

        return cls(
            kma_api_key=_secret("KMA_API_KEY", "kma", "api_key"),
            its_cctv_api_key=_secret(
                "ITS_CCTV_API_KEY", "its_cctv", "api_key"
            ),
            its_cctv_api_url=(
                os.getenv("ITS_CCTV_API_URL", "").strip()
                or _secret("ITS_CCTV_API_URL", "its_cctv", "api_url")
                or cls.its_cctv_api_url
            ),
            facility_path=Path(
                os.getenv("FACILITY_DATA_PATH", str(cls.facility_path))
            ),
            policy_path=Path(
                os.getenv("RISK_POLICY_PATH", str(cls.policy_path))
            ),
            group_path=Path(
                os.getenv("FACILITY_GROUPS_PATH", str(cls.group_path))
            ),
            zone_fallback_path=Path(
                os.getenv("WARNING_ZONE_PATH", str(cls.zone_fallback_path))
            ),
            cctv_direction_path=Path(
                os.getenv(
                    "CCTV_DIRECTION_PATH",
                    str(cls.cctv_direction_path),
                )
            ),
            monitoring_cache_seconds=seconds("MONITORING_CACHE_SECONDS", 300, 30),
            zone_cache_seconds=seconds("WARNING_ZONE_CACHE_SECONDS", 86400, 300),
            weather_cache_seconds=seconds("WEATHER_CACHE_SECONDS", 600, 60),
            cctv_cache_seconds=seconds("CCTV_CACHE_SECONDS", 60, 30),
            context_error_cache_seconds=seconds(
                "CONTEXT_ERROR_CACHE_SECONDS", 30, 10
            ),
        )
