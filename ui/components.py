"""작은 Streamlit UI 컴포넌트 모음."""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from core.region_resolver import warning_level_rank


def render_header() -> None:
    st.html(
        """
        <div class="dashboard-header">
            <div class="dashboard-kicker">K-ECO · DAEGU GYEONGBUK</div>
            <h1 class="dashboard-title">스마트 기상·재난 관제</h1>
            <div class="dashboard-subtitle">
                소관시설의 기상특보, 현장 영향과 대응 우선순위를 한 화면에서 확인합니다.
            </div>
        </div>
        """
    )


def render_status_cards(
    *,
    warning_count: int,
    highest_level: str,
    affected_count: int,
    urgent_count: int,
    source_status: str,
    fetched_note: str,
) -> None:
    source_value = "정상 수신" if source_status == "ok" else "확인 필요"
    source_class = "ok" if source_status == "ok" else "danger"
    cards = [
        ("활성 특보구역", f"{warning_count}건", "소관시설 권역", "warning"),
        ("최고 특보 단계", highest_level or "없음", "현재 발효 기준", "danger"),
        (
            "영향 시설",
            f"{affected_count}개",
            f"상 등급 {urgent_count}개",
            "info",
        ),
        ("데이터 상태", source_value, fetched_note, source_class),
    ]
    markup = ['<div class="status-grid">']
    for label, value, note, card_class in cards:
        markup.append(
            f'<div class="status-card status-card--{card_class}">'
            f'<div class="status-card__label">{html.escape(label)}</div>'
            f'<div class="status-card__value">{html.escape(value)}</div>'
            f'<div class="status-card__note">{html.escape(note)}</div>'
            "</div>"
        )
    markup.append("</div>")
    st.html("".join(markup))


def render_alert_summary(warnings: pd.DataFrame) -> None:
    if warnings.empty:
        st.success("현재 소관시설 권역에 발효 중인 기상특보가 없습니다.")
        return

    sorted_rows = sorted(
        warnings.to_dict("records"),
        key=lambda row: warning_level_rank(row.get("level")),
        reverse=True,
    )
    labels = [
        f"{row.get('region', '')} · {row.get('type', '')} {row.get('level', '')}"
        for row in sorted_rows[:4]
    ]
    remaining = len(sorted_rows) - len(labels)
    summary = "  ·  ".join(labels)
    if remaining > 0:
        summary += f"  ·  외 {remaining}건"

    st.html(
        f"""
        <div class="alert-summary">
            <span class="alert-summary__badge">기상특보</span>
            <span class="alert-summary__text">{html.escape(summary)}</span>
        </div>
        """
    )


def render_section_heading(title: str, note: str = "") -> None:
    st.html(
        f"""
        <div class="section-heading">
            <h2>{html.escape(title)}</h2>
            <span>{html.escape(note)}</span>
        </div>
        """
    )


def render_facility_metadata(manager: object, facility_type: object) -> None:
    """긴 값도 생략하지 않는 세로형 시설 메타데이터를 표시합니다."""

    rows = [
        ("담당자", str(manager or "-")),
        ("시설유형", str(facility_type or "-")),
    ]
    markup = ['<div class="facility-metadata">']
    for label, value in rows:
        markup.append(
            '<div class="facility-metadata__row">'
            f'<div class="facility-metadata__label">{html.escape(label)}</div>'
            f'<div class="facility-metadata__value">{html.escape(value)}</div>'
            "</div>"
        )
    markup.append("</div>")
    st.html("".join(markup))


def render_action_cards(affected: pd.DataFrame, limit: int = 8) -> None:
    if affected.empty:
        st.success("현재 특보 영향권에 포함된 시설이 없습니다.")
        return

    grade_order = {"상": 0, "중": 1, "하": 2}
    ordered = affected.copy()
    ordered["_grade_order"] = ordered["grade"].map(grade_order).fillna(9)
    ordered = ordered.sort_values(
        ["_grade_order", "total_score"],
        ascending=[True, False],
    )

    for _, row in ordered.head(limit).iterrows():
        grade = str(row.get("grade", "하"))
        css_grade = {"상": "high", "중": "medium", "하": "low"}.get(grade, "low")
        warnings = row.get("matched_warnings", [])
        warning_text = ", ".join(
            f"{item.get('type', '')} {item.get('level', '')}"
            for item in warnings[:2]
        )
        st.html(
            f"""
            <div class="action-card action-card--{css_grade}">
                <div class="action-card__top">
                    <span class="action-card__name">
                        {html.escape(str(row.get('facility_name', '')))}
                    </span>
                    <span class="action-card__grade grade-{css_grade}">{grade}</span>
                </div>
                <div class="action-card__meta">
                    {html.escape(warning_text or '특보 영향권')}<br>
                    {html.escape(str(row.get('manager', '-')))} ·
                    {html.escape(str(row.get('facility_type', '')))}
                </div>
            </div>
            """
        )

    if len(ordered) > limit:
        st.caption(f"우선순위 상위 {limit}개 표시 · 전체 {len(ordered)}개")


def render_weather_cards(weather: dict[str, str]) -> None:
    cards = [
        ("기온", f"{weather.get('기온(℃)', '-')} ℃"),
        ("1시간 강수량", f"{weather.get('1시간강수량(mm)', '-')} mm"),
        ("풍속", f"{weather.get('풍속(m/s)', '-')} m/s"),
        ("풍향", f"{weather.get('풍향(deg)', '-')}°"),
    ]
    markup = ['<div class="weather-grid">']
    for label, value in cards:
        markup.append(
            '<div class="weather-card">'
            f'<div class="weather-card__label">{html.escape(label)}</div>'
            f'<div class="weather-card__value">{html.escape(value)}</div>'
            "</div>"
        )
    markup.append("</div>")
    st.html("".join(markup))
