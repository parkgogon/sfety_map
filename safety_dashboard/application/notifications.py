"""관제 snapshot으로부터 Telegram 메시지를 만듭니다."""

from __future__ import annotations

import html
import datetime as dt
from collections import Counter
from collections.abc import Iterable

from safety_dashboard.application.contacts import public_contact
from safety_dashboard.application.deep_links import (
    build_facility_url,
    dashboard_home_url,
)
from safety_dashboard.domain.enums import RiskGrade
from safety_dashboard.alerts.domain import ManualTelegramCategory
from safety_dashboard.domain.models import (
    DashboardSnapshot,
    OutgoingTelegramMessage,
    RiskAssessment,
)


MAX_MESSAGE_LENGTH = 3900

_DETAIL_ORDER = (
    RiskGrade.HIGH,
    RiskGrade.UNASSESSED,
    RiskGrade.MEDIUM,
    RiskGrade.LOW,
)
_GRADE_EMOJI = {
    RiskGrade.HIGH: "🔴",
    RiskGrade.UNASSESSED: "⚪",
    RiskGrade.MEDIUM: "🟠",
    RiskGrade.LOW: "🟡",
    RiskGrade.NONE: "🔵",
}
_GRADE_ACTION = {
    RiskGrade.HIGH: "담당자에게 즉시 점검을 요청하고 현장 이상 여부를 확인",
    RiskGrade.UNASSESSED: "기준 미등록 항목을 관리자가 수동으로 판단",
    RiskGrade.MEDIUM: "담당자에게 시설 상태 확인을 요청",
    RiskGrade.LOW: "특보 변경과 시설 상태를 계속 관찰",
    RiskGrade.NONE: "현재 후속 조치 없음",
}


def build_telegram_payloads(
    snapshot: DashboardSnapshot,
    scope_label: str = "",
    mode: str = "실시간",
    policy_version: str | None = None,
    dashboard_base_url: str = "",
    temporary_policy: bool = False,
    max_length: int = MAX_MESSAGE_LENGTH,
) -> list[OutgoingTelegramMessage]:
    """상황 요약과 등급별 전체 시설 상세를 발송 payload로 만듭니다."""

    targets = tuple(
        item for item in snapshot.assessments if item.grade is not RiskGrade.NONE
    )
    policy = policy_version or snapshot.policy_version
    home_url = dashboard_home_url(dashboard_base_url)
    counts = Counter(item.grade for item in targets)
    requires_attention = bool(
        counts[RiskGrade.HIGH] or counts[RiskGrade.UNASSESSED]
    )
    occurred_at = _occurred_at(snapshot)
    mode_badge = f"[🎓 {mode}]" if "훈련" in mode else f"[{mode}]"
    temporary_line = (
        "\n⚠️ <b>현재 브라우저의 임시 위험도 기준 적용</b>"
        if temporary_policy
        else ""
    )
    action = _summary_action(counts)
    summary = (
        f"📡 <b>{html.escape(mode_badge)} 기상재난 시설 상황전파</b>\n"
        f"\n<b>발생·기준 시각</b>  {occurred_at:%Y-%m-%d %H:%M}"
        f"\n<b>영향 특보</b>  {snapshot.summary.active_warning_count}건"
        f"\n<b>선택 시설</b>  {len(targets)}개"
        f"\n<b>등급 현황</b>  "
        f"상 {counts[RiskGrade.HIGH]} · "
        f"미판정 {counts[RiskGrade.UNASSESSED]} · "
        f"중 {counts[RiskGrade.MEDIUM]} · 하 {counts[RiskGrade.LOW]}"
        + (f"\n<b>조회 범위</b>  {html.escape(scope_label)}" if scope_label else "")
        + f"\n<b>권장 행동</b>  {html.escape(action)}"
        + f"\n<b>위험도 정책</b>  {html.escape(policy)}"
        + temporary_line
    )
    if len(summary) > max_length:
        raise ValueError("Telegram 요약 메시지가 너무 깁니다.")

    payloads = [
        OutgoingTelegramMessage(
            text=summary,
            silent=not requires_attention,
            action_label="대시보드에서 확인",
            action_url=home_url,
        )
    ]
    for grade in _DETAIL_ORDER:
        grade_targets = sorted(
            (item for item in targets if item.grade is grade),
            key=lambda item: item.facility.name,
        )
        if not grade_targets:
            continue
        blocks = [
            _facility_detail_block(item, dashboard_base_url)
            for item in grade_targets
        ]
        pages = _paginate_detail_blocks(grade, blocks, max_length)
        payloads.extend(
            OutgoingTelegramMessage(text=page, silent=True) for page in pages
        )
    return payloads


def build_manual_telegram_payloads(
    snapshot: DashboardSnapshot,
    category: ManualTelegramCategory,
    note: str = "",
    scope_label: str = "",
    mode: str = "실시간",
    dashboard_base_url: str = "",
    temporary_policy: bool = False,
    max_length: int = MAX_MESSAGE_LENGTH,
) -> list[OutgoingTelegramMessage]:
    """관리자 수동 전파임을 모든 메시지에 명확히 표시한다."""

    is_drill = category is ManualTelegramCategory.DRILL
    base = build_telegram_payloads(
        snapshot,
        scope_label=scope_label,
        mode="모의훈련" if is_drill else mode,
        dashboard_base_url=dashboard_base_url,
        temporary_policy=temporary_policy,
        max_length=max_length - 520,
    )
    escaped_note = html.escape(note.strip())
    if is_drill:
        heading = (
            "🎓 <b>[모의훈련][수동 상황전파][훈련]</b>\n"
            "⚠️ <b>실제 재난 알림이 아닙니다.</b>"
        )
        closing = "\n\n⚠️ 모의훈련 메시지이며 실제 재난 알림이 아닙니다."
    else:
        heading = f"📣 <b>[수동 상황전파][{category.label}]</b>"
        closing = ""
    metadata = "\n발송자 · 중앙관제 관리자"
    if escaped_note:
        metadata += f"\n관리자 안내 · {escaped_note}"
    messages = [
        OutgoingTelegramMessage(
            text=f"{heading}{metadata}\n\n{item.text}{closing}",
            silent=item.silent,
            action_label=item.action_label,
            action_url=item.action_url,
        )
        for item in base
    ]
    if any(len(item.text) > max_length for item in messages):
        raise ValueError("수동 Telegram 메시지가 길이 제한을 초과했습니다.")
    return messages


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


def _facility_detail_block(
    assessment: RiskAssessment,
    dashboard_base_url: str,
) -> str:
    facility = assessment.facility
    name = html.escape(facility.name)
    facility_url = build_facility_url(dashboard_base_url, facility.id)
    name_text = (
        f'<a href="{html.escape(facility_url, quote=True)}">{name}</a>'
        if facility_url
        else name
    )
    warning_text = " / ".join(
        dict.fromkeys(
            f"{reason.warning_type} {reason.raw_level} ({reason.region})".strip()
            for reason in assessment.reasons
        )
    ) or "정책 확인 필요"
    return (
        f"📍 <b>{name_text}</b>\n"
        f"  · 판정 근거: {html.escape(warning_text)}\n"
        f"  · 담당: {html.escape(public_contact(facility))}\n"
        f"  · 조치: {html.escape(_GRADE_ACTION[assessment.grade])}"
    )


def _paginate_detail_blocks(
    grade: RiskGrade,
    blocks: list[str],
    max_length: int,
) -> list[str]:
    base_header = (
        f"{_GRADE_EMOJI[grade]} <b>{_grade_label(grade)} 등급 시설 상세</b>"
    )
    footer = "시설명을 누르면 대시보드의 해당 시설로 이동합니다."
    body_limit = max_length - len(base_header) - len(footer) - 40
    if body_limit < 200:
        raise ValueError("Telegram 상세 메시지 길이 제한이 너무 작습니다.")
    bodies: list[list[str]] = []
    current: list[str] = []
    current_length = 0
    for block in blocks:
        block_length = len(block) + 2
        if block_length > body_limit:
            raise ValueError("시설 하나의 상세 정보가 Telegram 제한보다 깁니다.")
        if current and current_length + block_length > body_limit:
            bodies.append(current)
            current = []
            current_length = 0
        current.append(block)
        current_length += block_length
    if current:
        bodies.append(current)

    result: list[str] = []
    for index, body in enumerate(bodies, start=1):
        page = f" ({index}/{len(bodies)})" if len(bodies) > 1 else ""
        message = f"{base_header}{page}\n\n" + "\n\n".join(body) + f"\n\n{footer}"
        if len(message) > max_length:
            raise ValueError("Telegram 상세 메시지 분할에 실패했습니다.")
        result.append(message)
    return result


def _summary_action(counts: Counter[RiskGrade]) -> str:
    if counts[RiskGrade.HIGH]:
        return _GRADE_ACTION[RiskGrade.HIGH]
    if counts[RiskGrade.UNASSESSED]:
        return _GRADE_ACTION[RiskGrade.UNASSESSED]
    if counts[RiskGrade.MEDIUM]:
        return _GRADE_ACTION[RiskGrade.MEDIUM]
    if counts[RiskGrade.LOW]:
        return _GRADE_ACTION[RiskGrade.LOW]
    return "현재 선택 범위에 특보 영향 시설이 없습니다."


def _occurred_at(snapshot: DashboardSnapshot) -> dt.datetime:
    times = [
        value
        for warning in snapshot.warning_feed.warnings
        for value in (warning.effective_at, warning.issued_at)
        if value is not None
    ]
    return min(times) if times else snapshot.generated_at


def _grade_label(grade: RiskGrade) -> str:
    return {
        RiskGrade.HIGH: "상",
        RiskGrade.MEDIUM: "중",
        RiskGrade.LOW: "하",
        RiskGrade.UNASSESSED: "미판정",
        RiskGrade.NONE: "없음",
    }[grade]
