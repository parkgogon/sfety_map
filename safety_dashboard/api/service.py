"""Cloud Run에서 사용하는 관제 snapshot 캐시와 조립 서비스."""

from __future__ import annotations

import datetime as dt
import threading
import time
from dataclasses import replace
from typing import Any, Callable

from core.region_resolver import WarningZoneIndex
from safety_dashboard.adapters.facility_csv import CsvFacilityRepository
from safety_dashboard.adapters.kma import (
    KmaWarningProvider,
    StaticWarningProvider,
    WarningZoneRepository,
    simulation_warnings,
)
from safety_dashboard.adapters.region_matcher import OfficialZoneMatcher
from safety_dashboard.api.serialization import KST, serialize_monitoring
from safety_dashboard.api.settings import ApiSettings
from safety_dashboard.application.facility_groups import FacilityGroupCatalog
from safety_dashboard.application.monitoring import MonitoringService
from safety_dashboard.domain.enums import DataHealth
from safety_dashboard.domain.models import DashboardSnapshot
from safety_dashboard.domain.risk_policy import RiskPolicy


class MonitoringApiService:
    """프로세스 안에서 짧게 캐시하되 강제 갱신을 지원한다."""

    def __init__(
        self,
        settings: ApiSettings,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._payloads: dict[bool, dict[str, Any]] = {}
        self._payload_expires_at: dict[bool, float] = {}
        self._refresh_allowed_at: dict[bool, float] = {}
        self._last_successful_builds: dict[
            bool,
            tuple[DashboardSnapshot, FacilityGroupCatalog, RiskPolicy],
        ] = {}
        self._zone_data: dict[str, Any] | None = None
        self._zone_health = DataHealth.ERROR
        self._zone_detail = "특보구역을 불러오지 못했습니다."
        self._zone_expires_at = 0.0

    def monitoring(
        self,
        force_refresh: bool = False,
        simulation: bool = False,
    ) -> dict[str, Any]:
        """실시간과 모의훈련 결과를 서로 다른 캐시로 제공합니다."""

        now = self._monotonic()
        if self._can_reuse_payload(now, force_refresh, simulation):
            return self._payloads[simulation]
        with self._lock:
            now = self._monotonic()
            if self._can_reuse_payload(now, force_refresh, simulation):
                return self._payloads[simulation]
            payload = self._build_payload(now, simulation=simulation)
            self._payloads[simulation] = payload
            self._payload_expires_at[simulation] = (
                now + self.settings.monitoring_cache_seconds
            )
            self._refresh_allowed_at[simulation] = (
                now + self.settings.monitoring_refresh_cooldown_seconds
            )
            return payload

    def _can_reuse_payload(
        self,
        monotonic_now: float,
        force_refresh: bool,
        simulation: bool,
    ) -> bool:
        if simulation not in self._payloads:
            return False
        if force_refresh:
            return monotonic_now < self._refresh_allowed_at.get(simulation, 0.0)
        return monotonic_now < self._payload_expires_at.get(simulation, 0.0)

    def _build_payload(
        self,
        monotonic_now: float,
        *,
        simulation: bool = False,
    ) -> dict[str, Any]:
        snapshot, catalog, policy, zone_data, zone_health, zone_detail = (
            self._build_snapshot(monotonic_now, simulation=simulation)
        )
        if snapshot.warning_feed.health in {
            DataHealth.LIVE,
            DataHealth.SIMULATION,
        }:
            self._last_successful_builds[simulation] = (snapshot, catalog, policy)
        elif snapshot.warning_feed.health is DataHealth.ERROR:
            previous = self._last_successful_builds.get(simulation)
            if previous is not None:
                previous_snapshot, previous_catalog, previous_policy = previous
                detail = (
                    f"{snapshot.warning_feed.message.strip()} "
                    "마지막 정상 자료를 표시합니다."
                ).strip()
                snapshot = replace(
                    previous_snapshot,
                    warning_feed=replace(
                        previous_snapshot.warning_feed,
                        health=DataHealth.STALE,
                        fetched_at=snapshot.warning_feed.fetched_at,
                        message=detail,
                        diagnostic=snapshot.warning_feed.diagnostic,
                    ),
                    notices=tuple(
                        dict.fromkeys((*previous_snapshot.notices, detail))
                    ),
                )
                catalog = previous_catalog
                policy = previous_policy
        return serialize_monitoring(
            snapshot,
            catalog,
            policy,
            zone_data,
            zone_health,
            zone_detail,
        )

    def snapshot(self, *, simulation: bool = False) -> DashboardSnapshot:
        """자동 작업자가 직렬화 이전의 동일 관제 결과를 사용하게 합니다."""

        with self._lock:
            snapshot, _, _, _, _, _ = self._build_snapshot(
                self._monotonic(),
                simulation=simulation,
            )
            return snapshot

    def _build_snapshot(
        self,
        monotonic_now: float,
        *,
        simulation: bool,
    ) -> tuple[
        DashboardSnapshot,
        FacilityGroupCatalog,
        RiskPolicy,
        dict[str, Any],
        DataHealth,
        str,
    ]:
        policy = RiskPolicy.load(self.settings.policy_path)
        catalog = FacilityGroupCatalog.load(self.settings.group_path)
        facilities = CsvFacilityRepository(self.settings.facility_path)
        zone_data, zone_health, zone_detail = self._zones(monotonic_now)
        zone_index = WarningZoneIndex.from_geojson(zone_data)
        warning_provider = (
            StaticWarningProvider(simulation_warnings(policy))
            if simulation
            else KmaWarningProvider(self.settings.kma_api_key, policy, timeout=7)
        )
        snapshot = MonitoringService(
            facilities,
            warning_provider,
            OfficialZoneMatcher(zone_index),
            policy,
        ).get_snapshot(now=dt.datetime.now(KST))
        return snapshot, catalog, policy, zone_data, zone_health, zone_detail

    def _zones(self, monotonic_now: float) -> tuple[dict[str, Any], DataHealth, str]:
        if self._zone_data is None or monotonic_now >= self._zone_expires_at:
            data, health, detail = WarningZoneRepository(
                self.settings.zone_fallback_path,
                timeout=10,
            ).load()
            self._zone_data = data
            self._zone_health = health
            self._zone_detail = detail
            self._zone_expires_at = monotonic_now + self.settings.zone_cache_seconds
        return self._zone_data, self._zone_health, self._zone_detail
