"""시설담당자별 문자 내용을 구성합니다."""

from __future__ import annotations

import hashlib
import hmac
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
