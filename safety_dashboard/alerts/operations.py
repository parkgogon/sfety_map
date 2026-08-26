"""자동 알림 작업자의 비용 상태와 정기 운영보고를 관리합니다."""

from __future__ import annotations

import datetime as dt
import html

from safety_dashboard.alerts.domain import (
    HealthCheck,
    OperationalHealthReport,
    TelegramAudience,
    TelegramOutboxItem,
    TelegramPurpose,
)
from safety_dashboard.alerts.ports import (
    AlertStateStore,
    SolapiBalanceProvider,
    SystemHealthProbe,
)
from safety_dashboard.alerts.settings import AlertSettings
from safety_dashboard.alerts.telegram_outbox import TelegramOutboxService
from safety_dashboard.domain.models import OutgoingTelegramMessage


KST = dt.timezone(dt.timedelta(hours=9))


class AlertOperationsService:
    def __init__(
        self,
        store: AlertStateStore,
        settings: AlertSettings,
        telegram_outbox: TelegramOutboxService,
        balance_provider: SolapiBalanceProvider | None = None,
        health_probe: SystemHealthProbe | None = None,
    ) -> None:
        self.store = store
        self.settings = settings
        self.telegram_outbox = telegram_outbox
        self.balance_provider = balance_provider
        self.health_probe = health_probe

    def check_solapi_balance(self, now: dt.datetime) -> None:
        if self.settings.user_delivery_mode != "sms":
            return
        if self.balance_provider is None:
            return
        status = dict(self.store.notification_status())
        previous_at = _parse_datetime(status.get("solapi_balance_checked_at"))
        if previous_at and _aware(previous_at) + dt.timedelta(hours=1) > now:
            return
        try:
            balance = self.balance_provider.fetch_balance()
        except Exception as exc:
            self.store.update_status({
                "solapi_balance_checked_at": now,
                "solapi_balance_health": "ERROR",
                "solapi_balance_detail": type(exc).__name__,
            })
            self.telegram_outbox.notify_admin(
                "solapi-balance-error",
                now,
                "⚠️ SOLAPI 잔액 조회 실패. 문자 시도는 계속합니다.",
            )
            return
        level = _balance_level(
            balance.available,
            warning=self.settings.balance_warning,
            critical=self.settings.balance_critical,
        )
        previous_level = str(status.get("solapi_balance_level", ""))
        self.store.update_status({
            "solapi_balance_checked_at": now,
            "solapi_balance_health": "LIVE",
            "solapi_balance": balance.balance,
            "solapi_point": balance.point,
            "solapi_available": balance.available,
            "solapi_balance_level": level,
        })
        if level != previous_level:
            if level == "CRITICAL":
                self.telegram_outbox.notify_admin(
                    "solapi-balance-critical",
                    now,
                    f"🚨 SOLAPI 사용 가능 금액이 {balance.available:,}원입니다. "
                    "3천원 미만이므로 충전해 주세요.",
                )
            elif level == "WARNING":
                self.telegram_outbox.notify_admin(
                    "solapi-balance-warning",
                    now,
                    f"⚠️ SOLAPI 사용 가능 금액이 {balance.available:,}원입니다. "
                    "1만원 미만이므로 충전을 준비해 주세요.",
                )
            elif previous_level in {"WARNING", "CRITICAL"}:
                self.telegram_outbox.notify_admin(
                    "solapi-balance-recovered",
                    now,
                    f"✅ SOLAPI 사용 가능 금액이 {balance.available:,}원으로 "
                    "회복됐습니다.",
                )

    def enqueue_scheduled_report(self, now: dt.datetime) -> None:
        local = now.astimezone(KST)
        if local.hour not in {9, 18}:
            return
        slot = "09" if local.hour == 9 else "18"
        key = f"operational-health-{local.date().isoformat()}-{slot}"
        if not self.store.admin_notice_due(key, now, dt.timedelta(days=2)):
            return
        message = self.report_message(now, include_metrics=slot == "09")
        self.store.enqueue_telegram(TelegramOutboxItem(
            id=f"admin-health-{local.date().isoformat()}-{slot}",
            audience=TelegramAudience.ADMIN,
            purpose=TelegramPurpose.HEARTBEAT,
            created_at=now,
            expires_at=now + dt.timedelta(
                seconds=self.settings.telegram_retry_seconds
            ),
            next_attempt_at=now,
            messages=(message,),
        ))

    def report_message(
        self,
        now: dt.datetime,
        *,
        include_metrics: bool,
        test: bool = False,
    ) -> OutgoingTelegramMessage:
        local = now.astimezone(KST)
        status = dict(self.store.notification_status())
        if self.health_probe is None:
            probe = OperationalHealthReport(now, ())
        else:
            try:
                probe = self.health_probe.check(now)
            except Exception as exc:
                probe = OperationalHealthReport(
                    now,
                    (HealthCheck("운영 경로 점검", False, type(exc).__name__),),
                )

        kma_ok = status.get("kma_health") == "LIVE"
        mode_ok = self.settings.automation_mode == "live"
        healthy = probe.healthy and kma_ok and mode_ok
        title = (
            "자동 알림 일일 요약 + 운영 상태"
            if include_metrics
            else "운영 상태 보고"
        )
        if test:
            title = "[시험] " + title
        icon = "✅" if healthy else "⚠️"
        lines = [
            f"{icon} <b>{html.escape(title)}</b>",
            f"기준 · {local:%Y-%m-%d %H:%M}",
        ]
        if include_metrics:
            report_day = local.date() - dt.timedelta(days=1)
            metrics = self.store.notification_metrics(report_day, report_day)
            totals = metrics.get("totals", {})
            if not isinstance(totals, dict):
                totals = {}
            lines.extend((
                f"\n<b>{report_day:%Y-%m-%d} 전날 실적</b>",
                f"자동 관제 · {int(totals.get('poll_runs', 0))}회",
                f"특보 변화 · 발효 {int(totals.get('warning_activated', 0))} · "
                f"격상 {int(totals.get('warning_escalated', 0))} · "
                f"해제 {int(totals.get('warning_cleared', 0))}",
                f"문자 · 시도 {int(totals.get('sms_attempted', 0))} · "
                f"수신완료 {int(totals.get('sms_delivered', 0))} · "
                f"실패 {int(totals.get('sms_delivery_failed', 0)) + int(totals.get('sms_failed', 0))}",
                "사용자 Telegram · "
                f"주경로 {int(totals.get('telegram_user_primary_sent', 0))} · "
                f"대체 {int(totals.get('telegram_user_fallback_sent', 0))} · "
                f"실패 {int(totals.get('telegram_user_failed', 0))}",
            ))
        lines.append("\n<b>현재 시스템</b>")
        for check in probe.checks:
            latency = (
                f" · {check.latency_ms}ms"
                if check.latency_ms is not None
                else ""
            )
            lines.append(
                f"{_health_icon(check.healthy)} {html.escape(check.name)} · "
                f"{html.escape(check.detail)}{latency}"
            )
        lines.extend((
            f"{_health_icon(mode_ok)} 자동 관제 · "
            f"{html.escape(self.settings.automation_mode)} · "
            f"최근 {html.escape(_format_status_time(status.get('last_run_at')))}",
            f"{_health_icon(kma_ok)} KMA · "
            f"{html.escape(str(status.get('kma_health', '미확인')))} · "
            "최근 정상 "
            f"{html.escape(_format_status_time(status.get('kma_last_success_at')))} · "
            f"연속 실패 {int(status.get('kma_consecutive_errors', 0))}회",
            f"특보·시설 · 활성 {int(status.get('active_warning_count', 0))}건 · "
            f"영향 {int(status.get('affected_facility_count', 0))}곳",
            "사용자 Telegram 최근 발송 · "
            f"{html.escape(str(status.get('last_user_telegram_result', '기록 없음')))} · "
            f"{html.escape(_format_status_time(status.get('last_user_telegram_at')))}",
            f"배포 · {html.escape(self.settings.app_revision)}",
        ))
        return OutgoingTelegramMessage(
            text="\n".join(lines),
            silent=healthy,
        )


def _aware(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo else value.replace(tzinfo=KST)


def _parse_datetime(value: object) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return _aware(parsed)


def _balance_level(available: int, *, warning: int, critical: int) -> str:
    if available < critical:
        return "CRITICAL"
    if available < warning:
        return "WARNING"
    return "NORMAL"


def _health_icon(healthy: bool) -> str:
    return "✅" if healthy else "❌"


def _format_status_time(value: object) -> str:
    parsed = _parse_datetime(value)
    return parsed.astimezone(KST).strftime("%m-%d %H:%M") if parsed else "기록 없음"
