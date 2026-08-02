"""시설·특보·알림 데이터를 UI가 사용하기 좋은 형태로 조합합니다."""

from __future__ import annotations

import datetime as dt
import html
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from core.region_resolver import facility_matches_warning
from risk_engine import assess_all_facilities


FACILITY_REQUIRED_COLUMNS = {
    "name",
    "address",
    "latitude",
    "longitude",
    "시설구분",
    "부서 담당자",
}


class FacilityDataError(ValueError):
    """시설 데이터가 예상 스키마를 만족하지 않을 때 발생합니다."""


@dataclass(frozen=True)
class WarningSnapshot:
    warnings: pd.DataFrame
    status: str
    message: str
    fetched_at: dt.datetime


def load_facilities(path: str | Path) -> pd.DataFrame:
    """CSV 시설 데이터를 검증하여 반환합니다."""

    file_path = Path(path)
    if not file_path.exists():
        raise FacilityDataError(f"시설 데이터 파일이 없습니다: {file_path}")

    try:
        df = pd.read_csv(file_path, encoding="utf-8-sig")
    except (OSError, UnicodeError, pd.errors.ParserError) as exc:
        raise FacilityDataError("시설 데이터 파일을 읽을 수 없습니다.") from exc

    missing = FACILITY_REQUIRED_COLUMNS.difference(df.columns)
    if missing:
        raise FacilityDataError(
            f"시설 데이터 필수 열이 없습니다: {', '.join(sorted(missing))}"
        )

    df = df.copy()
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")

    invalid_coords = (
        df["latitude"].isna()
        | df["longitude"].isna()
        | ~df["latitude"].between(33.0, 39.5)
        | ~df["longitude"].between(124.0, 132.0)
    )
    if invalid_coords.any():
        invalid_names = ", ".join(df.loc[invalid_coords, "name"].astype(str).head(3))
        raise FacilityDataError(
            f"유효하지 않은 시설 좌표가 {int(invalid_coords.sum())}건 있습니다: "
            f"{invalid_names}"
        )

    return df


def make_warning_snapshot(warnings: pd.DataFrame) -> WarningSnapshot:
    """프로바이더 DataFrame의 상태 메타데이터를 정규화합니다."""

    fetched_raw = warnings.attrs.get("fetched_at", "")
    try:
        fetched_at = dt.datetime.fromisoformat(str(fetched_raw))
    except ValueError:
        fetched_at = dt.datetime.now()

    return WarningSnapshot(
        warnings=warnings,
        status=str(warnings.attrs.get("fetch_status", "ok")),
        message=str(warnings.attrs.get("fetch_message", "")),
        fetched_at=fetched_at,
    )


def assess_dashboard(
    facilities: pd.DataFrame,
    warnings: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], pd.DataFrame]:
    """전체 위험도를 계산하고 영향 시설만 별도로 반환합니다."""

    result_df, grade_groups = assess_all_facilities(facilities, warnings)
    affected = result_df[result_df["grade"] != "없음"].copy()
    return result_df, grade_groups, affected


def matched_warning_rows(
    facility: pd.Series,
    warnings: pd.DataFrame,
) -> pd.DataFrame:
    """선택 시설에 적용되는 특보 행을 반환합니다."""

    if warnings.empty:
        return warnings.copy()
    mask = warnings.apply(
        lambda row: facility_matches_warning(
            facility.get("address", ""),
            row.get("region", ""),
            row.get("region_up", ""),
        ),
        axis=1,
    )
    return warnings[mask].copy()


def build_telegram_message(affected: pd.DataFrame) -> str:
    """영향 시설 DataFrame을 텔레그램 HTML 메시지로 변환합니다."""

    if affected.empty:
        return "✅ 현재 점검 대상 시설이 없습니다."

    lines = [
        "⚠️ <b>[기상재난 시설 점검 요청]</b>",
        f"점검 대상: <b>{len(affected)}개 시설</b>",
    ]

    for grade in ("상", "중", "하"):
        grade_df = affected[affected["grade"] == grade]
        if grade_df.empty:
            continue
        grade_label = {"상": "즉시 점검", "중": "주의 관찰", "하": "경과 관찰"}[grade]
        lines.append(f"\n<b>[{grade}] {grade_label} · {len(grade_df)}개</b>")
        for _, row in grade_df.head(25).iterrows():
            matched = row.get("matched_warnings", [])
            warning_text = ", ".join(
                f"{item.get('type', '')}{item.get('level', '')}"
                for item in matched[:2]
            )
            facility_name = html.escape(str(row.get("facility_name", "")))
            lines.append(f"• {facility_name} — {html.escape(warning_text)}")
        if len(grade_df) > 25:
            lines.append(f"• 외 {len(grade_df) - 25}개 시설")

    lines.append("\n대시보드에서 담당자와 세부 위치를 확인해 주세요.")
    return "\n".join(lines)
