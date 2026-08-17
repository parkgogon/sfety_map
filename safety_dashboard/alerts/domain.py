"""자동 특보 알림의 순수 도메인 모델."""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from safety_dashboard.domain.enums import RiskGrade, WarningLevel
from safety_dashboard.domain.models import OutgoingTelegramMessage


class AlertTransitionKind(str, Enum):
    ACTIVATED = "ACTIVATED"
    ESCALATED = "ESCALATED"
    CLEARED = "CLEARED"

    @property
    def label(self) -> str:
        return {
            AlertTransitionKind.ACTIVATED: "발효",
            AlertTransitionKind.ESCALATED: "격상",
            AlertTransitionKind.CLEARED: "해제",
        }[self]


class SmsDeliveryStatus(str, Enum):
    RESERVED = "RESERVED"
    ACCEPTED = "ACCEPTED"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    PREVIEW = "PREVIEW"
    BLOCKED_CAP = "BLOCKED_CAP"


class UserDeliveryMode(str, Enum):
    TELEGRAM = "telegram"
    SMS = "sms"


class TelegramAudience(str, Enum):
    ADMIN = "admin"
    USER = "user"


class TelegramPurpose(str, Enum):
    SYSTEM = "system"
    USER_PRIMARY = "user_primary"
    SMS_FALLBACK = "sms_fallback"
    SMS_FINAL = "sms_final"
    DAILY_DIGEST = "daily_digest"
    TEST = "test"
    HEARTBEAT = "heartbeat"
    MANUAL = "manual"


class ManualTelegramCategory(str, Enum):
    REMINDER = "REMINDER"
    CORRECTION = "CORRECTION"
    ADDITIONAL = "ADDITIONAL"
    DRILL = "DRILL"

    @property
    def label(self) -> str:
        return {
            ManualTelegramCategory.REMINDER: "재공지",
            ManualTelegramCategory.CORRECTION: "정정",
            ManualTelegramCategory.ADDITIONAL: "추가안내",
            ManualTelegramCategory.DRILL: "훈련",
        }[self]


class ManualDispatchStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    RETRY_QUEUED = "RETRY_QUEUED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class HealthCheck:
    name: str
    healthy: bool
    detail: str
    latency_ms: int | None = None


@dataclass(frozen=True)
class OperationalHealthReport:
    checked_at: dt.datetime
    checks: tuple[HealthCheck, ...]

    @property
    def healthy(self) -> bool:
        return all(item.healthy for item in self.checks)


@dataclass(frozen=True)
class FacilityRecipient:
    facility_id: str
    recipient_name: str
    phone: str
    note: str = ""


@dataclass(frozen=True)
class ContactDirectory:
    recipients: tuple[FacilityRecipient, ...]
    revision: str
    fetched_at: dt.datetime

    def for_facility(self, facility_id: str) -> tuple[FacilityRecipient, ...]:
        return tuple(
            item for item in self.recipients if item.facility_id == facility_id
        )

    @property
    def unique_phone_count(self) -> int:
        return len({item.phone for item in self.recipients})


@dataclass(frozen=True)
class FacilityImpact:
    """시설과 활성 특보 하나의 연결 상태."""

    key: str
    facility_id: str
    facility_name: str
    warning_key: str
    warning_id: str
    region_code: str
    region: str
    warning_type: str
    raw_level: str
    warning_level: WarningLevel
    risk_grade: RiskGrade
    issued_at: dt.datetime | None
    effective_at: dt.datetime | None
    recommended_action: str

    @property
    def fingerprint(self) -> str:
        values = (
            self.key,
            self.warning_id,
            self.raw_level,
            self.warning_level.value,
            self.risk_grade.value,
            self.issued_at.isoformat() if self.issued_at else "",
        )
        return hashlib.sha256("|".join(values).encode("utf-8")).hexdigest()[:20]


@dataclass(frozen=True)
class AlertTransition:
    id: str
    kind: AlertTransitionKind
    detected_at: dt.datetime
    previous: FacilityImpact | None
    current: FacilityImpact | None
    delayed: bool = False

    @property
    def impact(self) -> FacilityImpact:
        value = self.current or self.previous
        if value is None:  # pragma: no cover - 생성자 오용 방어
            raise ValueError("알림 변화에는 이전 또는 현재 영향 상태가 필요합니다.")
        return value


@dataclass(frozen=True)
class AlertBatch:
    id: str
    created_at: dt.datetime
    transitions: tuple[AlertTransition, ...]
    mode: str
    policy_version: str = ""


@dataclass(frozen=True)
class OutgoingSmsMessage:
    id: str
    batch_id: str
    recipient_hash: str
    phone: str
    text: str
    facility_ids: tuple[str, ...]
    transition_ids: tuple[str, ...]


@dataclass(frozen=True)
class SmsDeliveryResult:
    status: SmsDeliveryStatus
    provider_message_id: str = ""
    provider_group_id: str = ""
    detail: str = ""


@dataclass(frozen=True)
class SolapiBalance:
    balance: int
    point: int
    fetched_at: dt.datetime

    @property
    def available(self) -> int:
        return self.balance + self.point


@dataclass(frozen=True)
class TelegramOutboxItem:
    id: str
    audience: TelegramAudience
    purpose: TelegramPurpose
    created_at: dt.datetime
    expires_at: dt.datetime
    next_attempt_at: dt.datetime
    batch_id: str = ""
    reason: str = ""
    messages: tuple[OutgoingTelegramMessage, ...] = ()
    metric_scope: str = "operational"
    attempt_count: int = 0


@dataclass(frozen=True)
class ManualTelegramDispatch:
    id: str
    created_at: dt.datetime
    category: ManualTelegramCategory
    operator_label: str
    note: str
    mode: str
    facility_ids: tuple[str, ...]
    warning_keys: tuple[str, ...]
    messages: tuple[OutgoingTelegramMessage, ...]
    policy_version: str = ""
    temporary_policy: bool = False

    @property
    def fingerprint(self) -> str:
        identity = "|".join((
            ",".join(sorted(set(self.facility_ids))),
            ",".join(sorted(set(self.warning_keys))),
        ))
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class NotificationEvent:
    id: str
    occurred_at: dt.datetime
    source: str
    event: str
    status: str
    channel: str
    facility_count: int
    warning_count: int
    detail: str = ""
    category: str = ""
    operator_label: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "occurred_at": self.occurred_at.isoformat(),
            "source": self.source,
            "event": self.event,
            "status": self.status,
            "channel": self.channel,
            "facility_count": self.facility_count,
            "warning_count": self.warning_count,
            "detail": self.detail,
            "category": self.category,
            "operator_label": self.operator_label,
        }


def make_batch_id(transitions: Iterable[AlertTransition]) -> str:
    identity = "|".join(sorted(item.id for item in transitions))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
