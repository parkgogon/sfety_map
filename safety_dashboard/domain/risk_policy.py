"""사람이 직접 읽고 수정할 수 있는 TOML 기반 위험도 정책."""

from __future__ import annotations

import datetime as dt
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from safety_dashboard.domain.enums import RiskGrade, WarningLevel
from safety_dashboard.domain.models import Facility, RiskAssessment, RiskReason, Warning


class RiskPolicyError(ValueError):
    """정책 파일의 구조나 값이 유효하지 않을 때 발생합니다."""


RISK_GRADE_COLORS: dict[RiskGrade | str, str] = {
    RiskGrade.HIGH: "#D92D20",
    RiskGrade.MEDIUM: "#C2410C",
    RiskGrade.LOW: "#8A6D00",
    RiskGrade.NONE: "#176B87",
    RiskGrade.UNASSESSED: "#7C3AED",
    "HIGH": "#D92D20",
    "MEDIUM": "#C2410C",
    "LOW": "#8A6D00",
    "NONE": "#176B87",
    "UNASSESSED": "#7C3AED",
}



@dataclass(frozen=True)
class GradeDefinition:
    grade: RiskGrade
    rank: int
    label: str
    meaning: str
    action: str
    color: str



@dataclass(frozen=True)
class RiskPolicy:
    version: str
    description: str
    default_grade: RiskGrade
    grades: Mapping[RiskGrade, GradeDefinition]
    level_aliases: Mapping[str, WarningLevel]
    warning_matrix: Mapping[str, Mapping[WarningLevel, RiskGrade]]

    @classmethod
    def load(cls, path: str | Path) -> "RiskPolicy":
        try:
            with open(path, "rb") as file:
                raw = tomllib.load(file)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise RiskPolicyError(f"위험도 정책을 읽을 수 없습니다: {path}") from exc

        try:
            policy_raw = raw["policy"]
            version = str(policy_raw["version"]).strip()
            description = str(policy_raw.get("description", "")).strip()
            default_grade = RiskGrade(str(policy_raw["default_grade"]))

            grades: dict[RiskGrade, GradeDefinition] = {}
            for name, definition in raw["grades"].items():
                grade = RiskGrade(name)
                grades[grade] = GradeDefinition(
                    grade=grade,
                    rank=int(definition["rank"]),
                    label=str(definition["label"]),
                    meaning=str(definition["meaning"]),
                    action=str(definition["action"]),
                    color=str(definition["color"]),
                )

            aliases = {
                str(alias).strip(): WarningLevel(str(level))
                for alias, level in raw["level_aliases"].items()
            }

            matrix: dict[str, dict[WarningLevel, RiskGrade]] = {}
            for warning_type, levels in raw["warning_types"].items():
                matrix[str(warning_type)] = {
                    WarningLevel(level): RiskGrade(grade)
                    for level, grade in levels.items()
                }
        except (KeyError, TypeError, ValueError) as exc:
            raise RiskPolicyError("위험도 정책의 필수 값이 잘못되었습니다.") from exc

        required_grades = set(RiskGrade)
        if set(grades) != required_grades:
            missing = ", ".join(sorted(g.value for g in required_grades - set(grades)))
            raise RiskPolicyError(f"위험도 등급 정의가 부족합니다: {missing}")
        if not version:
            raise RiskPolicyError("위험도 정책 version이 비어 있습니다.")
        if len({item.rank for item in grades.values()}) != len(grades):
            raise RiskPolicyError("위험도 등급 rank는 서로 달라야 합니다.")

        return cls(
            version=version,
            description=description,
            default_grade=default_grade,
            grades=grades,
            level_aliases=aliases,
            warning_matrix=matrix,
        )

    def normalize_level(self, raw_level: object) -> WarningLevel:
        text = str(raw_level or "").strip()
        if text in self.level_aliases:
            return self.level_aliases[text]
        if any(token in text for token in ("중대", "심각", "위급")):
            return WarningLevel.CRITICAL
        if "경보" in text:
            return WarningLevel.WARNING
        if "주의" in text:
            return WarningLevel.ADVISORY
        return WarningLevel.UNKNOWN

    def classify_warning(self, warning: Warning) -> RiskReason:
        by_level = self.warning_matrix.get(warning.warning_type, {})
        grade = by_level.get(warning.level, self.default_grade)
        return RiskReason(
            warning_id=warning.id,
            warning_type=warning.warning_type,
            raw_level=warning.raw_level,
            grade=grade,
            region=warning.region,
            policy_key=f"{warning.warning_type}.{warning.level.value}",
        )

    def assess(
        self,
        facility: Facility,
        matched_warnings: Iterable[Warning],
        assessed_at: dt.datetime | None = None,
    ) -> RiskAssessment:
        reasons = tuple(self.classify_warning(item) for item in matched_warnings)
        if reasons:
            grade = max(
                (reason.grade for reason in reasons),
                key=lambda item: self.grades[item].rank,
            )
        else:
            grade = RiskGrade.NONE
        return RiskAssessment(
            facility=facility,
            grade=grade,
            reasons=reasons,
            policy_version=self.version,
            assessed_at=assessed_at or dt.datetime.now(),
        )

    def definition(self, grade: RiskGrade) -> GradeDefinition:
        return self.grades[grade]

