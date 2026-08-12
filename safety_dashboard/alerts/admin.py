"""SOLAPI 결과 웹훅과 전화번호 없는 관리자 실적 조회."""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import hmac
import io
from collections.abc import Mapping, Sequence

from safety_dashboard.adapters.firestore_alerts import FirestoreAlertStore, KST
from safety_dashboard.alerts.settings import AlertSettings


class AlertAdminConfigurationError(RuntimeError):
    pass


class AlertAdminAuthorizationError(PermissionError):
    pass


class AlertAdminService:
    def __init__(
        self,
        store: FirestoreAlertStore,
        settings: AlertSettings,
    ) -> None:
        self.store = store
        self.settings = settings

    def authorize_admin(self, token: str) -> None:
        expected = self.settings.admin_token
        if not expected:
            raise AlertAdminConfigurationError("관리자 통계 토큰이 없습니다.")
        if not hmac.compare_digest(token, expected):
            raise AlertAdminAuthorizationError("관리자 인증에 실패했습니다.")

    def status(self) -> dict[str, object]:
        values = dict(self.store.notification_status())
        values.setdefault("mode", self.settings.automation_mode)
        values["daily_cap"] = self.settings.daily_cap
        values["cap_warning"] = self.settings.cap_warning
        return values

    def metrics(self, start: dt.date, end: dt.date) -> dict[str, object]:
        _validate_period(start, end)
        return self.store.notification_metrics(start, end)

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
            "timestamp",
            "event",
            "facility_id",
            "facility_name",
            "warning",
            "recipient_code",
            "delivery_status",
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


def _validate_period(start: dt.date, end: dt.date) -> None:
    if end < start:
        raise ValueError("종료일은 시작일보다 빠를 수 없습니다.")
    if (end - start).days > 366:
        raise ValueError("한 번에 최대 1년까지 조회할 수 있습니다.")


def _parse_datetime(value: object) -> dt.datetime:
    if value:
        try:
            parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
        except ValueError:
            pass
    return dt.datetime.now(dt.timezone.utc)
