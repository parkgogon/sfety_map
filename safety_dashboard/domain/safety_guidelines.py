"""발효 기상특보별 핵심 안전관리 요령 및 대응 지침 도메인 모델."""

from __future__ import annotations

from typing import Sequence

from safety_dashboard.domain.enums import RiskGrade
from safety_dashboard.domain.models import DashboardSnapshot

# 기상특보 종류별 핵심 안전관리 행동 요령 매핑 (최대 2~3개 핵심 Action Item 배열)
WARNING_ACTION_GUIDELINES: dict[str, tuple[str, ...]] = {
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


def get_warning_guideline(warning_type: str) -> tuple[str, ...]:
    """특보 종류에 맞는 안전관리 요령 Action Item들을 반환합니다."""
    return WARNING_ACTION_GUIDELINES.get(
        warning_type,
        (f"{warning_type} 특보 대비 안전점검", "비상연락체계 유지"),
    )


def extract_safety_guidelines(
    snapshot: DashboardSnapshot, max_items: int = 3
) -> list[tuple[str, tuple[str, ...]]]:
    """현재 발효된 특보 중 영향도가 큰 특보들의 핵심 안전관리 요령을 추출합니다.

    Returns:
        list of (특보명, (행동요령1, 행동요령2))
    """
    active_warning_types: list[str] = []

    # 위험도 [상], [중] 시설에 걸린 특보 우선 추출
    for assessment in snapshot.assessments:
        if assessment.grade in (RiskGrade.HIGH, RiskGrade.MEDIUM):
            for reason in assessment.reasons:
                wt = reason.warning_type
                if wt and wt not in active_warning_types:
                    active_warning_types.append(wt)

    # 전체 활성 특보 피드에서도 보충
    for warning in snapshot.warning_feed.warnings:
        wt = getattr(warning, "warning_type", str(warning))
        if wt and wt not in active_warning_types:
            active_warning_types.append(wt)

    if not active_warning_types:
        return [("평시", DEFAULT_SAFETY_GUIDELINE)]

    results: list[tuple[str, tuple[str, ...]]] = []
    for wt in active_warning_types[:max_items]:
        results.append((wt, get_warning_guideline(wt)))
    return results
