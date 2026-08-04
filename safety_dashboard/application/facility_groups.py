"""수정 가능한 시설 유형 그룹과 원본 시설 유형의 연결."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from safety_dashboard.domain.models import Facility


class FacilityGroupError(ValueError):
    """시설 그룹 설정이 모호하거나 필수 값이 없을 때 발생합니다."""


@dataclass(frozen=True)
class FacilityGroup:
    id: str
    label: str
    facility_types: tuple[str, ...]
    fallback: bool = False


@dataclass(frozen=True)
class FacilityGroupCatalog:
    groups: tuple[FacilityGroup, ...]

    @classmethod
    def load(cls, path: str | Path) -> "FacilityGroupCatalog":
        try:
            with open(path, "rb") as file:
                raw = tomllib.load(file)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise FacilityGroupError(f"시설 그룹 설정을 읽을 수 없습니다: {path}") from exc

        try:
            groups = tuple(
                FacilityGroup(
                    id=str(group_id).strip(),
                    label=str(values["label"]).strip(),
                    facility_types=tuple(
                        str(item).strip()
                        for item in values.get("facility_types", ())
                        if str(item).strip()
                    ),
                    fallback=bool(values.get("fallback", False)),
                )
                for group_id, values in raw["groups"].items()
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise FacilityGroupError("시설 그룹 설정의 필수 값이 잘못되었습니다.") from exc

        if not groups or any(not item.id or not item.label for item in groups):
            raise FacilityGroupError("시설 그룹 ID와 표시명은 비워둘 수 없습니다.")
        fallback_groups = [item for item in groups if item.fallback]
        if len(fallback_groups) != 1:
            raise FacilityGroupError("fallback 시설 그룹은 정확히 하나여야 합니다.")

        owners: dict[str, str] = {}
        for group in groups:
            for facility_type in group.facility_types:
                if facility_type in owners:
                    raise FacilityGroupError(
                        f"시설 유형이 여러 그룹에 중복되었습니다: {facility_type}"
                    )
                owners[facility_type] = group.id
        return cls(groups=groups)

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(item.id for item in self.groups)

    def definition(self, group_id: str) -> FacilityGroup:
        try:
            return next(item for item in self.groups if item.id == group_id)
        except StopIteration as exc:
            raise FacilityGroupError(f"알 수 없는 시설 그룹입니다: {group_id}") from exc

    def group_for_type(self, facility_type: str) -> FacilityGroup:
        for group in self.groups:
            if facility_type in group.facility_types:
                return group
        return next(item for item in self.groups if item.fallback)

    def facility_ids_for_groups(
        self,
        facilities: Iterable[Facility],
        group_ids: Iterable[str],
    ) -> frozenset[str]:
        selected = frozenset(group_ids)
        unknown = selected.difference(self.ids)
        if unknown:
            raise FacilityGroupError(
                f"알 수 없는 시설 그룹입니다: {', '.join(sorted(unknown))}"
            )
        return frozenset(
            facility.id
            for facility in facilities
            if self.group_for_type(facility.facility_type).id in selected
        )

    def counts(self, facilities: Iterable[Facility]) -> dict[str, int]:
        result = {item.id: 0 for item in self.groups}
        for facility in facilities:
            result[self.group_for_type(facility.facility_type).id] += 1
        return result
