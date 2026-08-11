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
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], dt.datetime] = lambda: dt.datetime.now(KST),
    ) -> None:
        self.settings = settings
        self._setup_error = ""
        if provider is not None:
            self._provider: WeatherLayerFetcher | None = provider
        else:
            try:
                scope = load_monitoring_scope(settings.zone_fallback_path)
                self._provider = GridWeatherLayerProvider(
                    settings.kma_api_key,
                    scope,
                    timeout=7,
                )
            except (OSError, ValueError, TypeError, KeyError):
                self._provider = None
                self._setup_error = "기상 레이어 관제 권역을 준비하지 못했습니다."
        self._monotonic = monotonic
        self._now = now
        self._cache: dict[WeatherLayerKind, _CacheEntry] = {}
        self._last_success: dict[WeatherLayerKind, WeatherLayerFeed] = {}
        self._lock = threading.Lock()

    def layer(self, kind: WeatherLayerKind) -> dict[str, Any]:
        current = self._monotonic()
        cached = self._cache.get(kind)
        if cached is not None and current < cached.expires_at:
            return cached.value
        with self._lock:
            current = self._monotonic()
            cached = self._cache.get(kind)
            if cached is not None and current < cached.expires_at:
                return cached.value
            feed = self._fetch(kind)
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
            self._cache[kind] = _CacheEntry(value, current + ttl)
            return value

    def _fetch(self, kind: WeatherLayerKind) -> WeatherLayerFeed:
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
