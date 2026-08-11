"""React 현장 지도에 시설별 기상·CCTV 참고정보를 제공합니다."""

from __future__ import annotations

import datetime as dt
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from safety_dashboard.adapters.cctv import ItsCctvProvider
from safety_dashboard.adapters.current_weather import CurrentWeatherProvider
from safety_dashboard.adapters.facility_csv import CsvFacilityRepository
from safety_dashboard.api.serialization import serialize_cctv, serialize_weather
from safety_dashboard.api.settings import ApiSettings
from safety_dashboard.application.cctv_directions import (
    CctvDirectionCatalog,
    load_cctv_direction_catalog,
)
from safety_dashboard.application.context_info import KST
from safety_dashboard.domain.enums import ContextStatus, DataHealth
from safety_dashboard.domain.models import CctvFeed, Facility, GeoPoint, WeatherObservation


class WeatherFetcher(Protocol):
    def fetch(
        self,
        location: GeoPoint,
        now: dt.datetime | None = None,
    ) -> WeatherObservation: ...


class CctvFetcher(Protocol):
    def fetch_nearby(
        self,
        location: GeoPoint,
        radius_km: float = 20,
        limit: int = 5,
    ) -> CctvFeed: ...


class FacilityNotFoundError(KeyError):
    """공개 API에서 요청한 시설 ID가 존재하지 않습니다."""


@dataclass(frozen=True)
class _CacheEntry:
    value: dict[str, Any]
    expires_at: float


class FacilityContextService:
    """외부 참고정보를 핵심 관제와 분리해 짧게 캐시합니다."""

    def __init__(
        self,
        settings: ApiSettings,
        *,
        weather_provider: WeatherFetcher | None = None,
        cctv_provider: CctvFetcher | None = None,
        direction_catalog: CctvDirectionCatalog | None = None,
        direction_warning: str | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        facilities = CsvFacilityRepository(settings.facility_path).list_monitored()
        self._facilities: dict[str, Facility] = {
            facility.id: facility for facility in facilities
        }
        self._weather_provider = weather_provider or CurrentWeatherProvider(
            settings.kma_api_key,
            timeout=7,
            cache_seconds=settings.weather_cache_seconds,
        )
        self._cctv_provider = cctv_provider or ItsCctvProvider(
            settings.its_cctv_api_key,
            api_url=settings.its_cctv_api_url,
            timeout=7,
        )
        if direction_catalog is None:
            loaded_catalog, loaded_warning = load_cctv_direction_catalog(
                settings.cctv_direction_path
            )
            self._direction_catalog = loaded_catalog
            self._direction_warning = loaded_warning
        else:
            self._direction_catalog = direction_catalog
            self._direction_warning = direction_warning or ""
        self._monotonic = monotonic
        self._weather_cache: dict[str, _CacheEntry] = {}
        self._cctv_cache: dict[str, _CacheEntry] = {}
        self._weather_lock = threading.Lock()
        self._cctv_lock = threading.Lock()

    def weather(self, facility_id: str) -> dict[str, Any]:
        facility = self._facility(facility_id)
        return self._cached(
            facility.id,
            self._weather_cache,
            self._weather_lock,
            lambda: self._weather_payload(facility),
            lambda value: (
                self.settings.weather_cache_seconds
                if value["status"] == DataHealth.LIVE.value
                else self.settings.context_error_cache_seconds
            ),
        )

    def cctv(self, facility_id: str) -> dict[str, Any]:
        facility = self._facility(facility_id)
        return self._cached(
            facility.id,
            self._cctv_cache,
            self._cctv_lock,
            lambda: self._cctv_payload(facility),
            lambda value: (
                self.settings.cctv_cache_seconds
                if value["status"] == ContextStatus.LIVE.value
                else self.settings.context_error_cache_seconds
            ),
        )

    def _facility(self, facility_id: str) -> Facility:
        normalized = str(facility_id or "").strip()
        facility = self._facilities.get(normalized)
        if facility is None:
            raise FacilityNotFoundError(normalized)
        return facility

    def _weather_payload(self, facility: Facility) -> dict[str, Any]:
        try:
            observation = self._weather_provider.fetch(facility.location)
        except Exception:  # 외부 제공자 장애는 핵심 지도와 HTTP API를 중단하지 않는다.
            observation = WeatherObservation(
                observed_at=dt.datetime.now(KST),
                health=DataHealth.ERROR,
                message="현재 기상 제공자에 연결하지 못했습니다.",
            )
        return serialize_weather(facility.id, observation)

    def _cctv_payload(self, facility: Facility) -> dict[str, Any]:
        try:
            feed = self._cctv_provider.fetch_nearby(
                facility.location,
                radius_km=20,
                limit=5,
            )
        except Exception:  # CCTV 장애 역시 독립적인 참고정보 오류로 격리한다.
            feed = CctvFeed(
                status=ContextStatus.ERROR,
                cctvs=(),
                fetched_at=dt.datetime.now(KST),
                detail="ITS CCTV 제공자에 연결하지 못했습니다.",
            )
        enriched = self._direction_catalog.enrich_feed(feed)
        return serialize_cctv(
            facility.id,
            enriched,
            direction_warning=self._direction_warning,
        )

    def _cached(
        self,
        key: str,
        cache: dict[str, _CacheEntry],
        lock: threading.Lock,
        loader: Callable[[], dict[str, Any]],
        ttl: Callable[[dict[str, Any]], int],
    ) -> dict[str, Any]:
        now = self._monotonic()
        cached = cache.get(key)
        if cached is not None and now < cached.expires_at:
            return cached.value
        with lock:
            now = self._monotonic()
            cached = cache.get(key)
            if cached is not None and now < cached.expires_at:
                return cached.value
            value = loader()
            cache[key] = _CacheEntry(value, now + ttl(value))
            return value
