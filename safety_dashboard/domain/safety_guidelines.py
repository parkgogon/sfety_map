"""발효 기상특보별 핵심 안전관리 요령 및 대응 지침 도메인 모델."""

from __future__ import annotations

from typing import Sequence

from safety_dashboard.domain.enums import RiskGrade
from safety_dashboard.domain.models import DashboardSnapshot

# 기상특보 종류별 핵심 안전관리 행동 요령 매핑
WARNING_ACTION_GUIDELINES: dict[str, str] = {
    "호우": "지하 수위계·배수펌프 가동 상태 확인 및 사면·옹벽 침하 대비",
    "태풍": "옥외 시설물 사전 결속, 비상전원(UPS) 점검 및 취약지 현장 순찰 강화",
    "강풍": "옥외 측정 타워·안테나 결속 확인 및 비산 위험 자재 고정",
    "폭염": "전기·통신실 냉방 설비 점검 및 야외 현장 점검 시간 조정",
    "대설": "적설 취약 구조물 점검 및 진입로 제설 장비·자재 확보",
    "한파": "배관·유량계 등 동파 취약 부위 보온재 점검 및 난방 가동",
    "풍랑": "해안 인접 측정소 침수·월파 대비 및 옥외 장비 보호",
    "건조": "사업소 및 측정소 주변 인화물질 제거, 소화 장비 점검",
    "황사": "대기측정장비 흡입구 오염 점검 및 실내 환기 필터 관리",
    "폭풍해일": "해안 저지대 시설물 사전 통제 및 침수 대비",
    "지진해일": "해안 인접 시설 즉시 대피 유도 및 긴급 차단시설 점검",
    "안개": "현장 이동 차량 안전운행 및 시야 제한 취약 시설 주의",
    "열대야": "통신·전력설비 과열 방지 점검 및 야간 비상대기 체계 확인",
}

# 기본 평시 안전 수칙
DEFAULT_SAFETY_GUIDELINE = "시설별 정기 안전점검 수칙 준수 및 비상연락체계 상시 유지"


def get_warning_guideline(warning_type: str) -> str:
    """특보 종류에 맞는 안전관리 요령을 반환합니다. 등록되지 않은 특보는 기본 지침을 조합하여 반환합니다."""
    return WARNING_ACTION_GUIDELINES.get(
        warning_type,
        f"{warning_type} 특보 대응 시설별 안전점검 및 비상연락체계 유지",
    )


def extract_safety_guidelines(
    snapshot: DashboardSnapshot, max_items: int = 3
) -> list[tuple[str, str]]:
    """현재 발효된 특보 중 영향도가 큰 특보들의 핵심 안전관리 요령을 추출합니다.

    Returns:
        list of (특보명, 행동요령 문구)
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

    results: list[tuple[str, str]] = []
    for wt in active_warning_types[:max_items]:
        results.append((wt, get_warning_guideline(wt)))
    return results
