"""사람이 검증한 CCTV 촬영 방향을 ITS 조회 결과에 보강합니다."""

from __future__ import annotations

import datetime as dt
import math
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

from safety_dashboard.domain.models import CctvFeed, GeoPoint, NearbyCctv


class CctvDirectionConfigError(ValueError):
    """CCTV 방향 설정이 안전하게 적용될 수 없을 때 발생합니다."""


@dataclass(frozen=True)
class CctvDirection:
    name: str
    location: GeoPoint
    bearing_deg: float
    verified_on: dt.date
    source: str


@dataclass(frozen=True)
class CctvDirectionCatalog:
    entries: tuple[CctvDirection, ...] = ()

    @classmethod
    def empty(cls) -> "CctvDirectionCatalog":
        return cls()

    @classmethod
    def load(cls, path: Path) -> "CctvDirectionCatalog":
        try:
            with path.open("rb") as stream:
                document = tomllib.load(stream)
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            raise CctvDirectionConfigError(
                f"CCTV 방향 설정을 읽을 수 없습니다: {exc}"
            ) from exc

        raw_entries = document.get("directions", [])
        if not isinstance(raw_entries, list):
            raise CctvDirectionConfigError(
                "CCTV 방향 설정의 directions는 목록이어야 합니다."
            )

        entries: list[CctvDirection] = []
        seen: set[tuple[str, float, float]] = set()
        for index, raw_entry in enumerate(raw_entries, start=1):
            if not isinstance(raw_entry, dict):
                raise CctvDirectionConfigError(
                    f"CCTV 방향 {index}번 항목은 TOML 테이블이어야 합니다."
                )
            entry = _parse_entry(raw_entry, index)
            key = _match_key(entry.name, entry.location)
            if key in seen:
                raise CctvDirectionConfigError(
                    f"CCTV 방향 {index}번 항목이 중복됩니다: {entry.name}"
                )
            seen.add(key)
            entries.append(entry)
        return cls(tuple(entries))

    def enrich(self, cctvs: tuple[NearbyCctv, ...]) -> tuple[NearbyCctv, ...]:
        directions = {
            _match_key(item.name, item.location): item for item in self.entries
        }
        enriched: list[NearbyCctv] = []
        for cctv in cctvs:
            direction = directions.get(_match_key(cctv.name, cctv.location))
            if direction is None:
                enriched.append(cctv)
                continue
            enriched.append(
                replace(
                    cctv,
                    bearing_deg=direction.bearing_deg,
                    direction_verified_on=direction.verified_on,
                    direction_source=direction.source,
                )
            )
        return tuple(enriched)

    def enrich_feed(self, feed: CctvFeed) -> CctvFeed:
        return replace(feed, cctvs=self.enrich(feed.cctvs))


def load_cctv_direction_catalog(
    path: Path,
) -> tuple[CctvDirectionCatalog, str]:
    """설정 오류를 방향 표시에만 가두고 빈 catalog로 복구합니다."""

    try:
        return CctvDirectionCatalog.load(path), ""
    except CctvDirectionConfigError as exc:
        return CctvDirectionCatalog.empty(), str(exc)


def direction_label(bearing_deg: float) -> str:
    """북쪽 0도를 기준으로 한 8방위 표기를 반환합니다."""

    labels = ("북", "북동", "동", "남동", "남", "남서", "서", "북서")
    return labels[int((bearing_deg % 360 + 22.5) // 45) % 8]


def format_bearing(bearing_deg: float) -> str:
    value = f"{bearing_deg:.1f}".rstrip("0").rstrip(".")
    return f"{value}°"


def describe_cctv_direction(cctv: NearbyCctv) -> str:
    if cctv.bearing_deg is None:
        return "촬영방향 미확인"
    verified = (
        f"{cctv.direction_verified_on:%Y-%m-%d} 검증"
        if cctv.direction_verified_on
        else "검증일 미확인"
    )
    return (
        f"촬영방향 {direction_label(cctv.bearing_deg)} "
        f"{format_bearing(cctv.bearing_deg)} · {verified}"
    )


def _parse_entry(raw: dict, index: int) -> CctvDirection:
    name = str(raw.get("name", "")).strip()
    source = str(raw.get("source", "")).strip()
    if not name:
        raise CctvDirectionConfigError(
            f"CCTV 방향 {index}번 항목의 name이 비어 있습니다."
        )
    if not source:
        raise CctvDirectionConfigError(
            f"CCTV 방향 {index}번 항목의 source가 비어 있습니다."
        )

    latitude = _finite_number(raw.get("latitude"), "latitude", index)
    longitude = _finite_number(raw.get("longitude"), "longitude", index)
    bearing = _finite_number(raw.get("bearing_deg"), "bearing_deg", index)
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise CctvDirectionConfigError(
            f"CCTV 방향 {index}번 항목의 위도·경도 범위가 잘못되었습니다."
        )
    if not 0 <= bearing < 360:
        raise CctvDirectionConfigError(
            f"CCTV 방향 {index}번 항목의 bearing_deg는 0 이상 360 미만이어야 합니다."
        )

    verified_on = raw.get("verified_on")
    if isinstance(verified_on, str):
        try:
            verified_on = dt.date.fromisoformat(verified_on)
        except ValueError as exc:
            raise CctvDirectionConfigError(
                f"CCTV 방향 {index}번 항목의 verified_on은 YYYY-MM-DD여야 합니다."
            ) from exc
    if not isinstance(verified_on, dt.date) or isinstance(verified_on, dt.datetime):
        raise CctvDirectionConfigError(
            f"CCTV 방향 {index}번 항목의 verified_on이 유효한 날짜가 아닙니다."
        )

    return CctvDirection(
        name=name,
        location=GeoPoint(latitude, longitude),
        bearing_deg=bearing,
        verified_on=verified_on,
        source=source,
    )


def _finite_number(value: object, field_name: str, index: int) -> float:
    if isinstance(value, bool):
        raise CctvDirectionConfigError(
            f"CCTV 방향 {index}번 항목의 {field_name}가 숫자가 아닙니다."
        )
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise CctvDirectionConfigError(
            f"CCTV 방향 {index}번 항목의 {field_name}가 숫자가 아닙니다."
        ) from exc
    if not math.isfinite(number):
        raise CctvDirectionConfigError(
            f"CCTV 방향 {index}번 항목의 {field_name}가 유한한 숫자가 아닙니다."
        )
    return number


def _match_key(name: str, location: GeoPoint) -> tuple[str, float, float]:
    return (
        name.strip(),
        round(location.latitude, 5),
        round(location.longitude, 5),
    )
