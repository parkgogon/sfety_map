"""세 Streamlit 페이지가 공유하는 관제 입력과 캐시."""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass
from pathlib import Path

import streamlit as st

from core.region_resolver import WarningZoneIndex
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
from safety_dashboard.adapters.kma import (
    FeedWarningProvider,
    KmaWarningProvider,
    StaticWarningProvider,
    WarningZoneRepository,
    simulation_warnings,
)
from safety_dashboard.adapters.region_matcher import OfficialZoneMatcher
from safety_dashboard.application.facility_groups import FacilityGroupCatalog
from safety_dashboard.application.cctv_directions import (
    CctvDirectionCatalog,
    load_cctv_direction_catalog,
)
from safety_dashboard.application.monitoring import MonitoringService
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


@st.cache_data(ttl=600, show_spinner=False)
def load_live_feed(api_key: str, policy_modified_at: float):
    del policy_modified_at
    policy = RiskPolicy.load(POLICY_PATH)
    return KmaWarningProvider(api_key, policy).fetch_active()


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
    zone_index = build_zone_index(zone_data)
    if simulation:
        provider = StaticWarningProvider(simulation_warnings(policy))
    else:
        feed = load_live_feed(
            secret("kma", "api_key", "KMA_API_KEY"),
            POLICY_PATH.stat().st_mtime,
        )
        provider = FeedWarningProvider(feed)
    service = MonitoringService(
        _FacilityTupleRepository(load_facilities(FACILITY_PATH.stat().st_mtime)),
        provider,
        OfficialZoneMatcher(zone_index),
        policy,
    )
    return MonitoringContext(
        base_policy=base_policy,
        policy=policy,
        temporary_policy=temporary,
        snapshot=service.get_snapshot(),
        zone_data=zone_data,
        zone_health=zone_health,
        zone_message=zone_message,
        facility_groups=load_facility_groups(GROUP_PATH.stat().st_mtime),
    )


def clear_live_caches() -> None:
    load_live_feed.clear()
    load_zones.clear()
    build_zone_index.clear()
    load_current_weather.clear()
    load_disaster_feed.clear()
    load_cctv_feed.clear()
