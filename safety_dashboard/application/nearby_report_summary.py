"""지도 캡처 입력과 보고서 요약. 시설 선정은 운영 보고서와 같은 NearbyReport만 사용한다."""
from __future__ import annotations

from collections import Counter
import math

from safety_dashboard.adapters.nearby_pdf_report import report_text
from safety_dashboard.application.nearby_report import EARTH_RADIUS_METERS, NearbyReport


def destination(latitude: float, longitude: float, meters: float, bearing: float) -> dict:
    lat, lon, angle = map(math.radians, (latitude, longitude, bearing))
    distance = meters / EARTH_RADIUS_METERS
    end_lat = math.asin(math.sin(lat) * math.cos(distance)
                        + math.cos(lat) * math.sin(distance) * math.cos(angle))
    end_lon = lon + math.atan2(math.sin(angle) * math.sin(distance) * math.cos(lat),
                               math.cos(distance) - math.sin(lat) * math.sin(end_lat))
    return {"latitude": math.degrees(end_lat), "longitude": math.degrees(end_lon)}


def summary(report: NearbyReport) -> dict:
    """반올림 전 거리로 구간을 나눈다. 0m와 경계 시설도 한 번씩 센다."""
    rows = report.facilities
    cuts = sorted({min(value, report.radius_km) for value in (1, 3, 5, report.radius_km)})
    bands, lower = [], 0.0
    for upper in cuts:
        count = sum((lower * 1000 < row.meters <= upper * 1000)
                    or (lower == 0 and row.meters == 0) for row in rows)
        bands.append({"label": f"{lower:g}–{upper:g}km", "count": count})
        lower = upper
    def counts(attribute):
        result = Counter(report_text(getattr(row.facility, attribute)) for row in rows)
        return [{"label": label, "count": count}
                for label, count in sorted(result.items(), key=lambda item: (-item[1], item[0]))]
    return {"count": len(rows), "nearest_meters": rows[0].meters if rows else None,
            "types": counts("facility_type"), "departments": counts("department"), "bands": bands}


def capture_input(report: NearbyReport, case_id: str, *, synthetic: bool = False) -> dict:
    return {"id": case_id, "label": report_text(report.label), "address": report_text(report.address),
            "generated_at": report.generated_at.isoformat(),
            "latitude": report.point.latitude, "longitude": report.point.longitude,
            "radius_km": report.radius_km, "synthetic": synthetic, "summary": summary(report),
            "circle": [destination(report.point.latitude, report.point.longitude,
                                   report.radius_km * 1000, angle * 3.75) for angle in range(96)],
            "facilities": [{"id": row.facility.id, "number": index + 1,
                            "latitude": row.facility.location.latitude,
                            "longitude": row.facility.location.longitude}
                           for index, row in enumerate(report.facilities)]}
