"""Firestore 자동알림 저장소의 호환 facade.

기존 Worker와 API는 이 클래스의 생성자와 메서드를 계속 사용한다. 실제
저장 책임은 상태, SMS, Telegram outbox, 실적·감사 모듈로 나뉘어져 있다.
"""

from __future__ import annotations

from safety_dashboard.adapters.firestore_alert_audit import (
    FirestoreAlertAuditRepository,
)
from safety_dashboard.adapters.firestore_alert_common import (
    ALERT_COLLECTIONS,
    KST,
    FirestoreAlertCollections,
    FirestoreAlertStoreBase,
    _provider_status,
)
from safety_dashboard.adapters.firestore_alert_delivery import (
    FirestoreAlertDeliveryRepository,
)
from safety_dashboard.adapters.firestore_alert_outbox import (
    FirestoreTelegramOutboxRepository,
)
from safety_dashboard.adapters.firestore_alert_state import (
    FirestoreAlertStateRepository,
)


class FirestoreAlertStore(
    FirestoreAlertStateRepository,
    FirestoreAlertDeliveryRepository,
    FirestoreTelegramOutboxRepository,
    FirestoreAlertAuditRepository,
    FirestoreAlertStoreBase,
):
    """기존 `AlertStateStore`와 관리자 API 계약을 유지하는 facade."""


__all__ = [
    "ALERT_COLLECTIONS",
    "KST",
    "FirestoreAlertCollections",
    "FirestoreAlertStore",
    "_provider_status",
]
