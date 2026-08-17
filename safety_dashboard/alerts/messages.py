"""시설담당자별 문자 내용을 구성합니다."""

from __future__ import annotations

import hashlib
import hmac
import html
from collections import defaultdict
from collections.abc import Iterable

from safety_dashboard.alerts.domain import (
    AlertBatch,
    AlertTransition,
    AlertTransitionKind,
    ContactDirectory,
    OutgoingSmsMessage,
)
from safety_dashboard.application.deep_links import build_facility_url, dashboard_home_url
from safety_dashboard.domain.enums import RiskGrade
from safety_dashboard.domain.models import OutgoingTelegramMessage


_GRADE_LABEL = {
    RiskGrade.HIGH: "상",
    RiskGrade.MEDIUM: "중",
    RiskGrade.LOW: "하",
    RiskGrade.UNASSESSED: "미판정",
    RiskGrade.NONE: "영향 없음",
}
_GRADE_RANK = {
    RiskGrade.NONE: 0,
    RiskGrade.UNASSESSED: 1,
    RiskGrade.LOW: 2,
    RiskGrade.MEDIUM: 3,
    RiskGrade.HIGH: 4,
}
_GRADE_EMOJI = {
    RiskGrade.HIGH: "🔴",
    RiskGrade.UNASSESSED: "🟣",
    RiskGrade.MEDIUM: "🟠",
    RiskGrade.LOW: "🟡",
    RiskGrade.NONE: "🔵",
}
MAX_TELEGRAM_LENGTH = 3900


def build_sms_messages(
    batch: AlertBatch,
    directory: ContactDirectory,
    hmac_secret: str,
    dashboard_base_url: str,
) -> tuple[OutgoingSmsMessage, ...]:
    if not hmac_secret:
        raise ValueError("수신자 익명화 비밀값이 없습니다.")
    by_facility: dict[str, list[AlertTransition]] = defaultdict(list)
    for transition in batch.transitions:
        by_facility[transition.impact.facility_id].append(transition)

    by_phone: dict[str, list[AlertTransition]] = defaultdict(list)
    for facility_id, transitions in by_facility.items():
        for recipient in directory.for_facility(facility_id):
            by_phone[recipient.phone].extend(transitions)

    messages = []
    for phone, transitions in sorted(by_phone.items()):
        unique = {item.id: item for item in transitions}
        selected = tuple(sorted(unique.values(), key=lambda item: item.id))
        recipient_hash = hmac.new(
            hmac_secret.encode("utf-8"),
            phone.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        facility_ids = tuple(sorted({item.impact.facility_id for item in selected}))
        message_id = hashlib.sha256(
            f"{batch.id}|{recipient_hash}".encode("utf-8")
        ).hexdigest()[:28]
        messages.append(
            OutgoingSmsMessage(
                id=message_id,
                batch_id=batch.id,
                recipient_hash=recipient_hash,
                phone=phone,
                text=_message_text(selected, dashboard_base_url),
                facility_ids=facility_ids,
                transition_ids=tuple(item.id for item in selected),
            )
        )
    return tuple(messages)


def unmapped_facility_ids(
    transitions: Iterable[AlertTransition],
    directory: ContactDirectory,
) -> tuple[str, ...]:
    mapped = {item.facility_id for item in directory.recipients}
    return tuple(sorted({
        item.impact.facility_id for item in transitions
        if item.impact.facility_id not in mapped
    }))


def build_alert_batch_telegram_payloads(
    batch: AlertBatch,
    dashboard_base_url: str,
    fallback_reason: str = "",
    max_length: int = MAX_TELEGRAM_LENGTH,
) -> tuple[OutgoingTelegramMessage, ...]:
    """자동 감지 batch를 개인정보 없는 사용자 채널 메시지로 만든다."""

    by_facility: dict[str, list[AlertTransition]] = defaultdict(list)
    for transition in batch.transitions:
        by_facility[transition.impact.facility_id].append(transition)
    selected = []
    for facility_id, transitions in by_facility.items():
        active = [item for item in transitions if item.current is not None]
        representative = max(
            active or transitions,
            key=lambda item: _GRADE_RANK[item.impact.risk_grade],
        )
        selected.append((facility_id, representative, tuple(transitions)))
    selected.sort(
        key=lambda value: (
            -_GRADE_RANK[value[1].impact.risk_grade],
            value[1].impact.facility_name,
        )
    )

    kinds = {item.kind for item in batch.transitions}
    kind_label = next(iter(kinds)).label if len(kinds) == 1 else "상황변경"
    reference_at = max(item.detected_at for item in batch.transitions)
    warning_count = len({item.impact.warning_key for item in batch.transitions})
    current_grades = [
        item.impact.risk_grade
        for _, item, _ in selected
        if item.current is not None
    ]
    grade_text = " · ".join(
        f"{_GRADE_LABEL[grade]} {sum(value is grade for value in current_grades)}"
        for grade in (
            RiskGrade.HIGH,
            RiskGrade.UNASSESSED,
            RiskGrade.MEDIUM,
            RiskGrade.LOW,
        )
        if any(value is grade for value in current_grades)
    ) or "영향 종료"
    attention = any(
        item.current is not None
        and item.impact.risk_grade in {RiskGrade.HIGH, RiskGrade.UNASSESSED}
        and item.kind in {
            AlertTransitionKind.ACTIVATED,
            AlertTransitionKind.ESCALATED,
        }
        for item in batch.transitions
    )
    fallback_line = (
        f"\n⚠️ <b>문자 대체 전파</b> · {html.escape(fallback_reason)}"
        if fallback_reason
        else ""
    )
    summary = (
        f"📡 <b>[K-ECO 재난안전][{kind_label}]</b>"
        f"{fallback_line}\n"
        f"기준 시각 · {reference_at:%Y-%m-%d %H:%M}\n"
        f"영향 특보 · {warning_count}건\n"
        f"영향 시설 · {len(selected)}곳\n"
        f"등급 현황 · {html.escape(grade_text)}\n"
        f"정책 · {html.escape(batch.policy_version)}"
    )
    home_url = dashboard_home_url(dashboard_base_url)
    payloads = [OutgoingTelegramMessage(
        text=summary,
        silent=not attention,
        action_label="시설 지도에서 확인",
        action_url=home_url,
    )]

    blocks: list[str] = []
    for facility_id, representative, transitions in selected:
        impact = representative.impact
        facility_url = build_facility_url(dashboard_base_url, facility_id)
        escaped_name = html.escape(impact.facility_name)
        name = (
            f'<a href="{html.escape(facility_url, quote=True)}">{escaped_name}</a>'
            if facility_url
            else escaped_name
        )
        warnings = " / ".join(dict.fromkeys(
            f"{item.impact.region} {item.impact.warning_type} {item.impact.raw_level}"
            for item in transitions
        ))
        blocks.append(
            f"{_GRADE_EMOJI[impact.risk_grade]} <b>{name}</b> "
            f"[{_GRADE_LABEL[impact.risk_grade]}]\n"
            f"  · 특보: {html.escape(warnings)}\n"
            f"  · 조치: {html.escape(impact.recommended_action)}"
        )
    payloads.extend(
        OutgoingTelegramMessage(text=page, silent=True)
        for page in _paginate_telegram_blocks(blocks, max_length)
    )
    if any(len(item.text) > max_length for item in payloads):
        raise ValueError("자동 Telegram 메시지가 길이 제한을 초과했습니다.")
    return tuple(payloads)


def _paginate_telegram_blocks(
    blocks: list[str],
    max_length: int,
) -> tuple[str, ...]:
    if not blocks:
        return ()
    header = "<b>영향시설 상세</b>"
    pages: list[list[str]] = []
    current: list[str] = []
    length = len(header) + 2
    for block in blocks:
        if len(block) + len(header) + 4 > max_length:
            raise ValueError("시설 상세 한 건이 Telegram 길이 제한을 초과했습니다.")
        if current and length + len(block) + 2 > max_length:
            pages.append(current)
            current = []
            length = len(header) + 2
        current.append(block)
        length += len(block) + 2
    if current:
        pages.append(current)
    return tuple(
        f"{header}" + (
            f" ({index}/{len(pages)})" if len(pages) > 1 else ""
        ) + "\n\n" + "\n\n".join(page)
        for index, page in enumerate(pages, start=1)
    )


def _message_text(
    transitions: tuple[AlertTransition, ...],
    dashboard_base_url: str,
) -> str:
    kinds = {item.kind for item in transitions}
    kind_label = next(iter(kinds)).label if len(kinds) == 1 else "상황변경"
    delayed = any(item.delayed for item in transitions)
    reference_at = max(item.detected_at for item in transitions)
    warning_labels = list(dict.fromkeys(
        f"{item.impact.region} {item.impact.warning_type} {item.impact.raw_level}"
        for item in transitions
    ))
    facility_names = list(dict.fromkeys(item.impact.facility_name for item in transitions))
    facility_preview = ", ".join(facility_names[:5])
    if len(facility_names) > 5:
        facility_preview += f" 외 {len(facility_names) - 5}곳"

    current_grades = [
        item.current.risk_grade
        for item in transitions
        if item.current is not None
    ]
    grade_counts = []
    for grade in (RiskGrade.HIGH, RiskGrade.MEDIUM, RiskGrade.LOW, RiskGrade.UNASSESSED):
        count = sum(item is grade for item in current_grades)
        if count:
            grade_counts.append(f"{_GRADE_LABEL[grade]} {count}")
    grade_text = " · ".join(grade_counts) or "영향 종료"

    active = [item for item in transitions if item.kind is not AlertTransitionKind.CLEARED]
    if active:
        primary = max(active, key=lambda item: _GRADE_RANK[item.impact.risk_grade])
        action = primary.impact.recommended_action
    else:
        action = "특보 영향 종료 후 시설 이상 유무를 최종 확인해 주세요."

    facility_ids = sorted({item.impact.facility_id for item in transitions})
    if len(facility_ids) == 1:
        url = build_facility_url(dashboard_base_url, facility_ids[0])
    else:
        url = dashboard_home_url(dashboard_base_url)
    delay_text = "[지연 알림] " if delayed else ""
    warning_text = " / ".join(warning_labels[:4])
    if len(warning_labels) > 4:
        warning_text += f" 외 {len(warning_labels) - 4}건"
    lines = [
        f"[K-ECO 재난안전][{kind_label}] {delay_text}{reference_at:%m/%d %H:%M}",
        f"특보: {warning_text}",
        f"담당시설 {len(facility_names)}곳 · {grade_text}",
        f"시설: {facility_preview}",
        f"조치: {action}",
    ]
    if url:
        lines.append(f"확인: {url}")
    return "\n".join(lines)
