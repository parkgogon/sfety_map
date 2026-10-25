"""연락처를 제외한 실제 CSV 입력과 명시한 합성 경계 입력. 외부 통신 없음."""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from safety_dashboard.adapters.facility_csv import CsvFacilityRepository
from safety_dashboard.application.nearby_report import KST, NearbyReport
from safety_dashboard.domain.models import Facility, GeoPoint
from design.nearby_report.model import capture_input, destination


def build_cases():
    catalog = CsvFacilityRepository(ROOT / "facilities_info.csv").list_monitored()
    generated_at = dt.datetime.now(KST).replace(microsecond=0)
    references = [("urban", 35.8714, 128.6014, "동인청사 인근", "대구광역시 중구 동인동"),
                  ("rural", 36.3526, 128.6970, "의성읍 중심 인근", "경상북도 의성군 의성읍"),
                  ("coast", 36.0320, 129.3650, "포항 영일대 인근", "경상북도 포항시 북구 해안 인근")]
    cases = []
    for category, lat, lon, label, address in references:
        for radius in (0.1, 1, 3, 5, 50):
            report = NearbyReport.build(GeoPoint(lat, lon), label, address, radius,
                                        catalog, generated_at=generated_at)
            case_id = f"{category}-{radius:g}km"
            cases.append((capture_input(report, case_id), report))
    point = GeoPoint(35.8714, 128.6014)
    synthetic = []
    for i in range(195):
        pos = destination(point.latitude, point.longitude, (i % 30) * 140, (i * 47) % 360)
        synthetic.append(Facility(f"synthetic-{i:03}", f"검수용 시설 {i:03}",
                                  "합성 시설 유형 " + str(i % 7 + 1), GeoPoint(**pos),
                                  "합성 주소 · 실제 시설 아님", "합성 담당부서 " + str(i % 4 + 1)))
    synthetic[1] = dataclasses.replace(synthetic[1], name=synthetic[0].name, location=synthetic[0].location)
    synthetic[-1] = dataclasses.replace(synthetic[-1], name="긴 한글 시설명 " * 20 + "마지막시설",
                                        address="페이지 분할 검수용 긴 한글 주소 " * 300)
    report = NearbyReport.build(point, "합성 195개 시설 검수", "실제 시설·사건 자료 아님", 5,
                                synthetic, generated_at=generated_at)
    cases.append((capture_input(report, "synthetic-dense-long", synthetic=True), report))
    return cases


if __name__ == "__main__":
    print(json.dumps([item for item, _ in build_cases()], ensure_ascii=False))
