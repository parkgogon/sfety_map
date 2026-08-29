"""React 지도의 기상 레이어를 독립적으로 캐시하고 오류를 격리합니다."""

from __future__ import annotations

import datetime as dt
import threading
import time
from dataclasses import dataclass, replace
from typing import Any, Callable, Protocol

from safety_dashboard.adapters.weather_layers import (
    GridWeatherLayerProvider,
    KST,
    load_monitoring_scope,
)
from safety_dashboard.api.serialization import serialize_weather_layer
from safety_dashboard.api.settings import ApiSettings
from safety_dashboard.domain.enums import DataHealth, WeatherLayerKind
from safety_dashboard.domain.models import WeatherLayerFeed
from safety_dashboard.simulation.weather_layers import (
    SimulationWeatherLayerProvider,
)


class WeatherLayerFetcher(Protocol):
    def fetch(
        self,
        kind: WeatherLayerKind,
        now: dt.datetime | None = None,
    ) -> WeatherLayerFeed: ...


@dataclass(frozen=True)
class _CacheEntry:
    value: dict[str, Any]
    expires_at: float


class WeatherLayerService:
    def __init__(
        self,
        settings: ApiSettings,
        *,
        provider: WeatherLayerFetcher | None = None,
        simulation_provider: WeatherLayerFetcher | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], dt.datetime] = lambda: dt.datetime.now(KST),
    ) -> None:
        self.settings = settings
        self._setup_error = ""
        self._scope = None

        if provider is not None:
            self._provider: WeatherLayerFetcher | None = provider
        else:
            try:
                self._scope = load_monitoring_scope(settings.zone_fallback_path)
                self._provider = GridWeatherLayerProvider(
                    settings.kma_api_key,
                    self._scope,
                    timeout=7,
                )
            except (OSError, ValueError, TypeError, KeyError):
                self._provider = None
                self._setup_error = "기상 레이어 관제 권역을 준비하지 못했습니다."

        if simulation_provider is not None:
            self._simulation_provider: WeatherLayerFetcher | None = (
                simulation_provider
            )
        else:
            try:
                if self._scope is None:
                    self._scope = load_monitoring_scope(
                        settings.zone_fallback_path
                    )
                self._simulation_provider = SimulationWeatherLayerProvider(
                    self._scope
                )
            except (OSError, ValueError, TypeError, KeyError):
                self._simulation_provider = None

        self._monotonic = monotonic
        self._now = now
        self._cache: dict[tuple[str, WeatherLayerKind], _CacheEntry] = {}
        self._last_success: dict[WeatherLayerKind, WeatherLayerFeed] = {}
        self._lock = threading.Lock()

    def layer(
        self, kind: WeatherLayerKind, mode: str = "live"
    ) -> dict[str, Any]:
        normalized_mode = "simulation" if mode == "simulation" else "live"
        cache_key = (normalized_mode, kind)
        current = self._monotonic()
        cached = self._cache.get(cache_key)
        if cached is not None and current < cached.expires_at:
            return cached.value

        with self._lock:
            current = self._monotonic()
            cached = self._cache.get(cache_key)
            if cached is not None and current < cached.expires_at:
                return cached.value

            if normalized_mode == "simulation":
                feed = self._fetch_simulation(kind)
                ttl = self.settings.weather_layer_cache_seconds
            else:
                feed = self._fetch_live(kind)
                if feed.health is DataHealth.LIVE:
                    self._last_success[kind] = feed
                    ttl = self.settings.weather_layer_cache_seconds
                else:
                    previous = self._last_success.get(kind)
                    if previous is not None:
                        feed = replace(
                            previous,
                            health=DataHealth.STALE,
                            fetched_at=self._now(),
                            message=(
                                f"{feed.message} 마지막 정상 자료를 표시합니다."
                            ),
                        )
                    ttl = self.settings.weather_layer_error_cache_seconds

            value = serialize_weather_layer(feed)
            self._cache[cache_key] = _CacheEntry(value, current + ttl)
            return value

    def _fetch_live(self, kind: WeatherLayerKind) -> WeatherLayerFeed:
        if self._provider is None:
            moment = self._now()
            return WeatherLayerFeed(
                kind=kind,
                health=DataHealth.ERROR,
                observed_at=moment,
                fetched_at=moment,
                unit={
                    WeatherLayerKind.TEMPERATURE: "℃",
                    WeatherLayerKind.RAINFALL: "mm",
                    WeatherLayerKind.WIND: "m/s",
                }[kind],
                points=(),
                message=self._setup_error,
            )
        try:
            return self._provider.fetch(kind)
        except Exception:
            moment = self._now()
            return WeatherLayerFeed(
                kind=kind,
                health=DataHealth.ERROR,
                observed_at=moment,
                fetched_at=moment,
                unit={
                    WeatherLayerKind.TEMPERATURE: "℃",
                    WeatherLayerKind.RAINFALL: "mm",
                    WeatherLayerKind.WIND: "m/s",
                }[kind],
                points=(),
                message="기상 격자 제공자에 연결하지 못했습니다.",
            )

    def _fetch_simulation(self, kind: WeatherLayerKind) -> WeatherLayerFeed:
        if self._simulation_provider is None:
            moment = self._now()
            return WeatherLayerFeed(
                kind=kind,
                health=DataHealth.ERROR,
                observed_at=moment,
                fetched_at=moment,
                unit={
                    WeatherLayerKind.TEMPERATURE: "℃",
                    WeatherLayerKind.RAINFALL: "mm",
                    WeatherLayerKind.WIND: "m/s",
                }[kind],
                points=(),
                message="모의훈련 기상 격자 생성기를 준비하지 못했습니다.",
            )
        try:
            return self._simulation_provider.fetch(kind)
        except Exception:
            moment = self._now()
            return WeatherLayerFeed(
                kind=kind,
                health=DataHealth.ERROR,
                observed_at=moment,
                fetched_at=moment,
                unit={
                    WeatherLayerKind.TEMPERATURE: "℃",
                    WeatherLayerKind.RAINFALL: "mm",
                    WeatherLayerKind.WIND: "m/s",
                }[kind],
                points=(),
                message="모의훈련 기상 격자를 생성하지 못했습니다.",
            )
