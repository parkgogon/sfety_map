"""기본 파일을 변경하지 않는 세션용 위험도 정책 생성."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Mapping

from safety_dashboard.domain.enums import RiskGrade, WarningLevel
from safety_dashboard.domain.risk_policy import RiskPolicy, RiskPolicyError


EDITABLE_LEVELS = (
    WarningLevel.ADVISORY,
    WarningLevel.WARNING,
    WarningLevel.CRITICAL,
)


def session_policy(
    base_policy: RiskPolicy,
    matrix_values: Mapping[str, Mapping[str, str]],
) -> RiskPolicy:
    """문자열 행렬을 검증하고 해시 버전이 붙은 임시 정책을 반환합니다."""

    matrix: dict[str, dict[WarningLevel, RiskGrade]] = {}
    try:
        for raw_type, raw_levels in matrix_values.items():
            warning_type = str(raw_type).strip()
            if not warning_type:
                raise RiskPolicyError("특보 종류가 비어 있습니다.")
            matrix[warning_type] = {
                level: RiskGrade(str(raw_levels[level.value]))
                for level in EDITABLE_LEVELS
            }
    except (KeyError, TypeError, ValueError) as exc:
        raise RiskPolicyError("세션 위험도 행렬의 값이 잘못되었습니다.") from exc
    if not matrix:
        raise RiskPolicyError("세션 위험도 행렬이 비어 있습니다.")

    signature = "|".join(
        f"{warning_type}:{level.value}:{matrix[warning_type][level].value}"
        for warning_type in sorted(matrix)
        for level in EDITABLE_LEVELS
    )
    digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:8]
    return replace(
        base_policy,
        version=f"{base_policy.version}-session-{digest}",
        description=f"{base_policy.description} · 현재 브라우저 임시 기준",
        warning_matrix=matrix,
    )


def editable_matrix(
    policy: RiskPolicy,
    additional_warning_types: tuple[str, ...] = (),
) -> dict[str, dict[str, str]]:
    """UI와 session state에 저장할 문자열 행렬을 만듭니다."""

    warning_types = list(policy.warning_matrix)
    warning_types.extend(
        warning_type
        for warning_type in additional_warning_types
        if warning_type and warning_type not in policy.warning_matrix
    )
    return {
        warning_type: {
            level.value: policy.warning_matrix.get(warning_type, {}).get(
                level,
                RiskGrade.UNASSESSED,
            ).value
            for level in EDITABLE_LEVELS
        }
        for warning_type in warning_types
    }


def is_session_policy(policy: RiskPolicy) -> bool:
    return "-session-" in policy.version
