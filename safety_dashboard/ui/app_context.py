"""세 Streamlit 페이지가 공유하는 관제 입력과 캐시."""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass, replace
from pathlib import Path

import streamlit as st

from safety_dashboard.adapters.cctv import DEFAULT_API_URL as CCTV_API_URL
from safety_dashboard.adapters.cctv import ItsCctvProvider
from safety_dashboard.adapters.current_weather import CurrentWeatherProvider
from safety_dashboard.adapters.disaster_messages import (
    DEFAULT_API_URL as DISASTER_API_URL,
)
from safety_dashboard.adapters.disaster_messages import (
    SafetyDataDisasterMessageProvider,
)
from safety_dashboard.adapters.facility_csv import CsvFacilityRepository
from safety_dashboard.domain.region_resolver import WarningZoneIndex
from safety_dashboard.adapters.kma import (
    StaticWarningProvider,
    WarningZoneRepository,
    simulation_warnings,
)
from safety_dashboard.adapters.monitoring_api import (
    MonitoringSnapshotApiClient,
    MonitoringSnapshotApiError,
)
from safety_dashboard.adapters.region_matcher import OfficialZoneMatcher
from safety_dashboard.application.facility_groups import FacilityGroupCatalog
from safety_dashboard.application.cctv_directions import (
    CctvDirectionCatalog,
    load_cctv_direction_catalog,
)
from safety_dashboard.application.monitoring import (
    MonitoringService,
    reassess_snapshot,
)
from safety_dashboard.domain.enums import DataHealth
from safety_dashboard.domain.models import (
    DashboardSnapshot,
    Facility,
    FacilityRegion,
    GeoPoint,
)
from safety_dashboard.domain.risk_policy import RiskPolicy
from safety_dashboard.ui.policy_editor import effective_policy


ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "safety_dashboard" / "config" / "risk_policy.toml"
GROUP_PATH = ROOT / "safety_dashboard" / "config" / "facility_groups.toml"
DIRECTION_PATH = ROOT / "safety_dashboard" / "config" / "cctv_directions.toml"
FACILITY_PATH = ROOT / "facilities_info.csv"
ZONE_FALLBACK_PATH = ROOT / "data" / "kma_warning_zones.geojson.gz"
FONT_PATH = ROOT / "fonts" / "NotoSansKR.ttf"
STYLE_PATH = ROOT / "safety_dashboard" / "ui" / "style.css"
KST = dt.timezone(dt.timedelta(hours=9))


@dataclass(frozen=True)
class MonitoringContext:
    base_policy: RiskPolicy
    policy: RiskPolicy
    temporary_policy: bool
    snapshot: DashboardSnapshot
    zone_data: dict
    zone_health: DataHealth
    zone_message: str
    facility_groups: FacilityGroupCatalog


class _FacilityTupleRepository:
    def __init__(self, facilities: tuple[Facility, ...]) -> None:
        self._facilities = facilities

    def list_monitored(self) -> tuple[Facility, ...]:
        return self._facilities


def secret(section: str, key: str, env_name: str) -> str:
    env_value = os.getenv(env_name, "").strip()
    if env_value:
        return env_value
    try:
        return str(st.secrets[section][key]).strip()
    except (KeyError, TypeError, FileNotFoundError):
        return ""


@st.cache_resource
def load_policy(modified_at: float) -> RiskPolicy:
    del modified_at
    return RiskPolicy.load(POLICY_PATH)


@st.cache_resource
def load_facility_groups(modified_at: float) -> FacilityGroupCatalog:
    del modified_at
    return FacilityGroupCatalog.load(GROUP_PATH)


@st.cache_resource
def load_cctv_directions(
    modified_at: float,
) -> tuple[CctvDirectionCatalog, str]:
    del modified_at
    return load_cctv_direction_catalog(DIRECTION_PATH)


@st.cache_data(show_spinner=False)
def load_facilities(modified_at: float) -> tuple[Facility, ...]:
    del modified_at
    return CsvFacilityRepository(FACILITY_PATH).list_monitored()


@st.cache_data(ttl=86400, show_spinner=False)
def load_zones() -> tuple[dict, DataHealth, str]:
    return WarningZoneRepository(ZONE_FALLBACK_PATH).load()


@st.cache_resource(show_spinner=False)
def build_zone_index(zone_data: dict) -> WarningZoneIndex:
    return WarningZoneIndex.from_geojson(zone_data)


@st.cache_data(ttl=60, show_spinner=False)
def load_common_monitoring_snapshot(
    admin_api_url: str,
    admin_token: str,
) -> DashboardSnapshot:
    return MonitoringSnapshotApiClient(
        admin_api_url,
        admin_token,
        timeout=12,
    ).fetch()


@st.cache_data(ttl=180, show_spinner=False)
def load_disaster_feed(
    api_key: str,
    api_url: str,
    province: str,
    district: str,
    query_name: str,
    reference_bucket: str,
):
    reference = dt.datetime.fromisoformat(reference_bucket)
    region = FacilityRegion(province, district, query_name)
    return SafetyDataDisasterMessageProvider(
        api_key,
        api_url=api_url or DISASTER_API_URL,
        timeout=7,
    ).fetch_recent(region, reference - dt.timedelta(hours=6))


@st.cache_data(ttl=60, show_spinner=False)
def load_cctv_feed(
    api_key: str,
    api_url: str,
    latitude: float,
    longitude: float,
    reference_bucket: str,
    refresh_token: str,
):
    del reference_bucket, refresh_token
    return ItsCctvProvider(
        api_key,
        api_url=api_url or CCTV_API_URL,
        timeout=7,
    ).fetch_nearby(GeoPoint(latitude, longitude), radius_km=20, limit=5)


@st.cache_data(ttl=600, show_spinner=False)
def load_current_weather(
    api_key: str,
    latitude: float,
    longitude: float,
    reference_bucket: str,
):
    reference = dt.datetime.fromisoformat(reference_bucket)
    return CurrentWeatherProvider(api_key, timeout=7).fetch(
        GeoPoint(latitude, longitude),
        reference,
    )


def monitoring_context(simulation: bool = False) -> MonitoringContext:
    base_policy = load_policy(POLICY_PATH.stat().st_mtime)
    policy, temporary = effective_policy(base_policy)
    zone_data, zone_health, zone_message = load_zones()
    if simulation:
        zone_index = build_zone_index(zone_data)
        service = MonitoringService(
            _FacilityTupleRepository(
                load_facilities(FACILITY_PATH.stat().st_mtime)
            ),
            StaticWarningProvider(simulation_warnings(policy)),
            OfficialZoneMatcher(zone_index),
            policy,
        )
        snapshot = service.get_snapshot()
    else:
        snapshot = _shared_live_snapshot()
        if snapshot.policy_version != policy.version:
            snapshot = reassess_snapshot(snapshot, policy)
    return MonitoringContext(
        base_policy=base_policy,
        policy=policy,
        temporary_policy=temporary,
        snapshot=snapshot,
        zone_data=zone_data,
        zone_health=zone_health,
        zone_message=zone_message,
        facility_groups=load_facility_groups(GROUP_PATH.stat().st_mtime),
    )


def clear_live_caches() -> None:
    load_common_monitoring_snapshot.clear()
    load_zones.clear()
    build_zone_index.clear()
    load_current_weather.clear()
    load_disaster_feed.clear()
    load_cctv_feed.clear()


def _shared_live_snapshot() -> DashboardSnapshot:
    state_key = "shared_last_monitoring_snapshot"
    try:
        snapshot = load_common_monitoring_snapshot(
            secret("alerting", "admin_api_url", "ALERT_ADMIN_API_URL"),
            secret("alerting", "admin_token", "ALERT_ADMIN_TOKEN"),
        )
    except MonitoringSnapshotApiError as exc:
        previous = st.session_state.get(state_key)
        if isinstance(previous, DashboardSnapshot):
            return _stale_streamlit_snapshot(
                previous,
                "공통 관제 API 연결이 지연되어 "
                "이 브라우저의 마지막 정상 자료를 표시합니다.",
            )
        raise RuntimeError(
            "공통 관제 snapshot을 불러오지 못했습니다."
        ) from exc

    previous = st.session_state.get(state_key)
    if (
        snapshot.warning_feed.health is DataHealth.ERROR
        and isinstance(previous, DashboardSnapshot)
    ):
        return _stale_streamlit_snapshot(
            previous,
            snapshot.warning_feed.message
            or "공통 관제 자료 수신이 지연되고 있습니다.",
        )
    if snapshot.warning_feed.health in {DataHealth.LIVE, DataHealth.STALE}:
        st.session_state[state_key] = snapshot
    return snapshot


def _stale_streamlit_snapshot(
    snapshot: DashboardSnapshot,
    message: str,
) -> DashboardSnapshot:
    detail = message.strip()
    return replace(
        snapshot,
        warning_feed=replace(
            snapshot.warning_feed,
            health=DataHealth.STALE,
            message=detail,
        ),
        notices=tuple(dict.fromkeys((*snapshot.notices, detail))),
    )
