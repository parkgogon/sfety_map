"""ITS 국가교통정보센터의 시설 인근 도로 CCTV 연동."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urlsplit

import requests

from safety_dashboard.application.context_info import KST
from safety_dashboard.domain.enums import ContextStatus
from safety_dashboard.domain.models import CctvFeed, GeoPoint, NearbyCctv


DEFAULT_API_URL = "https://openapi.its.go.kr:9443/cctvInfo"
SOURCE_PAGE_URL = "https://its.go.kr/opendata/opendataList?service=cctv"
OFFICIAL_MAP_URL = "https://its.go.kr/map/statistics"

_ROAD_TYPES = {"ex": "고속도로", "its": "국도"}
_PLACEHOLDER_KEYS = {"YOUR_ITS_CCTV_API_KEY", "YOUR_CCTV_API_KEY"}


class CctvDataError(ValueError):
    pass


class ItsCctvProvider:
    def __init__(
        self,
        api_key: str,
        api_url: str = DEFAULT_API_URL,
        timeout: float = 7,
    ) -> None:
        self.api_key = str(api_key or "").strip()
        self.api_url = str(api_url or DEFAULT_API_URL).strip()
        self.timeout = timeout

    def fetch_nearby(
        self,
        location: GeoPoint,
        radius_km: float = 20,
        limit: int = 5,
    ) -> CctvFeed:
        fetched_at = dt.datetime.now(KST)
        if not self.api_key or self.api_key in _PLACEHOLDER_KEYS:
            return CctvFeed(
                status=ContextStatus.NOT_CONFIGURED,
                cctvs=(),
                fetched_at=fetched_at,
                detail="ITS CCTV API 키가 설정되지 않았습니다.",
            )
        if not _valid_point(location) or radius_km <= 0 or limit <= 0:
            return CctvFeed(
                status=ContextStatus.ERROR,
                cctvs=(),
                fetched_at=fetched_at,
                detail="CCTV 조회 범위를 계산할 시설 좌표가 올바르지 않습니다.",
            )

        bounds = _bounding_box(location, radius_km)
        values: list[NearbyCctv] = []
        failures: list[str] = []
        with ThreadPoolExecutor(max_workers=len(_ROAD_TYPES)) as executor:
            futures = {
                executor.submit(self._fetch_road_type, road_code, location, bounds): label
                for road_code, label in _ROAD_TYPES.items()
            }
            for future in as_completed(futures):
                label = futures[future]
                try:
                    values.extend(future.result())
                except (requests.RequestException, CctvDataError, TypeError, ValueError):
                    failures.append(label)

        if len(failures) == len(_ROAD_TYPES):
            return CctvFeed(
                status=ContextStatus.ERROR,
                cctvs=(),
                fetched_at=fetched_at,
                detail="ITS CCTV를 조회하지 못했습니다.",
            )

        nearby = [item for item in values if item.distance_km <= radius_km]
        deduplicated: dict[tuple[str, float, float], NearbyCctv] = {}
        for item in nearby:
            key = (
                item.name.casefold(),
                round(item.location.latitude, 5),
                round(item.location.longitude, 5),
            )
            previous = deduplicated.get(key)
            if previous is None or _video_preference(item) > _video_preference(previous):
                deduplicated[key] = item
        selected = tuple(
            sorted(
                deduplicated.values(),
                key=lambda item: (item.distance_km, item.name),
            )[:limit]
        )
        detail = f"ITS 도로 CCTV · {radius_km:g}km · 가까운 순"
        if failures:
            detail += f" · {'·'.join(sorted(failures))} 일부 조회 실패"
        return CctvFeed(
            status=ContextStatus.LIVE,
            cctvs=selected,
            fetched_at=fetched_at,
            detail=detail,
        )

    def _fetch_road_type(
        self,
        road_code: str,
        origin: GeoPoint,
        bounds: tuple[float, float, float, float],
    ) -> tuple[NearbyCctv, ...]:
        min_x, max_x, min_y, max_y = bounds
        response = requests.get(
            self.api_url,
            params={
                "apiKey": self.api_key,
                "type": road_code,
                "cctvType": 5,
                "minX": round(min_x, 6),
                "maxX": round(max_x, 6),
                "minY": round(min_y, 6),
                "maxY": round(max_y, 6),
                "getType": "json",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        try:
            payload: object = response.json()
        except (requests.JSONDecodeError, ValueError):
            payload = response.text
        return parse_cctv_response(payload, road_code, origin)


def parse_cctv_response(
    payload: object,
    road_code: str,
    origin: GeoPoint,
) -> tuple[NearbyCctv, ...]:
    rows = _response_rows(payload)
    result: list[NearbyCctv] = []
    for row in rows:
        normalized = {_local_name(str(key)).lower(): value for key, value in row.items()}
        try:
            longitude = float(normalized["coordx"])
            latitude = float(normalized["coordy"])
        except (KeyError, TypeError, ValueError):
            continue
        point = GeoPoint(latitude=latitude, longitude=longitude)
        if not _valid_point(point):
            continue
        video_url = str(normalized.get("cctvurl", "")).strip()
        if urlsplit(video_url).scheme.lower() not in ("http", "https"):
            continue
        name = str(normalized.get("cctvname", "")).strip() or "이름 없는 CCTV"
        road_type = _ROAD_TYPES.get(road_code, road_code)
        identifier = hashlib.sha1(
            f"{name}|{latitude:.6f}|{longitude:.6f}".encode("utf-8")
        ).hexdigest()[:16]
        result.append(
            NearbyCctv(
                id=identifier,
                name=name,
                location=point,
                distance_km=_distance_km(origin, point),
                road_type=road_type,
                video_url=video_url,
                video_format=str(normalized.get("cctvformat", "MP4")).strip()
                or "MP4",
                updated_at=_parse_updated_at(normalized.get("filecreatetime")),
            )
        )
    if rows and not result:
        raise CctvDataError("CCTV 응답의 좌표나 영상 URL을 해석할 수 없습니다.")
    return tuple(result)


def _response_rows(payload: object) -> list[Mapping[str, Any]]:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")
    if isinstance(payload, str):
        text = payload.strip()
        if not text:
            return []
        if text.startswith("<"):
            return _xml_rows(text)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CctvDataError("CCTV 응답을 해석할 수 없습니다.") from exc
    if not isinstance(payload, (Mapping, list)):
        raise CctvDataError("CCTV 응답이 JSON 객체가 아닙니다.")
    rows = _json_rows(payload)
    if rows:
        return rows
    if _declared_count(payload) == 0:
        return []
    raise CctvDataError("CCTV 목록을 찾을 수 없습니다.")


def _json_rows(value: object) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        keys = {_local_name(str(key)).lower() for key in value}
        if {"coordx", "coordy", "cctvurl"}.issubset(keys):
            return [value]
        result: list[Mapping[str, Any]] = []
        for item in value.values():
            result.extend(_json_rows(item))
        return result
    if isinstance(value, list):
        result = []
        for item in value:
            result.extend(_json_rows(item))
        return result
    return []


def _xml_rows(text: str) -> list[Mapping[str, Any]]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise CctvDataError("CCTV XML 응답을 해석할 수 없습니다.") from exc
    rows = [
        {_local_name(child.tag).lower(): child.text or "" for child in item}
        for item in root.iter()
        if _local_name(item.tag).lower() == "data"
    ]
    if rows:
        return rows
    counts = [
        str(item.text or "").strip()
        for item in root.iter()
        if _local_name(item.tag).lower() in ("datacount", "totalcount")
    ]
    if counts and all(value in ("", "0") for value in counts):
        return []
    raise CctvDataError("CCTV XML 목록을 찾을 수 없습니다.")


def _declared_count(value: object) -> int | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _local_name(str(key)).lower() in ("datacount", "totalcount"):
                try:
                    return int(item)
                except (TypeError, ValueError):
                    pass
            nested = _declared_count(item)
            if nested is not None:
                return nested
    elif isinstance(value, list):
        for item in value:
            nested = _declared_count(item)
            if nested is not None:
                return nested
    return None


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def _parse_updated_at(value: object) -> dt.datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for pattern in ("%Y%m%d%H%M%S", "%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M"):
        try:
            return dt.datetime.strptime(text, pattern).replace(tzinfo=KST)
        except ValueError:
            continue
    return None


def _bounding_box(
    location: GeoPoint,
    radius_km: float,
) -> tuple[float, float, float, float]:
    latitude_delta = radius_km / 111.32
    longitude_scale = max(math.cos(math.radians(location.latitude)), 0.01)
    longitude_delta = radius_km / (111.32 * longitude_scale)
    return (
        location.longitude - longitude_delta,
        location.longitude + longitude_delta,
        location.latitude - latitude_delta,
        location.latitude + latitude_delta,
    )


def _distance_km(first: GeoPoint, second: GeoPoint) -> float:
    radius = 6371.0088
    lat1, lat2 = math.radians(first.latitude), math.radians(second.latitude)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(second.longitude - first.longitude)
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _valid_point(point: GeoPoint) -> bool:
    return (
        math.isfinite(point.latitude)
        and math.isfinite(point.longitude)
        and -90 <= point.latitude <= 90
        and -180 <= point.longitude <= 180
    )


def _video_preference(item: NearbyCctv) -> tuple[bool, bool]:
    return (
        "MP4" in item.video_format.upper(),
        urlsplit(item.video_url).scheme.lower() == "https",
    )
