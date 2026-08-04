"""관제 snapshot으로부터 Telegram 메시지를 만듭니다."""

from __future__ import annotations

import html
from collections.abc import Iterable

from safety_dashboard.domain.enums import RiskGrade
from safety_dashboard.domain.models import RiskAssessment


MAX_MESSAGE_LENGTH = 3900


def build_telegram_messages(
    assessments: Iterable[RiskAssessment],
    max_length: int = MAX_MESSAGE_LENGTH,
    simulation: bool = False,
    scope_label: str = "",
    temporary_policy: bool = False,
) -> list[str]:
    targets = [item for item in assessments if item.grade is not RiskGrade.NONE]
    order = {
        RiskGrade.HIGH: 0,
        RiskGrade.MEDIUM: 1,
        RiskGrade.LOW: 2,
        RiskGrade.UNASSESSED: 3,
    }
    targets.sort(key=lambda item: (order.get(item.grade, 9), item.facility.name))
    if not targets:
        return ["✅ 현재 기상특보 영향 시설이 없습니다."]

    mode = "[모의훈련] " if simulation else ""
    header = f"⚠️ <b>{mode}[기상재난 시설 확인 요청]</b>"
    footer = "대시보드에서 상세 위치와 담당자를 확인해 주세요."
    scope_line = f"조회 범위: <b>{html.escape(scope_label)}</b>" if scope_label else ""
    policy_line = "⚠️ <b>현재 브라우저의 임시 위험도 기준 적용</b>" if temporary_policy else ""
    summary_line = f"영향 시설 <b>{len(targets)}개</b> · 정책 {targets[0].policy_version}"
    fixed_length = sum(
        len(item)
        for item in (header, summary_line, scope_line, policy_line, footer)
    ) + 80
    body_limit = max_length - fixed_length
    if body_limit < 200:
        raise ValueError("조회 범위 설명이 너무 길어 Telegram 메시지를 만들 수 없습니다.")
    lines: list[str] = []
    for item in targets:
        warning_text = ", ".join(
            dict.fromkeys(
                f"{reason.warning_type} {reason.raw_level}".strip()
                for reason in item.reasons
            )
        ) or "정책 확인 필요"
        lines.append(
            f"• <b>{html.escape(item.facility.name)}</b> "
            f"[{html.escape(_grade_label(item.grade))}] — {html.escape(warning_text)}"
        )

    pages: list[list[str]] = []
    current: list[str] = []
    current_length = 0
    for line in lines:
        line_length = len(line) + 1
        if current and current_length + line_length > body_limit:
            pages.append(current)
            current = []
            current_length = 0
        if line_length > body_limit:
            raise ValueError("시설명이 너무 길어 Telegram 메시지를 만들 수 없습니다.")
        current.append(line)
        current_length += line_length
    if current:
        pages.append(current)

    messages: list[str] = []
    for index, page in enumerate(pages, start=1):
        sections = [
            header + (f" ({index}/{len(pages)})" if len(pages) > 1 else ""),
            summary_line,
        ]
        if scope_line:
            sections.append(scope_line)
        if policy_line:
            sections.append(policy_line)
        sections.extend(("\n".join(page), footer))
        message = "\n\n".join(sections)
        if len(message) > max_length:
            raise ValueError("Telegram 메시지 분할 길이 계산에 실패했습니다.")
        messages.append(message)
    return messages


def _grade_label(grade: RiskGrade) -> str:
    return {
        RiskGrade.HIGH: "상",
        RiskGrade.MEDIUM: "중",
        RiskGrade.LOW: "하",
        RiskGrade.UNASSESSED: "미판정",
        RiskGrade.NONE: "없음",
    }[grade]
