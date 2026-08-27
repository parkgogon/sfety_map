"""SOLAPI 결과 웹훅과 전화번호 없는 관리자 실적 조회."""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import hmac
import html
import io
import re
from collections.abc import Mapping, Sequence
from typing import Any, Callable

from safety_dashboard.adapters.firestore_alerts import KST
from safety_dashboard.alerts.domain import (
    ManualDispatchStatus,
    ManualTelegramCategory,
    ManualTelegramDispatch,
    NotificationEvent,
    TelegramAudience,
    TelegramOutboxItem,
    TelegramPurpose,
)
from safety_dashboard.domain.models import OutgoingTelegramMessage
from safety_dashboard.domain.models import DashboardSnapshot
from safety_dashboard.alerts.ports import SystemHealthProbe
from safety_dashboard.alerts.settings import AlertSettings


class AlertAdminConfigurationError(RuntimeError):
    pass


class AlertAdminAuthorizationError(PermissionError):
    pass


class ManualDispatchValidationError(ValueError):
    pass


class ManualDispatchDuplicateError(RuntimeError):
    def __init__(self, event: NotificationEvent) -> None:
        super().__init__("최근 30분 내 유사한 전파 기록이 있습니다.")
        self.event = event


_PHONE_PATTERN = re.compile(r"(?<!\d)0\d{1,2}[- .]?\d{3,4}[- .]?\d{4}(?!\d)")


class AlertAdminService:
    def __init__(
        self,
        store: Any,
        settings: AlertSettings,
        *,
        user_telegram: Any | None = None,
        admin_telegram: Any | None = None,
        health_probe: SystemHealthProbe | None = None,
        manual_snapshot_provider: Callable[..., DashboardSnapshot] | None = None,
    ) -> None:
        self.store = store
        self.settings = settings
        self.user_telegram = user_telegram
        self.admin_telegram = admin_telegram
        self.health_probe = health_probe
        self.manual_snapshot_provider = manual_snapshot_provider
        self._health_cache: tuple[dt.datetime, dict[str, object]] | None = None

    def authorize_admin(self, token: str) -> None:
        expected = self.settings.admin_token
        if not expected:
            raise AlertAdminConfigurationError("관리자 통계 토큰이 없습니다.")
        if not hmac.compare_digest(token, expected):
            raise AlertAdminAuthorizationError("관리자 인증에 실패했습니다.")

    def status(self) -> dict[str, object]:
        values = dict(self.store.notification_status())
        values.setdefault("mode", self.settings.automation_mode)
        values.setdefault("user_delivery_mode", self.settings.user_delivery_mode)
        values["daily_cap"] = self.settings.daily_cap
        values["cap_warning"] = self.settings.cap_warning
        values["monthly_cap"] = self.settings.monthly_cap
        values["monthly_cap_warning"] = self.settings.monthly_cap_warning
        today = dt.datetime.now(KST).date()
        values["sms_today"] = self.store.sms_count(today)
        values["sms_month"] = self.store.monthly_sms_count(today)
        return values

    def overview(self, now: dt.datetime | None = None) -> dict[str, object]:
        checked_at = now or dt.datetime.now(KST)
        values = self.status()
        last_run = _optional_datetime(values.get("last_run_at"))
        worker_fresh = bool(
            last_run
            and checked_at.astimezone(dt.timezone.utc)
            - last_run.astimezone(dt.timezone.utc)
            <= dt.timedelta(minutes=10)
        )
        checks = self._health_checks(checked_at)
        kma_live = values.get("kma_health") == "LIVE"
        mode_live = values.get("mode") == "live"
        healthy = worker_fresh and kma_live and mode_live and all(
            bool(item.get("healthy")) for item in checks
        )
        values.update({
            "checked_at": checked_at.isoformat(),
            "healthy": healthy,
            "worker_fresh": worker_fresh,
            "worker_detail": (
                "최근 10분 이내 실행"
                if worker_fresh
                else "최근 실행이 없거나 10분 이상 지연"
            ),
            "checks": checks,
        })
        return values

    def metrics(self, start: dt.date, end: dt.date) -> dict[str, object]:
        _validate_period(start, end)
        return self.store.notification_metrics(start, end)

    def events(
        self,
        start: dt.datetime,
        end: dt.datetime,
        *,
        source: str = "all",
        status: str = "all",
        limit: int = 100,
    ) -> tuple[dict[str, object], ...]:
        if end <= start:
            raise ValueError("종료 시각은 시작 시각보다 늦어야 합니다.")
        if end - start > dt.timedelta(days=366):
            raise ValueError("한 번에 최대 1년까지 조회할 수 있습니다.")
        if source not in {"all", "automatic", "manual"}:
            raise ValueError("지원하지 않는 전파 출처입니다.")
        if limit < 1 or limit > 200:
            raise ValueError("이력은 한 번에 1~200건까지 조회할 수 있습니다.")
        return tuple(
            item.as_dict()
            for item in self.store.notification_events(
                start, end, source=source, status=status, limit=limit
            )
        )

    def dispatch_manual(
        self,
        value: ManualTelegramDispatch,
        *,
        allow_duplicate: bool = False,
    ) -> dict[str, object]:
        value = _validated_manual(value)
        self._validate_manual_scope(value)
        existing = self.store.manual_dispatch(value.id)
        if existing is not None:
            return {
                "status": str(existing.get("status", ManualDispatchStatus.PENDING.value)),
                "dispatch_id": value.id,
                "idempotent": True,
                "detail": str(existing.get("last_detail", "이미 접수된 요청입니다.")),
            }
        if self.user_telegram is None:
            raise AlertAdminConfigurationError("시설담당자 Telegram 그룹이 설정되지 않았습니다.")
        duplicate = self.store.recent_duplicate(
            value.fingerprint,
            value.created_at - dt.timedelta(minutes=30),
        )
        if duplicate is not None and not allow_duplicate:
            raise ManualDispatchDuplicateError(duplicate)
        if not self.store.create_manual_dispatch(value):
            existing = self.store.manual_dispatch(value.id) or {}
            return {
                "status": str(existing.get("status", ManualDispatchStatus.PENDING.value)),
                "dispatch_id": value.id,
                "idempotent": True,
                "detail": str(existing.get("last_detail", "이미 접수된 요청입니다.")),
            }

        result = self.user_telegram.send_batch(value.messages)
        success = bool(getattr(result, "success", False))
        detail = str(getattr(result, "message", "Telegram 발송 결과 미확인"))
        sent_count = max(0, min(
            len(value.messages),
            int(getattr(result, "sent_count", 0) or 0),
        ))
        metric_prefix = (
            "manual_drill"
            if value.category is ManualTelegramCategory.DRILL
            else "telegram_manual"
        )
        if success:
            self.store.update_manual_dispatch(value.id, {
                "status": ManualDispatchStatus.SENT.value,
                "completed_at": value.created_at,
                "last_attempt_at": value.created_at,
                "last_detail": detail,
            })
            self.store.record_run(
                value.created_at.astimezone(KST).date(),
                {f"{metric_prefix}_sent": 1},
            )
            self._report_manual_result(value, True, detail)
            return {
                "status": ManualDispatchStatus.SENT.value,
                "dispatch_id": value.id,
                "idempotent": False,
                "detail": detail,
            }

        remaining_messages = value.messages[sent_count:] or value.messages
        outbox = TelegramOutboxItem(
            id=f"user-manual-{value.id}",
            audience=TelegramAudience.USER,
            purpose=TelegramPurpose.MANUAL,
            created_at=value.created_at,
            expires_at=value.created_at + dt.timedelta(minutes=30),
            next_attempt_at=value.created_at + dt.timedelta(minutes=5),
            batch_id=value.id,
            reason=detail,
            messages=remaining_messages,
            metric_scope=(
                "drill"
                if value.category is ManualTelegramCategory.DRILL
                else "manual"
            ),
        )
        self.store.enqueue_telegram(outbox)
        self.store.update_manual_dispatch(value.id, {
            "status": ManualDispatchStatus.RETRY_QUEUED.value,
            "last_attempt_at": value.created_at,
            "last_detail": detail,
        })
        return {
            "status": ManualDispatchStatus.RETRY_QUEUED.value,
            "dispatch_id": value.id,
            "idempotent": False,
            "detail": "즉시 발송에 실패해 30분 재시도를 예약했습니다.",
        }

    def export_csv(self, start: dt.date, end: dt.date) -> bytes:
        _validate_period(start, end)
        start_at = dt.datetime.combine(start, dt.time.min, tzinfo=KST)
        end_at = dt.datetime.combine(
            end + dt.timedelta(days=1),
            dt.time.min,
            tzinfo=KST,
        )
        rows = self.store.export_rows(start_at, end_at)
        output = io.StringIO()
        columns = (
            "record_type",
            "source",
            "timestamp",
            "event",
            "facility_id",
            "facility_name",
            "warning",
            "recipient_code",
            "delivery_status",
            "category",
            "operator_label",
        )
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue().encode("utf-8-sig")

    def apply_webhook(
        self,
        supplied_secret_hash: str,
        events: Sequence[Mapping[str, object]],
    ) -> int:
        secret = self.settings.solapi_webhook_secret
        if not secret:
            raise AlertAdminConfigurationError("SOLAPI 웹훅 비밀값이 없습니다.")
        expected = hashlib.sha1(secret.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(supplied_secret_hash, expected):
            raise AlertAdminAuthorizationError("웹훅 인증에 실패했습니다.")
        changed = 0
        for event in events:
            message_id = str(event.get("messageId", "")).strip()
            status_code = str(event.get("statusCode", "")).strip()
            if not message_id or not status_code:
                continue
            processed_at = _parse_datetime(
                event.get("dateReported") or event.get("dateProcessed")
            )
            custom_fields = event.get("customFields")
            delivery_id_hint = (
                str(custom_fields.get("deliveryId", ""))
                if isinstance(custom_fields, Mapping)
                else ""
            )
            changed += int(self.store.apply_provider_report(
                message_id,
                status_code,
                processed_at,
                delivery_id_hint,
            ))
        return changed

    def _health_checks(self, now: dt.datetime) -> list[dict[str, object]]:
        if self._health_cache is not None:
            cached_at, cached = self._health_cache
            if now - cached_at < dt.timedelta(seconds=60):
                return list(cached.get("checks", []))
        checks: list[dict[str, object]] = []
        if self.health_probe is not None:
            try:
                report = self.health_probe.check(now)
                checks = [
                    {
                        "name": item.name,
                        "healthy": item.healthy,
                        "detail": item.detail,
                        "latency_ms": item.latency_ms,
                    }
                    for item in report.checks
                ]
            except Exception as exc:
                checks = [{
                    "name": "운영 경로 점검",
                    "healthy": False,
                    "detail": type(exc).__name__,
                    "latency_ms": None,
                }]
        else:
            checks = [{
                "name": "운영 경로 점검",
                "healthy": False,
                "detail": "점검 제공자가 설정되지 않았습니다.",
                "latency_ms": None,
            }]
        self._health_cache = (now, {"checks": checks})
        return checks

    def _validate_manual_scope(self, value: ManualTelegramDispatch) -> None:
        if self.manual_snapshot_provider is None:
            return
        try:
            snapshot = self.manual_snapshot_provider(
                simulation=value.mode == "simulation"
            )
        except Exception as exc:
            raise AlertAdminConfigurationError(
                f"현재 관제 대상을 확인하지 못했습니다 ({type(exc).__name__})."
            ) from exc
        warnings_by_id = {
            item.id: f"{item.region_code}|{item.warning_type}"
            for item in snapshot.warning_feed.warnings
        }
        connected: dict[str, set[str]] = {}
        for assessment in snapshot.assessments:
            keys = {
                warnings_by_id[reason.warning_id]
                for reason in assessment.reasons
                if reason.warning_id in warnings_by_id
            }
            if keys:
                connected[assessment.facility.id] = keys
        selected_ids = set(value.facility_ids)
        invalid_ids = sorted(selected_ids - set(connected))
        if invalid_ids:
            raise ManualDispatchValidationError(
                "현재 특보 영향시설이 아닌 대상이 포함되어 있습니다."
            )
        expected_warning_keys = set().union(
            *(connected[facility_id] for facility_id in selected_ids)
        )
        if set(value.warning_keys) != expected_warning_keys:
            raise ManualDispatchValidationError(
                "선택 시설과 연결 특보 구성이 현재 관제 결과와 일치하지 않습니다."
            )

    def _report_manual_result(
        self,
        value: ManualTelegramDispatch,
        success: bool,
        detail: str,
    ) -> None:
        message = OutgoingTelegramMessage(
            text=(
                f"{'✅' if success else '🚨'} <b>시설담당자 그룹 수동 전파 "
                f"{'완료' if success else '실패'}</b>\n"
                f"구분 · {html.escape(value.category.label)}\n"
                f"시설 · {len(set(value.facility_ids))}곳\n"
                f"요청 · {html.escape(value.id)}\n"
                f"결과 · {html.escape(detail)}"
            ),
            silent=success,
        )
        result = (
            self.admin_telegram.send_batch((message,))
            if self.admin_telegram is not None
            else None
        )
        if result is not None and bool(getattr(result, "success", False)):
            return
        self.store.enqueue_telegram(TelegramOutboxItem(
            id=f"admin-manual-result-{value.id}",
            audience=TelegramAudience.ADMIN,
            purpose=TelegramPurpose.SYSTEM,
            created_at=value.created_at,
            expires_at=value.created_at + dt.timedelta(minutes=30),
            next_attempt_at=value.created_at + dt.timedelta(minutes=5),
            batch_id=value.id,
            messages=(message,),
        ))


def _validate_period(start: dt.date, end: dt.date) -> None:
    if end < start:
        raise ValueError("종료일은 시작일보다 빠를 수 없습니다.")
    if (end - start).days > 366:
        raise ValueError("한 번에 최대 1년까지 조회할 수 있습니다.")


def _validated_manual(value: ManualTelegramDispatch) -> ManualTelegramDispatch:
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", value.id):
        raise ManualDispatchValidationError("수동 전파 요청 ID가 올바르지 않습니다.")
    if value.mode not in {"live", "simulation"}:
        raise ManualDispatchValidationError("수동 전파 자료 모드가 올바르지 않습니다.")
    is_drill = value.category is ManualTelegramCategory.DRILL
    if is_drill != (value.mode == "simulation"):
        raise ManualDispatchValidationError(
            "모의훈련 자료는 훈련 분류로만 전파할 수 있습니다."
        )
    note = value.note.strip()
    if len(note) > 200:
        raise ManualDispatchValidationError("관리자 메모는 200자 이하여야 합니다.")
    if _PHONE_PATTERN.search(note):
        raise ManualDispatchValidationError(
            "관리자 메모에는 전화번호를 입력할 수 없습니다."
        )
    if value.category in {
        ManualTelegramCategory.CORRECTION,
        ManualTelegramCategory.ADDITIONAL,
    } and not note:
        raise ManualDispatchValidationError("정정·추가안내에는 관리자 메모가 필요합니다.")
    facility_ids = tuple(sorted({item.strip() for item in value.facility_ids if item.strip()}))
    warning_keys = tuple(sorted({item.strip() for item in value.warning_keys if item.strip()}))
    if not facility_ids or len(facility_ids) > 103:
        raise ManualDispatchValidationError("수동 전파 시설은 1~103곳이어야 합니다.")
    if not warning_keys or len(warning_keys) > 200:
        raise ManualDispatchValidationError("연결 특보 정보가 없습니다.")
    if not value.messages or len(value.messages) > 30:
        raise ManualDispatchValidationError("Telegram 메시지는 1~30건이어야 합니다.")
    for message in value.messages:
        if not message.text or len(message.text) > 3900:
            raise ManualDispatchValidationError(
                "Telegram 메시지 한 건은 3,900자 이하여야 합니다."
            )
        if "수동 상황전파" not in message.text and "상황전파" not in message.text:
            raise ManualDispatchValidationError("수동 전파 표시가 없는 메시지입니다.")
        if _PHONE_PATTERN.search(message.text):
            raise ManualDispatchValidationError(
                "수동 전파 메시지에 전화번호가 포함되어 있습니다."
            )
        if is_drill and (
            "모의훈련" not in message.text
            or ("실제 재난" not in message.text and "실제 상황" not in message.text)
        ):
            raise ManualDispatchValidationError("모의훈련 경고가 없는 메시지입니다.")

        if message.action_url and not message.action_url.startswith("https://"):
            raise ManualDispatchValidationError("대시보드 링크는 HTTPS만 허용합니다.")
    return ManualTelegramDispatch(
        id=value.id,
        created_at=value.created_at,
        category=value.category,
        operator_label="중앙관제 관리자",
        note=note,
        mode=value.mode,
        facility_ids=facility_ids,
        warning_keys=warning_keys,
        messages=value.messages,
        policy_version=value.policy_version[:80],
        temporary_policy=value.temporary_policy,
    )


def _optional_datetime(value: object) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: object) -> dt.datetime:
    if value:
        try:
            parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
        except ValueError:
            pass
    return dt.datetime.now(dt.timezone.utc)
