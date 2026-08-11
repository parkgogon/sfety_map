"""배포 전에 시설 CSV와 시설 유형 설정을 검증하는 명령."""

from __future__ import annotations

from safety_dashboard.adapters.facility_csv import CsvFacilityRepository
from safety_dashboard.api.settings import ApiSettings
from safety_dashboard.application.facility_groups import FacilityGroupCatalog


def main() -> None:
    settings = ApiSettings.from_environment()
    facilities = CsvFacilityRepository(settings.facility_path).list_monitored()
    catalog = FacilityGroupCatalog.load(settings.group_path)
    counts = catalog.counts(facilities)
    print(f"시설 데이터 정상: 전체 {len(facilities)}개")
    for group in catalog.groups:
        print(f"- {group.label}: {counts[group.id]}개")


if __name__ == "__main__":
    main()
