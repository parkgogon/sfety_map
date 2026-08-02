"""시설·특보·알림 데이터를 UI가 사용하기 좋은 형태로 조합합니다."""

from __future__ import annotations

import datetime as dt
import html
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from core.region_resolver import WarningZoneIndex, warning_matches_facility
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
    zone_index: WarningZoneIndex | None = None,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], pd.DataFrame]:
    """전체 위험도를 계산하고 영향 시설만 별도로 반환합니다."""

    result_df, grade_groups = assess_all_facilities(
        facilities,
        warnings,
        zone_index=zone_index,
    )
    affected = result_df[result_df["grade"] != "없음"].copy()
    return result_df, grade_groups, affected


def matched_warning_rows(
    facility: pd.Series,
    warnings: pd.DataFrame,
    zone_index: WarningZoneIndex | None = None,
) -> pd.DataFrame:
    """선택 시설에 적용되는 특보 행을 반환합니다."""

    if warnings.empty:
        return warnings.copy()
    mask = warnings.apply(
        lambda row: warning_matches_facility(facility, row, zone_index),
        axis=1,
    )
    return warnings[mask].copy()


TELEGRAM_MESSAGE_MAX_LENGTH = 3900


def _telegram_warning_text(matched: object) -> str:
    if not isinstance(matched, list):
        return "특보 영향권"

    labels: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for item in matched:
        if not isinstance(item, dict):
            continue
        key = (
            str(item.get("type", "")),
            str(item.get("level", "")),
            str(item.get("region", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        warning_type, level, region = key
        label = f"{warning_type} {level}".strip()
        if region:
            label += f" ({region})"
        labels.append(label)
    return ", ".join(labels) or "특보 영향권"


def build_telegram_messages(
    affected: pd.DataFrame,
    max_length: int = TELEGRAM_MESSAGE_MAX_LENGTH,
) -> list[str]:
    """모든 영향 시설을 생략 없이 길이 제한 내 HTML 메시지로 나눕니다."""

    if affected.empty:
        return ["✅ 현재 점검 대상 시설이 없습니다."]
    if max_length < 500:
        raise ValueError("텔레그램 메시지 최대 길이가 너무 짧습니다.")

    grade_order = {"상": 0, "중": 1, "하": 2}
    ordered = affected.copy()
    ordered["_grade_order"] = ordered["grade"].map(grade_order).fillna(9)
    sort_columns = ["_grade_order"]
    ascending = [True]
    if "total_score" in ordered:
        sort_columns.append("total_score")
        ascending.append(False)
    if "facility_name" in ordered:
        sort_columns.append("facility_name")
        ascending.append(True)
    ordered = ordered.sort_values(sort_columns, ascending=ascending)

    page_header = (
        "⚠️ <b>[기상재난 시설 점검 요청]</b>\n"
        f"점검 대상: <b>{len(ordered)}개 시설</b>"
    )
    footer = "\n대시보드에서 담당자와 세부 위치를 확인해 주세요."
    body_limit = max_length - len(page_header) - len(footer) - 40
    pages: list[list[str]] = []
    current: list[str] = []
    current_length = 0

    for grade in ("상", "중", "하"):
        grade_df = ordered[ordered["grade"] == grade]
        if grade_df.empty:
            continue
        grade_label = {
            "상": "즉시 점검",
            "중": "주의 관찰",
            "하": "경과 관찰",
        }[grade]
        section_header = f"<b>[{grade}] {grade_label} · {len(grade_df)}개</b>"
        header_pending = True
        for _, row in grade_df.iterrows():
            facility_name = html.escape(str(row.get("facility_name", "")))
            warning_text = html.escape(
                _telegram_warning_text(row.get("matched_warnings", []))
            )
            line = f"• {facility_name} — {warning_text}"
            required_lines = ([section_header] if header_pending else []) + [line]
            required_length = sum(len(item) + 1 for item in required_lines)

            if current and current_length + required_length > body_limit:
                pages.append(current)
                current = []
                current_length = 0
                header_pending = True
                required_lines = [section_header, line]
                required_length = sum(len(item) + 1 for item in required_lines)

            if required_length > body_limit:
                raise ValueError(f"시설 점검 문구가 너무 깁니다: {facility_name}")
            current.extend(required_lines)
            current_length += required_length
            header_pending = False

    if current:
        pages.append(current)

    total_pages = len(pages)
    messages: list[str] = []
    for index, body in enumerate(pages, start=1):
        page_label = f" ({index}/{total_pages})" if total_pages > 1 else ""
        message = (
            page_header.replace("</b>\n", f"{page_label}</b>\n", 1)
            + "\n\n"
            + "\n".join(body)
            + footer
        )
        if len(message) > max_length:
            raise ValueError("텔레그램 메시지 분할 길이 계산에 실패했습니다.")
        messages.append(message)
    return messages
