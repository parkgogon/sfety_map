"""
시설물 위험도 산정 엔진 (Risk Assessment Engine)

특보 데이터를 기반으로 각 시설물의 위험도를 산정하고
상(High) / 중(Medium) / 하(Low) 등급으로 분류합니다.

설계 원칙:
- 점수 합산(additive) 방식: 여러 위험 요소의 점수를 합산
- 향후 홍수통제소, 산림청 등 추가 데이터 소스의 위험 점수도 합산 가능
- 시설구분별 취약도 가중치도 추후 추가 가능

현재 지원 데이터 소스:
- 기상청 특보 (특보 종류 × 등급 배수)
"""

from typing import Dict, List, Optional, Tuple
import pandas as pd

from core.region_resolver import facility_matches_warning


# =============================================
# 1. 특보 종류별 기본 가중치 (Base Risk Score)
# =============================================
WARNING_TYPE_WEIGHTS: Dict[str, int] = {
    "태풍": 5,
    "호우": 4,
    "대설": 4,
    "폭풍해일": 4,
    "강풍": 3,
    "풍랑": 3,
    "한파": 3,
    "폭염": 2,
    "열대야": 2,
    "건조": 2,
    "황사": 2,
    "안개": 1,
}

# =============================================
# 2. 특보 등급별 배수 (Level Multiplier)
# =============================================
WARNING_LEVEL_MULTIPLIER: Dict[str, float] = {
    "주의": 1.0,
    "주의보": 1.0,
    "경보": 1.5,
    "중대경보": 2.0,
}

# =============================================
# 3. 등급 분류 임계값
# =============================================
GRADE_THRESHOLDS = {
    "상": 7,   # 7점 이상
    "중": 4,   # 4~6점
    "하": 1,   # 1~3점
}


def calculate_warning_score(warning_type: str, warning_level: str) -> float:
    """
    단일 특보에 대한 위험도 점수를 계산합니다.

    Args:
        warning_type: 특보 종류 (예: "호우", "태풍")
        warning_level: 특보 등급 (예: "주의보", "경보")

    Returns:
        float: 위험도 점수
    """
    base = WARNING_TYPE_WEIGHTS.get(warning_type, 1)
    multiplier = WARNING_LEVEL_MULTIPLIER.get(warning_level, 1.0)
    return base * multiplier


def classify_grade(score: float) -> str:
    """
    종합 위험도 점수를 상/중/하 등급으로 분류합니다.

    Args:
        score: 종합 위험도 점수

    Returns:
        str: "상", "중", "하", 또는 "없음"
    """
    if score >= GRADE_THRESHOLDS["상"]:
        return "상"
    elif score >= GRADE_THRESHOLDS["중"]:
        return "중"
    elif score >= GRADE_THRESHOLDS["하"]:
        return "하"
    else:
        return "없음"


def assess_facility_risk(
    facility_row: pd.Series,
    warnings_df: pd.DataFrame,
    additional_scores: Optional[List[Dict]] = None,
) -> Dict:
    """
    개별 시설물의 위험도를 산정합니다.

    한 시설물이 여러 특보에 동시 해당될 경우, 가장 높은 점수를 최종 위험도로 사용합니다.
    향후 additional_scores를 통해 홍수위험도, 산사태위험도 등을 합산할 수 있습니다.

    Args:
        facility_row: 시설물 정보 (pandas Series)
        warnings_df: 해당 시설물 위치에 적용되는 특보 DataFrame
        additional_scores: 추가 위험 요소 점수 리스트
            [{"source": "홍수통제소", "factor": "홍수위험도", "score": 3.0}, ...]

    Returns:
        dict: {
            "facility_name": str,
            "max_warning_score": float,
            "additional_score": float,
            "total_score": float,
            "grade": str,  # "상"/"중"/"하"/"없음"
            "matched_warnings": list,  # 매칭된 특보 목록
        }
    """
    address = str(facility_row.get("address", ""))
    matched_warnings = []

    # 특보와 시설물 주소 매칭
    if not warnings_df.empty:
        for _, warn_row in warnings_df.iterrows():
            region = str(warn_row.get("region", ""))
            if facility_matches_warning(
                address,
                region,
                warn_row.get("region_up", ""),
            ):
                score = calculate_warning_score(
                    warn_row.get("type", ""),
                    warn_row.get("level", ""),
                )
                matched_warnings.append(
                    {
                        "type": warn_row.get("type", ""),
                        "level": warn_row.get("level", ""),
                        "region": region,
                        "score": score,
                        "source": warn_row.get("source", "기상청"),
                    }
                )

    # 특보 기반 최대 점수 (가장 높은 것 적용)
    max_warning_score = (
        max(w["score"] for w in matched_warnings) if matched_warnings else 0.0
    )

    # 추가 위험 요소 점수 합산 (향후 확장용)
    additional_total = 0.0
    if additional_scores:
        additional_total = sum(s.get("score", 0) for s in additional_scores)

    total_score = max_warning_score + additional_total
    grade = classify_grade(total_score)

    return {
        "facility_name": facility_row.get("name", ""),
        "facility_type": facility_row.get("시설구분", ""),
        "department": facility_row.get("담당부서", "-"),
        "manager": facility_row.get("부서 담당자", "-"),
        "address": address,
        "latitude": facility_row.get("latitude", 0),
        "longitude": facility_row.get("longitude", 0),
        "max_warning_score": max_warning_score,
        "additional_score": additional_total,
        "total_score": total_score,
        "grade": grade,
        "matched_warnings": matched_warnings,
    }


def assess_all_facilities(
    facility_df: pd.DataFrame,
    warnings_df: pd.DataFrame,
) -> Tuple[pd.DataFrame, Dict[str, pd.DataFrame]]:
    """
    전체 시설물에 대해 위험도를 산정하고 등급별로 그룹핑합니다.

    Args:
        facility_df: 전체 시설물 DataFrame
        warnings_df: 현재 발효 중인 특보 DataFrame

    Returns:
        Tuple:
            - 전체 평가 결과 DataFrame (점수 내림차순 정렬)
            - 등급별 그룹 딕셔너리 {"상": DataFrame, "중": DataFrame, "하": DataFrame}
    """
    results = []
    for _, row in facility_df.iterrows():
        result = assess_facility_risk(row, warnings_df)
        results.append(result)

    result_df = pd.DataFrame(results)

    # 점수 내림차순 정렬
    result_df = result_df.sort_values("total_score", ascending=False).reset_index(
        drop=True
    )

    # 등급별 그룹핑 (위험도가 있는 시설물만)
    groups = {}
    for grade in ["상", "중", "하"]:
        grade_df = result_df[result_df["grade"] == grade]
        if not grade_df.empty:
            groups[grade] = grade_df

    return result_df, groups
