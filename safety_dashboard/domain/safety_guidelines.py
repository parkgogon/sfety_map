"""발효 기상특보별 핵심 안전관리 요령 및 대응 지침 도메인 모델."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from safety_dashboard.domain.enums import RiskGrade, WarningLevel
from safety_dashboard.domain.models import DashboardSnapshot

# 기상청 공식 지원 기상특보 13종 전체 목록
SUPPORTED_WARNING_TYPES: tuple[str, ...] = (
    "호우", "태풍", "강풍", "폭염", "대설", "한파",
    "풍랑", "건조", "황사", "폭풍해일", "지진해일", "안개", "열대야",
)

# 기본 Master 안전관리 행동요령 (2~3개 단문 Action Items)
_DEFAULT_ACTION_GUIDELINES: dict[str, tuple[str, ...]] = {
    "호우": (
        "수위계·배수펌프 가동상태 확인",
        "사면·옹벽 침하 여부 점검",
    ),
    "태풍": (
        "옥외 시설물 사전 결속 및 고정",
        "비상전원(UPS) 점검 및 순찰 강화",
    ),
    "강풍": (
        "옥외 측정타워·안테나 결속 확인",
        "비산 위험 자재 결속 및 고정",
    ),
    "폭염": (
        "전기·통신실 냉방설비 가동 점검",
        "야외 현장 점검 시간대 조정",
    ),
    "대설": (
        "적설 취약 구조물 사전 점검",
        "진입로 제설 장비·자재 확보",
    ),
    "한파": (
        "배관·유량계 보온재 동파 점검",
        "시설 난방설비 정상 가동 유지",
    ),
    "풍랑": (
        "해안 인접 측정소 침수·월파 대비",
        "옥외 장비 결속 및 안전구역 이동",
    ),
    "건조": (
        "사업소 주변 가연물·인화물질 제거",
        "소화 장비 및 방화 설비 점검",
    ),
    "황사": (
        "대기측정장비 흡입구 오염 점검",
        "실내 환기 필터 청결 상태 관리",
    ),
    "폭풍해일": (
        "해안 저지대 시설물 사전 통제",
        "배수구 이물질 제거 및 침수 대비",
    ),
    "지진해일": (
        "해안 인접 시설 즉시 대피 유도",
        "긴급 전원·차단시설 작동 점검",
    ),
    "안개": (
        "현장 이동 차량 서행 및 안전운행",
        "시야 제한 취약 시설 주의 순찰",
    ),
    "열대야": (
        "통신·전력설비 과열 방지 점검",
        "야간 비상대기 및 모니터링 유지",
    ),
}

# 기본 평시 안전 수칙
DEFAULT_SAFETY_GUIDELINE: tuple[str, ...] = (
    "시설별 정기 안전점검 수칙 준수",
    "비상연락망 상시 가동 유지",
)

# 미매핑 특보 발생 시 안전 Fallback
FALLBACK_SAFETY_GUIDELINE: tuple[str, ...] = (
    "해당 특보의 표준 안전관리요령을 확인하십시오.",
    "현장 비상연락체계를 유지하십시오.",
)


@dataclass(frozen=True)
class SafetyGuidelineMaster:
    """안전관리요령 마스터 모델 (버전 추적 및 단문 Action Items 관리)."""

    version: str = "2026.08-v1"
    effective_from: str = "2026-08-01"
    guidelines: dict[str, tuple[str, ...]] = field(
        default_factory=lambda: dict(_DEFAULT_ACTION_GUIDELINES)
    )

    def has_mapping(self, warning_type: str) -> bool:
        """해당 기상특보 종류의 안전관리요령이 마스터에 등록되어 있는지 확인합니다."""
        return warning_type in self.guidelines

    def get_guideline(self, warning_type: str) -> tuple[str, ...]:
        """특보 종류에 맞는 안전관리 요령 Action Item들을 반환합니다 (미등록 시 Fallback 반환)."""
        return self.guidelines.get(warning_type, FALLBACK_SAFETY_GUIDELINE)


# 전역 기본 마스터 싱글톤 인스턴스
DEFAULT_GUIDELINE_MASTER = SafetyGuidelineMaster()
WARNING_ACTION_GUIDELINES = DEFAULT_GUIDELINE_MASTER.guidelines


def get_warning_guideline(warning_type: str) -> tuple[str, ...]:
    """특보 종류에 맞는 안전관리 요령 Action Item들을 반환합니다."""
    return DEFAULT_GUIDELINE_MASTER.get_guideline(warning_type)


def extract_safety_guidelines(
    snapshot: DashboardSnapshot,
    max_items: int = 2,
    master: SafetyGuidelineMaster | None = None,
) -> list[tuple[str, tuple[str, ...]]]:
    """현재 발효된 특보 중 영향도와 우선순위가 높은 특보들의 핵심 안전관리 요령을 추출합니다.

    우선순위:
      1. 경보(WARNING/CRITICAL) 발효 특보
      2. 영향시설 수(HIGH, MEDIUM)가 많은 특보
      3. 활성 특보 피드에 존재하는 특보

    Returns:
        list of (특보명, (행동요령1, 행동요령2))
    """
    g_master = master or DEFAULT_GUIDELINE_MASTER
    warning_scores: dict[str, int] = {}

    # 1. 영향시설 평가 결과에서 특보별 영향도 점수 산출
    for assessment in snapshot.assessments:
        weight = 3 if assessment.grade is RiskGrade.HIGH else 2 if assessment.grade is RiskGrade.MEDIUM else 1 if assessment.grade is RiskGrade.LOW else 0
        for reason in assessment.reasons:
            wt = reason.warning_type
            if wt:
                # 경보 가산점
                level_bonus = 5 if "경보" in reason.raw_level else 2
                warning_scores[wt] = warning_scores.get(wt, 0) + weight + level_bonus

    # 2. 전체 활성 특보 피드에서도 등록 (기본 점수 1점)
    for warning in snapshot.warning_feed.warnings:
        wt = getattr(warning, "warning_type", str(warning))
        if wt:
            level_bonus = 3 if warning.level in (WarningLevel.WARNING, WarningLevel.CRITICAL) else 1
            warning_scores[wt] = warning_scores.get(wt, 0) + level_bonus

    if not warning_scores:
        return [("평시", DEFAULT_SAFETY_GUIDELINE)]

    # 점수 내림차순 정렬
    sorted_warning_types = sorted(warning_scores.keys(), key=lambda k: warning_scores[k], reverse=True)

    results: list[tuple[str, tuple[str, ...]]] = []
    for wt in sorted_warning_types[:max_items]:
        results.append((wt, g_master.get_guideline(wt)))

    return results
