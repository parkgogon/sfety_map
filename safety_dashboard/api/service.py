"""Cloud Run에서 사용하는 관제 snapshot 캐시와 조립 서비스."""

from __future__ import annotations

import datetime as dt
import threading
import time
from typing import Any, Callable

from core.region_resolver import WarningZoneIndex
from safety_dashboard.adapters.facility_csv import CsvFacilityRepository
from safety_dashboard.adapters.kma import KmaWarningProvider, WarningZoneRepository
from safety_dashboard.adapters.region_matcher import OfficialZoneMatcher
from safety_dashboard.api.serialization import KST, serialize_monitoring
from safety_dashboard.api.settings import ApiSettings
from safety_dashboard.application.facility_groups import FacilityGroupCatalog
from safety_dashboard.application.monitoring import MonitoringService
from safety_dashboard.domain.enums import DataHealth
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
        self._payload: dict[str, Any] | None = None
        self._payload_expires_at = 0.0
        self._zone_data: dict[str, Any] | None = None
        self._zone_health = DataHealth.ERROR
        self._zone_detail = "특보구역을 불러오지 못했습니다."
        self._zone_expires_at = 0.0

    def monitoring(self, force_refresh: bool = False) -> dict[str, Any]:
        now = self._monotonic()
        if not force_refresh and self._payload is not None and now < self._payload_expires_at:
            return self._payload
        with self._lock:
            now = self._monotonic()
            if not force_refresh and self._payload is not None and now < self._payload_expires_at:
                return self._payload
            payload = self._build_payload(now)
            self._payload = payload
            self._payload_expires_at = now + self.settings.monitoring_cache_seconds
            return payload

    def _build_payload(self, monotonic_now: float) -> dict[str, Any]:
        policy = RiskPolicy.load(self.settings.policy_path)
        catalog = FacilityGroupCatalog.load(self.settings.group_path)
        facilities = CsvFacilityRepository(self.settings.facility_path)
        zone_data, zone_health, zone_detail = self._zones(monotonic_now)
        zone_index = WarningZoneIndex.from_geojson(zone_data)
        snapshot = MonitoringService(
            facilities,
            KmaWarningProvider(self.settings.kma_api_key, policy, timeout=7),
            OfficialZoneMatcher(zone_index),
            policy,
        ).get_snapshot(now=dt.datetime.now(KST))
        return serialize_monitoring(
            snapshot,
            catalog,
            policy,
            zone_data,
            zone_health,
            zone_detail,
        )

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
