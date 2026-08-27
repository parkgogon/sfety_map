"""Firestore 자동알림 저장소의 공통 스키마와 직렬화 도구."""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from google.cloud import firestore

from safety_dashboard.alerts.domain import (
    AlertTransition,
    AlertTransitionKind,
    FacilityImpact,
    ManualDispatchStatus,
    ManualTelegramCategory,
    NotificationEvent,
    SmsDeliveryStatus,
    TelegramAudience,
    TelegramOutboxItem,
    TelegramPurpose,
)
from safety_dashboard.domain.enums import RiskGrade, WarningLevel
from safety_dashboard.domain.models import OutgoingTelegramMessage


KST = dt.timezone(dt.timedelta(hours=9))


@dataclass(frozen=True)
class FirestoreAlertCollections:
    """자동알림에서 사용하는 기존 Firestore collection 이름."""

    state: str = "alert_state"
    batches: str = "alert_batches"
    pending: str = "alert_pending"
    deliveries: str = "alert_deliveries"
    provider_messages: str = "alert_provider_messages"
    metrics: str = "alert_metrics"
    admin_notices: str = "alert_admin_notices"
    telegram_outbox: str = "alert_telegram_outbox"
    manual_dispatches: str = "alert_manual_dispatches"


ALERT_COLLECTIONS = FirestoreAlertCollections()


class FirestoreAlertStoreBase:
    """책임별 mixin이 공유하는 Firestore client와 기본 문서."""

    collections = ALERT_COLLECTIONS

    def __init__(self, project_id: str = "", *, client: Any | None = None) -> None:
        self.client = client or firestore.Client(project=project_id or None)
        state = self.client.collection(self.collections.state)
        self.state_ref = state.document("current")
        self.lock_ref = state.document("dispatch_lock")
        self.status_ref = state.document("status")


def _impact_to_dict(value: FacilityImpact) -> dict[str, object]:
    return {
        "key": value.key,
        "facility_id": value.facility_id,
        "facility_name": value.facility_name,
        "warning_key": value.warning_key,
        "warning_id": value.warning_id,
        "region_code": value.region_code,
        "region": value.region,
        "warning_type": value.warning_type,
        "raw_level": value.raw_level,
        "warning_level": value.warning_level.value,
        "risk_grade": value.risk_grade.value,
        "issued_at": _iso(value.issued_at),
        "effective_at": _iso(value.effective_at),
        "recommended_action": value.recommended_action,
    }


def _impact_from_dict(value: Mapping[str, object]) -> FacilityImpact:
    return FacilityImpact(
        key=str(value["key"]),
        facility_id=str(value["facility_id"]),
        facility_name=str(value["facility_name"]),
        warning_key=str(value["warning_key"]),
        warning_id=str(value["warning_id"]),
        region_code=str(value["region_code"]),
        region=str(value["region"]),
        warning_type=str(value["warning_type"]),
        raw_level=str(value["raw_level"]),
        warning_level=WarningLevel(str(value["warning_level"])),
        risk_grade=RiskGrade(str(value["risk_grade"])),
        issued_at=_parse_datetime(value.get("issued_at")),
        effective_at=_parse_datetime(value.get("effective_at")),
        recommended_action=str(value.get("recommended_action", "")),
    )


def _transition_to_dict(value: AlertTransition) -> dict[str, object]:
    return {
        "id": value.id,
        "kind": value.kind.value,
        "detected_at": value.detected_at.isoformat(),
        "previous": _impact_to_dict(value.previous) if value.previous else None,
        "current": _impact_to_dict(value.current) if value.current else None,
        "delayed": value.delayed,
    }


def _transition_from_dict(value: Mapping[str, object]) -> AlertTransition:
    previous = value.get("previous")
    current = value.get("current")
    return AlertTransition(
        id=str(value["id"]),
        kind=AlertTransitionKind(str(value["kind"])),
        detected_at=_parse_datetime(value.get("detected_at"))
        or dt.datetime.now(dt.timezone.utc),
        previous=_impact_from_dict(previous) if isinstance(previous, Mapping) else None,
        current=_impact_from_dict(current) if isinstance(current, Mapping) else None,
        delayed=bool(value.get("delayed", False)),
    )


def _provider_status(code: str) -> SmsDeliveryStatus:
    # SINGLE-REPORT 웹훅은 개별 메시지 처리가 끝난 뒤 호출된다.
    # SOLAPI에서 4000만 '수신 완료'이며, 나머지 최종 코드는 실패로 집계한다.
    if code == "4000":
        return SmsDeliveryStatus.DELIVERED
    return SmsDeliveryStatus.FAILED


def _transition_fingerprint(transitions: object) -> str:
    facility_ids: set[str] = set()
    warning_keys: set[str] = set()
    if isinstance(transitions, Sequence):
        for transition in transitions:
            if not isinstance(transition, Mapping):
                continue
            impact = transition.get("current") or transition.get("previous") or {}
            if not isinstance(impact, Mapping):
                continue
            facility_ids.add(str(impact.get("facility_id", "")))
            warning_keys.add(str(impact.get("warning_key", "")))
    identity = "|".join((
        ",".join(sorted(item for item in facility_ids if item)),
        ",".join(sorted(item for item in warning_keys if item)),
    ))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def _automatic_event_from_dict(
    event_id: str, values: Mapping[str, object]
) -> NotificationEvent:
    transitions = values.get("transitions", [])
    kinds: set[str] = set()
    facility_ids: set[str] = set()
    warning_keys: set[str] = set()
    if isinstance(transitions, Sequence):
        for transition in transitions:
            if not isinstance(transition, Mapping):
                continue
            try:
                kinds.add(AlertTransitionKind(str(transition.get("kind", ""))).label)
            except ValueError:
                kinds.add(str(transition.get("kind", "상황변경")))
            impact = transition.get("current") or transition.get("previous") or {}
            if isinstance(impact, Mapping):
                facility_ids.add(str(impact.get("facility_id", "")))
                warning_keys.add(str(impact.get("warning_key", "")))
    route = str(values.get("delivery_route", "telegram"))
    event_status = str(values.get("telegram_status", ""))
    if not event_status:
        event_status = (
            "PREVIEW"
            if values.get("mode") == "preview"
            else ("PENDING" if route == "telegram" else str(values.get("status", "")))
        )
    return NotificationEvent(
        id=event_id,
        occurred_at=_parse_datetime(values.get("created_at"))
        or dt.datetime.now(dt.timezone.utc),
        source="automatic",
        event=next(iter(kinds)) if len(kinds) == 1 else "상황변경",
        status=event_status,
        channel="사용자 Telegram" if route != "sms" else "SOLAPI 문자",
        facility_count=len({item for item in facility_ids if item}),
        warning_count=len({item for item in warning_keys if item}),
        detail=str(values.get("telegram_detail", "")),
    )


def _manual_event_from_dict(
    event_id: str, values: Mapping[str, object]
) -> NotificationEvent:
    category_value = str(values.get("category", ""))
    try:
        label = ManualTelegramCategory(category_value).label
    except ValueError:
        label = category_value or "수동 전파"
    return NotificationEvent(
        id=event_id,
        occurred_at=_parse_datetime(values.get("created_at"))
        or dt.datetime.now(dt.timezone.utc),
        source="manual",
        event=label,
        status=str(values.get("status", ManualDispatchStatus.PENDING.value)),
        channel="사용자 Telegram",
        facility_count=len(set(values.get("facility_ids", []))),
        warning_count=len(set(values.get("warning_keys", []))),
        detail=str(values.get("last_detail", "")),
        category=category_value,
        operator_label=str(values.get("operator_label", "")),
    )


def _telegram_message_to_dict(value: OutgoingTelegramMessage) -> dict[str, object]:
    return {
        "text": value.text,
        "silent": value.silent,
        "action_label": value.action_label,
        "action_url": value.action_url,
    }


def _telegram_job_from_dict(
    item_id: str,
    values: Mapping[str, object],
) -> TelegramOutboxItem:
    messages = values.get("messages", [])
    return TelegramOutboxItem(
        id=item_id,
        audience=TelegramAudience(str(values.get("audience", "admin"))),
        purpose=TelegramPurpose(str(values.get("purpose", "system"))),
        created_at=_parse_datetime(values.get("created_at"))
        or dt.datetime.now(dt.timezone.utc),
        expires_at=_parse_datetime(values.get("expires_at"))
        or dt.datetime.now(dt.timezone.utc),
        next_attempt_at=_parse_datetime(values.get("next_attempt_at"))
        or dt.datetime.now(dt.timezone.utc),
        batch_id=str(values.get("batch_id", "")),
        reason=str(values.get("reason", "")),
        messages=tuple(
            OutgoingTelegramMessage(
                text=str(item.get("text", "")),
                silent=bool(item.get("silent", False)),
                action_label=str(item.get("action_label", "")),
                action_url=str(item.get("action_url", "")),
            )
            for item in messages
            if isinstance(item, Mapping)
        ),
        metric_scope=str(values.get("metric_scope", "operational")),
        attempt_count=int(values.get("attempt_count", 0)),
    )


def _telegram_metric(
    item: TelegramOutboxItem,
    success: bool,
    expired: bool,
) -> str:
    if success:
        if item.audience is TelegramAudience.ADMIN:
            return "telegram_admin_sent"
        if item.purpose is TelegramPurpose.SMS_FALLBACK:
            return "telegram_user_fallback_sent"
        return "telegram_user_primary_sent"
    if expired:
        return (
            "telegram_admin_failed"
            if item.audience is TelegramAudience.ADMIN
            else "telegram_user_failed"
        )
    return ""


def _parse_datetime(value: object) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _aware(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


def _iso(value: object) -> str:
    return (
        value.isoformat()
        if isinstance(value, (dt.datetime, dt.date))
        else str(value or "")
    )


def _json_safe(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    return value
