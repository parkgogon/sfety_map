"""Telegram outbox 생성, 재시도와 결과 보고를 담당합니다."""

from __future__ import annotations

import datetime as dt
import hashlib
import html

from safety_dashboard.adapters.telegram import TelegramNotifier
from safety_dashboard.alerts.domain import (
    AlertBatch,
    AlertTransitionKind,
    TelegramAudience,
    TelegramOutboxItem,
    TelegramPurpose,
)
from safety_dashboard.alerts.messages import build_alert_batch_telegram_payloads
from safety_dashboard.alerts.ports import AlertStateStore
from safety_dashboard.alerts.settings import AlertSettings
from safety_dashboard.domain.models import OutgoingTelegramMessage


KST = dt.timezone(dt.timedelta(hours=9))


class TelegramOutboxService:
    def __init__(
        self,
        store: AlertStateStore,
        settings: AlertSettings,
        admin_notifier: TelegramNotifier | None,
        user_notifier: TelegramNotifier | None,
    ) -> None:
        self.store = store
        self.settings = settings
        self.admin_notifier = admin_notifier
        self.user_notifier = user_notifier

    def notify_admin(
        self,
        key: str,
        now: dt.datetime,
        text: str,
        *,
        force: bool = False,
    ) -> None:
        due = self.store.admin_notice_due(key, now, dt.timedelta(hours=1))
        if not due and not force:
            return
        time_key = now.astimezone(KST).strftime(
            "%Y%m%d%H%M%S" if force else "%Y%m%d%H"
        )
        self.store.enqueue_telegram(TelegramOutboxItem(
            id=(
                "admin-"
                + hashlib.sha256(f"{key}|{time_key}".encode()).hexdigest()[:24]
            ),
            audience=TelegramAudience.ADMIN,
            purpose=TelegramPurpose.SYSTEM,
            created_at=now,
            expires_at=now + dt.timedelta(
                seconds=self.settings.telegram_retry_seconds
            ),
            next_attempt_at=now,
            messages=(OutgoingTelegramMessage(text=html.escape(text)),),
        ))

    def enqueue_user_batch(
        self,
        batch: AlertBatch,
        now: dt.datetime,
        purpose: TelegramPurpose,
        reason: str,
        payloads: tuple[OutgoingTelegramMessage, ...] = (),
    ) -> None:
        prefix = (
            "user-primary"
            if purpose is TelegramPurpose.USER_PRIMARY
            else "user-fallback"
        )
        self.store.enqueue_telegram(TelegramOutboxItem(
            id=f"{prefix}-{batch.id}",
            audience=TelegramAudience.USER,
            purpose=purpose,
            created_at=now,
            expires_at=now + dt.timedelta(
                seconds=self.settings.telegram_retry_seconds
            ),
            next_attempt_at=now,
            batch_id=batch.id,
            reason=reason,
            messages=payloads,
        ))

    def enqueue_batch_summary(
        self,
        batch: AlertBatch,
        route: str,
        messages: int,
        accepted: int,
        failed: int,
        unknown: int,
        blocked: int,
        unmapped: int,
        fallback_queued: bool,
    ) -> None:
        warning_counts = {
            kind: len({
                item.impact.warning_key
                for item in batch.transitions
                if item.kind is kind
            })
            for kind in AlertTransitionKind
        }
        affected_facilities = len({
            item.impact.facility_id for item in batch.transitions
        })
        text = (
            "📨 <b>자동 재난특보 알림 처리</b>\n"
            f"전달 경로 · {html.escape(route)}\n"
            f"발효 {warning_counts[AlertTransitionKind.ACTIVATED]} · "
            f"격상 {warning_counts[AlertTransitionKind.ESCALATED]} · "
            f"해제 {warning_counts[AlertTransitionKind.CLEARED]}\n"
            f"영향시설 {affected_facilities}곳 · "
            f"메시지 {messages}건 · 문자 접수 {accepted} · "
            f"접수 실패 {failed} · 확인 불가 {unknown} · "
            f"상한 차단 {blocked} · 연락처 미매핑 시설 {unmapped}\n"
            f"사용자 Telegram 대체 · "
            f"{'예약' if fallback_queued else '없음'}\n"
            f"정책 {html.escape(batch.policy_version)}"
        )
        self.store.enqueue_telegram(TelegramOutboxItem(
            id=f"admin-batch-{batch.id}",
            audience=TelegramAudience.ADMIN,
            purpose=TelegramPurpose.SYSTEM,
            created_at=batch.created_at,
            expires_at=batch.created_at + dt.timedelta(
                seconds=self.settings.telegram_retry_seconds
            ),
            next_attempt_at=batch.created_at,
            batch_id=batch.id,
            messages=(OutgoingTelegramMessage(text=text),),
        ))

    def drain(self, now: dt.datetime) -> None:
        # 사용자 결과로 새로 생긴 관리자 알림도 같은 회차에 발송합니다.
        for _ in range(5):
            due = self.store.due_telegram(now)
            if not due:
                return
            for item in due:
                self._deliver(item, now)

    def _deliver(self, item: TelegramOutboxItem, now: dt.datetime) -> None:
        messages = self._messages(item)
        notifier = (
            self.admin_notifier
            if item.audience is TelegramAudience.ADMIN
            else self.user_notifier
        )
        if notifier is None:
            success = False
            detail = f"{item.audience.value} Telegram 설정값이 없습니다."
        elif not messages:
            success = False
            detail = "Telegram 발송 내용을 구성하지 못했습니다."
        else:
            result = notifier.send_batch(messages)
            success = bool(getattr(result, "success", True))
            detail = str(getattr(result, "message", "Telegram 발송 완료"))
        self.store.record_telegram_result(item, success, detail, now)
        self.store.update_status({
            f"last_{item.audience.value}_telegram_at": now,
            f"last_{item.audience.value}_telegram_result": (
                "SENT" if success else "FAILED"
            ),
            f"last_{item.audience.value}_telegram_detail": detail,
        })
        if item.audience is TelegramAudience.USER:
            final_failure = not success and (
                _aware(now) + dt.timedelta(minutes=5) > _aware(item.expires_at)
            )
            if success or final_failure:
                self._enqueue_user_delivery_result(
                    item,
                    now,
                    success,
                    detail,
                )

    def _messages(
        self, item: TelegramOutboxItem
    ) -> tuple[OutgoingTelegramMessage, ...]:
        messages = item.messages
        if messages or not item.batch_id:
            return messages
        if item.purpose in {
            TelegramPurpose.USER_PRIMARY,
            TelegramPurpose.SMS_FALLBACK,
        }:
            batch = self.store.load_batch(item.batch_id)
            if batch is not None:
                return build_alert_batch_telegram_payloads(
                    batch,
                    self.settings.dashboard_base_url,
                    item.reason
                    if item.purpose is TelegramPurpose.SMS_FALLBACK
                    else "",
                )
        if item.purpose is TelegramPurpose.SMS_FINAL:
            summary = self.store.delivery_summary(item.batch_id)
            return (OutgoingTelegramMessage(text=(
                "📬 <b>문자 최종 전달 결과</b>\n"
                f"수신 완료 {summary.get('delivered', 0)} · "
                f"실패 {summary.get('failed', 0)} · "
                f"결과 대기 {summary.get('accepted', 0)}\n"
                f"배치 {html.escape(item.batch_id)}"
            )),)
        return ()

    def _enqueue_user_delivery_result(
        self,
        item: TelegramOutboxItem,
        now: dt.datetime,
        success: bool,
        detail: str,
    ) -> None:
        route = (
            "SMS 대체 전파"
            if item.purpose is TelegramPurpose.SMS_FALLBACK
            else (
                "관리자 수동 전파"
                if item.purpose is TelegramPurpose.MANUAL
                else "주경로 전파"
            )
        )
        state = "성공" if success else "30분 재시도 후 실패"
        text = (
            f"{'✅' if success else '🚨'} <b>사용자 Telegram {state}</b>\n"
            f"경로 · {route}\n"
            f"배치 · {html.escape(item.batch_id or item.id)}\n"
            f"결과 · {html.escape(detail)}"
        )
        self.store.enqueue_telegram(TelegramOutboxItem(
            id=f"admin-user-result-{item.id}",
            audience=TelegramAudience.ADMIN,
            purpose=TelegramPurpose.SYSTEM,
            created_at=now,
            expires_at=now + dt.timedelta(
                seconds=self.settings.telegram_retry_seconds
            ),
            next_attempt_at=now,
            batch_id=item.batch_id,
            messages=(OutgoingTelegramMessage(text=text, silent=success),),
        ))


def _aware(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo else value.replace(tzinfo=KST)
