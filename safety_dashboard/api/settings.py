"""Cloud Run과 로컬 개발에서 공유하는 API 설정."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from safety_dashboard.config.environment import env_text


ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ApiSettings:
    kma_api_key: str
    cctv_enabled: bool = True
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
    monitoring_refresh_cooldown_seconds: int = 60
    monitoring_snapshot_fresh_seconds: int = 900
    zone_cache_seconds: int = 86400
    weather_cache_seconds: int = 600
    weather_layer_cache_seconds: int = 600
    weather_layer_error_cache_seconds: int = 60
    cctv_cache_seconds: int = 60
    context_error_cache_seconds: int = 30
    nearby_map_capture_enabled: bool = False
    nearby_map_origin: str = "https://keco-safety-map.web.app"
    nearby_map_timeout_seconds: int = 20
    nearby_chromium_executable: str = "/usr/bin/chromium"

    @classmethod
    def from_environment(cls) -> "ApiSettings":
        def enabled(name: str, default: bool) -> bool:
            raw = os.getenv(name)
            if raw is None:
                return default
            return raw.strip().casefold() in {"1", "true", "yes", "on"}

        def seconds(name: str, default: int, minimum: int) -> int:
            try:
                return max(minimum, int(os.getenv(name, str(default))))
            except ValueError:
                return default

        return cls(
            kma_api_key=env_text("KMA_API_KEY"),
            cctv_enabled=enabled("CCTV_ENABLED", True),
            its_cctv_api_key=env_text("ITS_CCTV_API_KEY"),
            its_cctv_api_url=(env_text("ITS_CCTV_API_URL") or cls.its_cctv_api_url),
            facility_path=Path(os.getenv("FACILITY_DATA_PATH", str(cls.facility_path))),
            policy_path=Path(os.getenv("RISK_POLICY_PATH", str(cls.policy_path))),
            group_path=Path(os.getenv("FACILITY_GROUPS_PATH", str(cls.group_path))),
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
            monitoring_refresh_cooldown_seconds=seconds(
                "MONITORING_REFRESH_COOLDOWN_SECONDS", 60, 10
            ),
            monitoring_snapshot_fresh_seconds=seconds(
                "MONITORING_SNAPSHOT_FRESH_SECONDS", 900, 300
            ),
            zone_cache_seconds=seconds("WARNING_ZONE_CACHE_SECONDS", 86400, 300),
            weather_cache_seconds=seconds("WEATHER_CACHE_SECONDS", 600, 60),
            weather_layer_cache_seconds=seconds("WEATHER_LAYER_CACHE_SECONDS", 600, 60),
            weather_layer_error_cache_seconds=seconds(
                "WEATHER_LAYER_ERROR_CACHE_SECONDS", 60, 10
            ),
            cctv_cache_seconds=seconds("CCTV_CACHE_SECONDS", 60, 30),
            context_error_cache_seconds=seconds("CONTEXT_ERROR_CACHE_SECONDS", 30, 10),
            nearby_map_capture_enabled=enabled("NEARBY_MAP_CAPTURE_ENABLED", False),
            nearby_map_origin=env_text("DASHBOARD_BASE_URL") or cls.nearby_map_origin,
            nearby_map_timeout_seconds=min(30, seconds("NEARBY_MAP_TIMEOUT_SECONDS", 20, 5)),
            nearby_chromium_executable=env_text("NEARBY_CHROMIUM_EXECUTABLE") or cls.nearby_chromium_executable,
        )
