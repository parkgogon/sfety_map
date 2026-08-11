"""표준 라이브러리만 사용하는 시설 CSV 저장소."""

from __future__ import annotations

import csv
from pathlib import Path

from safety_dashboard.domain.models import Facility, GeoPoint


class FacilityDataError(ValueError):
    pass


class CsvFacilityRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def list_monitored(self) -> tuple[Facility, ...]:
        try:
            with self.path.open(encoding="utf-8-sig", newline="") as file:
                reader = csv.DictReader(file)
                fieldnames = set(reader.fieldnames or ())
                rows = tuple(reader)
        except OSError as exc:
            raise FacilityDataError(f"시설 파일을 읽을 수 없습니다: {self.path}") from exc
        required = {
            "name", "address", "latitude", "longitude", "시설코드", "시설구분"
        }
        if not required.issubset(fieldnames):
            raise FacilityDataError("시설 CSV 필수 열이 없습니다.")

        result: list[Facility] = []
        seen_ids: set[str] = set()
        for index, row in enumerate(rows, start=1):
            name = str(row.get("name", "") or "").strip()
            address = str(row.get("address", "") or "").strip()
            facility_type = str(row.get("시설구분", "") or "").strip()
            raw_id = str(row.get("시설코드", "") or "").strip()
            if not name or not address or not facility_type or not raw_id:
                raise FacilityDataError(
                    f"{index}행 시설 ID·이름·주소·시설구분은 비워둘 수 없습니다."
                )
            facility_id = raw_id.removesuffix(".0")
            if facility_id in seen_ids:
                raise FacilityDataError(f"시설 ID가 중복되었습니다: {facility_id}")
            try:
                latitude = float(row["latitude"])
                longitude = float(row["longitude"])
            except (TypeError, ValueError) as exc:
                raise FacilityDataError(f"{index}행 시설 좌표가 잘못되었습니다.") from exc
            if not 33 <= latitude <= 39.5 or not 124 <= longitude <= 132:
                raise FacilityDataError(f"{index}행 시설 좌표가 국내 범위를 벗어납니다.")
            result.append(
                Facility(
                    id=facility_id,
                    name=name,
                    facility_type=facility_type,
                    location=GeoPoint(latitude, longitude),
                    address=address,
                    department=str(row.get("담당부서", "-")).strip() or "-",
                    manager=str(row.get("부서 담당자", "-")).strip() or "-",
                    metadata={key: value for key, value in row.items() if key not in required},
                )
            )
            seen_ids.add(facility_id)
        return tuple(result)
