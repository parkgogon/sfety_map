import datetime as dt
import dataclasses
import hashlib
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from safety_dashboard.adapters.google_sheet_contacts import GoogleSheetContactProvider
from safety_dashboard.adapters.solapi import SolapiNotifier
from safety_dashboard.adapters.telegram import TelegramResult
from safety_dashboard.adapters.firestore_alerts import _provider_status
from safety_dashboard.alerts.admin import (
    AlertAdminAuthorizationError,
    AlertAdminService,
)
from safety_dashboard.alerts.contacts import ContactDataError, build_contact_directory
from safety_dashboard.alerts.domain import (
    AlertBatch,
    ContactDirectory,
    FacilityRecipient,
    HealthCheck,
    OperationalHealthReport,
    SmsDeliveryResult,
    SmsDeliveryStatus,
    SolapiBalance,
    TelegramAudience,
)
from safety_dashboard.alerts.messages import build_alert_batch_telegram_payloads
from safety_dashboard.alerts.memory_store import InMemoryAlertStore
from safety_dashboard.alerts.service import AlertDispatcher, DispatchSummary
from safety_dashboard.alerts.settings import AlertSettings
from safety_dashboard.alerts.worker_app import create_worker_app
from safety_dashboard.alerts.transitions import (
    detect_transitions,
    filter_impacts_by_warning_type,
    impacts_from_snapshot,
)
from safety_dashboard.api.app import create_app
from safety_dashboard.application.monitoring import MonitoringService
from safety_dashboard.domain import (
    DataHealth,
    Facility,
    GeoPoint,
    KmaFailureCategory,
    KmaFailureDiagnostic,
    Warning,
    WarningFeed,
    WarningLevel,
    RiskGrade,
)
from safety_dashboard.domain.risk_policy import RiskPolicy


KST = dt.timezone(dt.timedelta(hours=9))


class _FacilityRepository:
    def __init__(self, facilities):
        self.facilities = facilities

    def list_monitored(self):
        return self.facilities


class _WarningProvider:
    def __init__(self, feed):
        self.feed = feed

    def fetch_active(self):
        return self.feed


class _Matcher:
    def matches(self, facility, warning):
        return True


class _SnapshotProvider:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def fetch(self):
        return self.snapshot


class _ContactProvider:
    def __init__(self, recipients):
        self.recipients = recipients
        self.error = False
        self.calls = 0

    def fetch(self, valid_facility_ids):
        self.calls += 1
        if self.error:
            raise ContactDataError("테스트 연락처 장애")
        return ContactDirectory(
            tuple(self.recipients),
            "revision",
            dt.datetime.now(dt.timezone.utc),
        )


class _Sms:
    def __init__(self, status=SmsDeliveryStatus.ACCEPTED, detail=""):
        self.messages = []
        self.status = status
        self.detail = detail

    def send(self, message):
        self.messages.append(message)
        return SmsDeliveryResult(
            self.status,
            provider_message_id=(
                f"provider-{len(self.messages)}"
                if self.status is SmsDeliveryStatus.ACCEPTED
                else ""
            ),
            detail=self.detail,
        )


class _Telegram:
    def __init__(self, success=True):
        self.batches = []
        self.success = success

    def send_batch(self, messages):
        self.batches.append(tuple(messages))
        return TelegramResult(
            self.success,
            len(messages) if self.success else 0,
            len(messages),
            "Telegram 성공" if self.success else "Telegram 실패",
        )


class _Balance:
    def __init__(self, available):
        self.available = available
        self.calls = 0

    def fetch_balance(self):
        self.calls += 1
        return SolapiBalance(self.available, 0, dt.datetime.now(dt.timezone.utc))


class _HealthProbe:
    def __init__(self, healthy=True):
        self.healthy = healthy
        self.calls = 0

    def check(self, now):
        self.calls += 1
        return OperationalHealthReport(now, (
            HealthCheck("사용자 웹", self.healthy, "HTTP 200", 120),
            HealthCheck("공개 API", self.healthy, "HTTP 200", 80),
            HealthCheck("사용자 Telegram", self.healthy, "채널 접근 가능"),
        ))


class _KmaDiagnoser:
    def __init__(self, category=KmaFailureCategory.KMA_ROUTE):
        self.category = category

    def diagnose(self, initial):
        return KmaFailureDiagnostic(
            self.category,
            f"{self.category.label} 테스트 판단",
            "제어 점검 근거",
            cause_type=initial.cause_type,
        )


class AutomaticAlertTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = RiskPolicy.load("safety_dashboard/config/risk_policy.toml")
        cls.facilities = (
            Facility(
                "F-1", "구미 측정소", "대기측정소",
                GeoPoint(36.1, 128.3), "경북 구미시", "부서", "담당자",
            ),
            Facility(
                "F-2", "김천 측정소", "대기측정소",
                GeoPoint(36.2, 128.1), "경북 김천시", "부서", "담당자",
            ),
        )
        cls.now = dt.datetime(2026, 8, 12, 10, 0, tzinfo=KST)

    def snapshot(
        self,
        raw_level=None,
        health=DataHealth.LIVE,
        minute=0,
        warning_type="강풍",
    ):
        warnings = ()
        if raw_level:
            level = {
                "주의보": WarningLevel.ADVISORY,
                "경보": WarningLevel.WARNING,
            }[raw_level]
            warnings = (
                Warning(
                    f"W-{raw_level}-{minute}", "기상청", "L1070000", "L1070300",
                    "경상북도", "구미시", warning_type, raw_level, level,
                    command="발표", issued_at=self.now.replace(minute=minute),
                    effective_at=self.now.replace(minute=minute),
                ),
            )
        feed = WarningFeed(
            warnings if health is DataHealth.LIVE else (),
            health,
            self.now,
            "KMA 장애" if health is DataHealth.ERROR else "",
        )
        return MonitoringService(
            _FacilityRepository(self.facilities),
            _WarningProvider(feed),
            _Matcher(),
            self.policy,
        ).get_snapshot(self.now)

    def settings(self, **values):
        defaults = dict(
            automation_mode="live",
            user_delivery_mode="sms",
            recipient_hmac_secret="test-hmac-secret",
            dashboard_base_url="https://keco-safety-map.web.app",
            daily_cap=50,
            cap_warning=40,
            pending_seconds=1800,
        )
        defaults.update(values)
        return AlertSettings(**defaults)

    def dispatcher(
        self,
        snapshot,
        contacts=None,
        store=None,
        sms=None,
        settings=None,
        admin_telegram=None,
        user_telegram=None,
        balance_provider=None,
        health_probe=None,
        kma_diagnoser=None,
    ):
        contact_provider = contacts or _ContactProvider((
            FacilityRecipient("F-1", "담당", "01011112222"),
            FacilityRecipient("F-2", "담당", "01011112222"),
        ))
        return (
            AlertDispatcher(
                _SnapshotProvider(snapshot),
                contact_provider,
                sms or _Sms(),
                store or InMemoryAlertStore(),
                self.policy,
                settings or self.settings(),
                admin_telegram or _Telegram(),
                user_telegram=user_telegram,
                balance_provider=balance_provider,
                health_probe=health_probe,
                kma_diagnoser=kma_diagnoser,
            ),
            contact_provider,
        )

    def test_transition_identity_ignores_same_level_reissue_and_detects_escalation(self):
        advisory = impacts_from_snapshot(self.snapshot("주의보", minute=0), self.policy)
        reissued = impacts_from_snapshot(self.snapshot("주의보", minute=5), self.policy)
        warning = impacts_from_snapshot(self.snapshot("경보", minute=10), self.policy)
        self.assertEqual(detect_transitions(advisory, reissued, self.now), ())
        transitions = detect_transitions(reissued, warning, self.now)
        self.assertEqual({item.kind.value for item in transitions}, {"ESCALATED"})
        self.assertEqual(len(transitions), 2)
        self.assertEqual(detect_transitions(warning, advisory, self.now), ())
        self.assertEqual(
            {item.kind.value for item in detect_transitions(warning, (), self.now)},
            {"CLEARED"},
        )

    def test_warning_type_filter_excludes_tropical_night_without_changing_snapshot(self):
        snapshot = self.snapshot("주의보", warning_type="열대야")
        impacts = impacts_from_snapshot(snapshot, self.policy)

        self.assertEqual(len(impacts), 2)
        self.assertTrue(all(item.warning_type == "열대야" for item in impacts))
        self.assertEqual(
            filter_impacts_by_warning_type(
                impacts,
                excluded_warning_types=("열대야",),
            ),
            (),
        )
        self.assertEqual(
            len(filter_impacts_by_warning_type(
                impacts,
                included_warning_types=("열대야", "호우"),
            )),
            2,
        )

    def test_warning_filter_change_rebaselines_without_false_clear(self):
        store = InMemoryAlertStore()
        user = _Telegram()
        unfiltered, _ = self.dispatcher(
            self.snapshot(),
            store=store,
            settings=self.settings(
                user_delivery_mode="telegram",
                excluded_warning_types=(),
            ),
            user_telegram=user,
        )
        self.assertEqual(unfiltered.run(self.now).status, "BASELINED")
        unfiltered.snapshot_provider.snapshot = self.snapshot(
            "주의보", warning_type="열대야"
        )
        self.assertEqual(
            unfiltered.run(self.now + dt.timedelta(minutes=5)).status,
            "DISPATCHED",
        )
        sent_before_filter_change = len(user.batches)

        filtered, _ = self.dispatcher(
            self.snapshot("주의보", warning_type="열대야"),
            store=store,
            settings=self.settings(
                user_delivery_mode="telegram",
                excluded_warning_types=("열대야",),
            ),
            user_telegram=user,
        )
        self.assertEqual(
            filtered.run(self.now + dt.timedelta(minutes=10)).status,
            "BASELINED",
        )
        self.assertEqual(len(user.batches), sent_before_filter_change)

    def test_warning_type_environment_lists_support_pipe_separator(self):
        with patch.dict(os.environ, {
            "ALERT_INCLUDED_WARNING_TYPES": "호우|태풍|호우",
            "ALERT_EXCLUDED_WARNING_TYPES": "열대야|안개",
        }):
            settings = AlertSettings.from_environment()

        self.assertEqual(settings.included_warning_types, ("호우", "태풍"))
        self.assertEqual(settings.excluded_warning_types, ("열대야", "안개"))

    def test_same_recipient_gets_one_message_and_repeated_poll_does_not_duplicate(self):
        store = InMemoryAlertStore()
        sms = _Sms()
        dispatcher, _ = self.dispatcher(self.snapshot(), store=store, sms=sms)
        self.assertEqual(dispatcher.run(self.now).status, "BASELINED")
        dispatcher.snapshot_provider.snapshot = self.snapshot("주의보")
        first = dispatcher.run(self.now + dt.timedelta(minutes=5))
        self.assertEqual(first.transition_count, 2)
        self.assertEqual(first.message_count, 1)
        self.assertEqual(len(sms.messages), 1)
        self.assertEqual(set(sms.messages[0].facility_ids), {"F-1", "F-2"})
        self.assertNotIn("01011112222", sms.messages[0].text)
        counters = store.metrics[self.now.date().isoformat()]
        self.assertEqual(counters["warning_activated"], 1)
        self.assertEqual(counters["transition_activated"], 2)
        self.assertEqual(counters["affected_facility_events"], 2)
        repeated = dispatcher.run(self.now + dt.timedelta(minutes=10))
        self.assertEqual(repeated.status, "NO_CHANGE")
        self.assertEqual(len(sms.messages), 1)

    def test_escalation_downgrade_reescalation_and_clear(self):
        store = InMemoryAlertStore()
        sms = _Sms()
        dispatcher, _ = self.dispatcher(self.snapshot(), store=store, sms=sms)
        dispatcher.run(self.now)
        dispatcher.snapshot_provider.snapshot = self.snapshot("주의보", minute=5)
        dispatcher.run(self.now + dt.timedelta(minutes=5))
        dispatcher.snapshot_provider.snapshot = self.snapshot("경보", minute=10)
        dispatcher.run(self.now + dt.timedelta(minutes=10))
        dispatcher.snapshot_provider.snapshot = self.snapshot("주의보", minute=15)
        self.assertEqual(
            dispatcher.run(self.now + dt.timedelta(minutes=15)).status,
            "NO_CHANGE",
        )
        dispatcher.snapshot_provider.snapshot = self.snapshot("경보", minute=20)
        dispatcher.run(self.now + dt.timedelta(minutes=20))
        dispatcher.snapshot_provider.snapshot = self.snapshot()
        dispatcher.run(self.now + dt.timedelta(minutes=25))
        self.assertEqual(len(sms.messages), 4)
        self.assertIn("[해제]", sms.messages[-1].text)

    def test_kma_error_preserves_state_and_never_sends_false_clear(self):
        store = InMemoryAlertStore()
        sms = _Sms()
        dispatcher, _ = self.dispatcher(self.snapshot("주의보"), store=store, sms=sms)
        dispatcher.run(self.now)
        before = store.impacts
        dispatcher.snapshot_provider.snapshot = self.snapshot(health=DataHealth.ERROR)
        result = dispatcher.run(self.now + dt.timedelta(minutes=5))
        self.assertEqual(result.status, "KMA_ERROR")
        self.assertEqual(store.impacts, before)
        self.assertEqual(sms.messages, [])

    def test_kma_outage_notice_is_rate_limited_and_recovery_is_reported(self):
        store = InMemoryAlertStore()
        telegram = _Telegram()
        dispatcher = AlertDispatcher(
            _SnapshotProvider(self.snapshot("주의보")),
            _ContactProvider((
                FacilityRecipient("F-1", "담당", "01011112222"),
                FacilityRecipient("F-2", "담당", "01011112222"),
            )),
            _Sms(),
            store,
            self.policy,
            self.settings(),
            telegram,
        )
        dispatcher.run(self.now)
        dispatcher.snapshot_provider.snapshot = self.snapshot(health=DataHealth.ERROR)
        dispatcher.run(self.now + dt.timedelta(minutes=5))
        dispatcher.run(self.now + dt.timedelta(minutes=10))
        self.assertEqual(len(telegram.batches), 1)
        dispatcher.snapshot_provider.snapshot = self.snapshot("주의보")
        dispatcher.run(self.now + dt.timedelta(minutes=15))
        self.assertEqual(len(telegram.batches), 2)

    def test_kma_diagnostic_category_change_is_immediate_and_recovery_has_duration(self):
        store = InMemoryAlertStore()
        admin = _Telegram()
        diagnoser = _KmaDiagnoser()
        dispatcher, _ = self.dispatcher(
            self.snapshot("주의보"),
            store=store,
            admin_telegram=admin,
            kma_diagnoser=diagnoser,
        )
        dispatcher.run(self.now)
        dispatcher.snapshot_provider.snapshot = self.snapshot(health=DataHealth.ERROR)
        dispatcher.run(self.now + dt.timedelta(minutes=5))
        dispatcher.run(self.now + dt.timedelta(minutes=10))
        self.assertEqual(len(admin.batches), 1)
        self.assertIn("KMA API 통신경로", admin.batches[0][0].text)
        diagnoser.category = KmaFailureCategory.CLOUD_EGRESS
        dispatcher.run(self.now + dt.timedelta(minutes=15))
        self.assertEqual(len(admin.batches), 2)
        self.assertIn("Cloud Run 외부통신", admin.batches[1][0].text)
        dispatcher.snapshot_provider.snapshot = self.snapshot("주의보")
        dispatcher.run(self.now + dt.timedelta(minutes=20))
        self.assertEqual(len(admin.batches), 3)
        self.assertIn("장애 지속 · 15분", admin.batches[2][0].text)

    def test_contact_failure_falls_back_once_and_does_not_send_delayed_sms(self):
        store = InMemoryAlertStore()
        sms = _Sms()
        user = _Telegram()
        dispatcher, contacts = self.dispatcher(
            self.snapshot(), store=store, sms=sms, user_telegram=user
        )
        dispatcher.run(self.now)
        contacts.error = True
        dispatcher.snapshot_provider.snapshot = self.snapshot("주의보")
        result = dispatcher.run(self.now + dt.timedelta(minutes=5))
        self.assertEqual(result.status, "CONTACTS_ERROR")
        self.assertEqual(store.load_pending(self.now + dt.timedelta(minutes=6)), ())
        self.assertEqual(len(user.batches), 1)
        self.assertIn("문자 대체 전파", user.batches[0][0].text)
        contacts.error = False
        recovered = dispatcher.run(self.now + dt.timedelta(minutes=10))
        self.assertEqual(recovered.status, "NO_CHANGE")
        self.assertEqual(sms.messages, [])
        self.assertEqual(len(user.batches), 1)

    def test_telegram_mode_skips_contacts_and_solapi_and_uses_user_channel(self):
        contacts = _ContactProvider(())
        sms = _Sms()
        admin = _Telegram()
        user = _Telegram()
        store = InMemoryAlertStore()
        dispatcher, _ = self.dispatcher(
            self.snapshot(),
            contacts=contacts,
            store=store,
            sms=sms,
            settings=self.settings(user_delivery_mode="telegram"),
            admin_telegram=admin,
            user_telegram=user,
        )
        dispatcher.run(self.now)
        dispatcher.snapshot_provider.snapshot = self.snapshot("주의보")
        result = dispatcher.run(self.now + dt.timedelta(minutes=5))
        self.assertEqual(result.status, "DISPATCHED")
        self.assertEqual(contacts.calls, 0)
        self.assertEqual(sms.messages, [])
        self.assertEqual(len(user.batches), 1)
        self.assertTrue(any(
            "구미 측정소" in message.text for message in user.batches[0]
        ))
        self.assertTrue(all("010" not in message.text for message in user.batches[0]))
        self.assertGreaterEqual(len(admin.batches), 1)

    def test_sms_success_does_not_duplicate_to_user_channel(self):
        user = _Telegram()
        store = InMemoryAlertStore()
        dispatcher, _ = self.dispatcher(
            self.snapshot(), store=store, user_telegram=user
        )
        dispatcher.run(self.now)
        dispatcher.snapshot_provider.snapshot = self.snapshot("주의보")
        result = dispatcher.run(self.now + dt.timedelta(minutes=5))
        self.assertEqual(result.accepted_count, 1)
        self.assertEqual(user.batches, [])

    def test_solapi_rejection_falls_back_to_user_channel_once(self):
        sms = _Sms(SmsDeliveryStatus.FAILED, "잔액 부족")
        user = _Telegram()
        store = InMemoryAlertStore()
        dispatcher, _ = self.dispatcher(
            self.snapshot(), store=store, sms=sms, user_telegram=user
        )
        dispatcher.run(self.now)
        dispatcher.snapshot_provider.snapshot = self.snapshot("주의보")
        dispatcher.run(self.now + dt.timedelta(minutes=5))
        dispatcher.run(self.now + dt.timedelta(minutes=10))
        self.assertEqual(len(sms.messages), 1)
        self.assertEqual(len(user.batches), 1)
        self.assertIn("잔액 부족", user.batches[0][0].text)

    def test_unmapped_facility_uses_one_fallback_post_without_phone_data(self):
        contacts = _ContactProvider((
            FacilityRecipient("F-1", "담당", "01011112222"),
        ))
        user = _Telegram()
        store = InMemoryAlertStore()
        dispatcher, _ = self.dispatcher(
            self.snapshot(), contacts=contacts, store=store, user_telegram=user
        )
        dispatcher.run(self.now)
        dispatcher.snapshot_provider.snapshot = self.snapshot("주의보")
        dispatcher.run(self.now + dt.timedelta(minutes=5))
        self.assertEqual(len(user.batches), 1)
        combined = "\n".join(item.text for item in user.batches[0])
        self.assertIn("연락처 미등록 시설 1곳", combined)
        self.assertNotIn("01011112222", combined)

    def test_user_payload_alert_sound_and_facility_rows(self):
        transitions = detect_transitions(
            (),
            impacts_from_snapshot(self.snapshot("주의보"), self.policy),
            self.now,
        )
        low_batch = AlertBatch(
            "low", self.now, transitions, "live", self.policy.version
        )
        low_payloads = build_alert_batch_telegram_payloads(
            low_batch, "https://keco-safety-map.web.app"
        )
        self.assertTrue(low_payloads[0].silent)
        details = "\n".join(item.text for item in low_payloads[1:])
        for facility in self.facilities:
            self.assertEqual(details.count(facility.name), 1)

        high_transitions = tuple(
            dataclasses.replace(
                item,
                current=dataclasses.replace(
                    item.current,
                    risk_grade=RiskGrade.HIGH,
                ),
            )
            for item in transitions
        )
        high_batch = AlertBatch(
            "high", self.now, high_transitions, "live", self.policy.version
        )
        high_payloads = build_alert_batch_telegram_payloads(
            high_batch, "https://keco-safety-map.web.app"
        )
        self.assertFalse(high_payloads[0].silent)
        self.assertTrue(all(item.silent for item in high_payloads[1:]))

    def test_user_clear_payload_separates_current_and_previous_state(self):
        previous = impacts_from_snapshot(self.snapshot("경보"), self.policy)
        transitions = detect_transitions(previous, (), self.now)
        batch = AlertBatch(
            "cleared", self.now, transitions, "live", self.policy.version
        )

        payloads = build_alert_batch_telegram_payloads(
            batch, "https://keco-safety-map.web.app"
        )
        summary = payloads[0].text
        details = "\n".join(item.text for item in payloads[1:])

        self.assertIn("[K-ECO 재난안전][해제]", summary)
        self.assertIn("등급 현황 · 영향 종료", summary)
        self.assertIn("🔵", details)
        self.assertIn("[특보 영향 종료]", details)
        self.assertIn("해제된 특보:", details)
        self.assertIn("해제 전 등급: 중", details)
        self.assertIn("시설 이상 유무를 확인", details)
        self.assertNotIn("🔴", details)
        self.assertNotIn("[상]", details)

    def test_delayed_escalation_is_discarded_after_warning_downgrade(self):
        store = InMemoryAlertStore()
        sms = _Sms()
        dispatcher, contacts = self.dispatcher(
            self.snapshot("주의보"),
            store=store,
            sms=sms,
        )
        dispatcher.run(self.now)
        contacts.error = True
        dispatcher.snapshot_provider.snapshot = self.snapshot("경보", minute=5)
        self.assertEqual(
            dispatcher.run(self.now + dt.timedelta(minutes=5)).status,
            "CONTACTS_ERROR",
        )
        contacts.error = False
        dispatcher.snapshot_provider.snapshot = self.snapshot("주의보", minute=10)
        recovered = dispatcher.run(self.now + dt.timedelta(minutes=10))
        self.assertEqual(recovered.status, "NO_CHANGE")
        self.assertEqual(sms.messages, [])

    def test_preview_is_excluded_and_live_switch_baselines(self):
        store = InMemoryAlertStore()
        sms = _Sms()
        dispatcher, _ = self.dispatcher(
            self.snapshot(), store=store, sms=sms,
            settings=self.settings(automation_mode="preview"),
        )
        dispatcher.run(self.now)
        dispatcher.snapshot_provider.snapshot = self.snapshot("주의보")
        preview = dispatcher.run(self.now + dt.timedelta(minutes=5))
        self.assertEqual(preview.status, "PREVIEW")
        self.assertEqual(sms.messages, [])
        self.assertEqual(store.status["preview_estimated_cost_krw"], 45)
        self.assertNotIn("01011112222", store.status["preview_samples"][0]["text"])
        self.assertEqual(
            store.metrics[self.now.date().isoformat()].get("transition_activated", 0),
            0,
        )
        self.assertNotIn("poll_runs", store.metrics[self.now.date().isoformat()])
        live, _ = self.dispatcher(
            self.snapshot("주의보"), store=store, sms=sms,
            settings=self.settings(automation_mode="live"),
        )
        self.assertEqual(live.run(self.now + dt.timedelta(minutes=10)).status, "BASELINED")
        self.assertEqual(sms.messages, [])

    def test_daily_cap_blocks_excess_recipient(self):
        contacts = _ContactProvider((
            FacilityRecipient("F-1", "담당1", "01011112222"),
            FacilityRecipient("F-2", "담당2", "01033334444"),
        ))
        store = InMemoryAlertStore()
        sms = _Sms()
        dispatcher, _ = self.dispatcher(
            self.snapshot(), contacts=contacts, store=store, sms=sms,
            settings=self.settings(daily_cap=1, cap_warning=1),
        )
        dispatcher.run(self.now)
        dispatcher.snapshot_provider.snapshot = self.snapshot("주의보")
        result = dispatcher.run(self.now + dt.timedelta(minutes=5))
        self.assertEqual(result.message_count, 2)
        self.assertEqual(result.accepted_count, 1)
        self.assertEqual(result.blocked_count, 1)
        self.assertEqual(len(sms.messages), 1)

    def test_monthly_cap_blocks_sms_and_uses_one_fallback_post(self):
        contacts = _ContactProvider((
            FacilityRecipient("F-1", "담당1", "01011112222"),
            FacilityRecipient("F-2", "담당2", "01033334444"),
        ))
        store = InMemoryAlertStore()
        store.metrics["2026-08-01"] = {"sms_attempted": 1}
        sms = _Sms()
        user = _Telegram()
        dispatcher, _ = self.dispatcher(
            self.snapshot(),
            contacts=contacts,
            store=store,
            sms=sms,
            user_telegram=user,
            settings=self.settings(monthly_cap=1, monthly_cap_warning=1),
        )
        dispatcher.run(self.now)
        dispatcher.snapshot_provider.snapshot = self.snapshot("주의보")
        result = dispatcher.run(self.now + dt.timedelta(minutes=5))
        self.assertEqual(result.blocked_count, 2)
        self.assertEqual(sms.messages, [])
        self.assertEqual(len(user.batches), 1)

    def test_daily_and_monthly_warning_thresholds_notify_admin_once(self):
        contacts = _ContactProvider((
            FacilityRecipient("F-1", "담당1", "01011112222"),
            FacilityRecipient("F-2", "담당2", "01033334444"),
        ))
        store = InMemoryAlertStore()
        store.metrics["2026-08-01"] = {"sms_attempted": 399}
        admin = _Telegram()
        dispatcher, _ = self.dispatcher(
            self.snapshot(),
            contacts=contacts,
            store=store,
            admin_telegram=admin,
            settings=self.settings(
                daily_cap=100,
                cap_warning=2,
                monthly_cap=500,
                monthly_cap_warning=400,
            ),
        )
        dispatcher.run(self.now)
        dispatcher.snapshot_provider.snapshot = self.snapshot("주의보")
        dispatcher.run(self.now + dt.timedelta(minutes=5))
        combined = "\n".join(
            item.text for batch in admin.batches for item in batch
        )
        self.assertIn("오늘 자동 문자 발송이 2건에 도달", combined)
        self.assertIn("이번 달 자동 문자 발송이 400건에 도달", combined)

    def test_balance_is_checked_hourly_only_in_sms_mode_and_recovery_is_reported(self):
        store = InMemoryAlertStore()
        admin = _Telegram()
        balance = _Balance(2000)
        dispatcher, _ = self.dispatcher(
            self.snapshot(),
            store=store,
            admin_telegram=admin,
            balance_provider=balance,
        )
        dispatcher.run(self.now)
        dispatcher.run(self.now + dt.timedelta(minutes=5))
        self.assertEqual(balance.calls, 1)
        self.assertTrue(any(
            "사용 가능 금액" in item.text for item in admin.batches[0]
        ))
        balance.available = 20000
        dispatcher.run(self.now + dt.timedelta(hours=1))
        self.assertEqual(balance.calls, 2)
        self.assertTrue(any(
            "회복" in item.text
            for batch in admin.batches
            for item in batch
        ))

        telegram_balance = _Balance(100)
        telegram_dispatcher, _ = self.dispatcher(
            self.snapshot(),
            settings=self.settings(user_delivery_mode="telegram"),
            balance_provider=telegram_balance,
        )
        telegram_dispatcher.run(self.now)
        self.assertEqual(telegram_balance.calls, 0)

    def test_user_telegram_retries_for_thirty_minutes_without_sms_reverse_fallback(self):
        store = InMemoryAlertStore()
        sms = _Sms()
        user = _Telegram(success=False)
        admin = _Telegram()
        dispatcher, _ = self.dispatcher(
            self.snapshot(),
            store=store,
            sms=sms,
            settings=self.settings(user_delivery_mode="telegram"),
            admin_telegram=admin,
            user_telegram=user,
        )
        dispatcher.run(self.now)
        dispatcher.snapshot_provider.snapshot = self.snapshot("주의보")
        for minute in (5, 10, 15, 20, 25, 30, 35):
            dispatcher.run(self.now + dt.timedelta(minutes=minute))
        self.assertEqual(len(user.batches), 7)
        self.assertEqual(sms.messages, [])
        self.assertEqual(
            store.metrics[self.now.date().isoformat()]["telegram_user_failed"],
            1,
        )
        self.assertTrue(any(
            "30분 재시도 후 실패" in message.text
            for batch in admin.batches
            for message in batch
        ))

    def test_delivery_mode_change_does_not_reannounce_existing_warning(self):
        store = InMemoryAlertStore()
        telegram_dispatcher, _ = self.dispatcher(
            self.snapshot("주의보"),
            store=store,
            settings=self.settings(user_delivery_mode="telegram"),
            user_telegram=_Telegram(),
        )
        self.assertEqual(telegram_dispatcher.run(self.now).status, "BASELINED")
        sms = _Sms()
        sms_dispatcher, contacts = self.dispatcher(
            self.snapshot("주의보"), store=store, sms=sms
        )
        self.assertEqual(
            sms_dispatcher.run(self.now + dt.timedelta(minutes=5)).status,
            "NO_CHANGE",
        )
        self.assertEqual(contacts.calls, 0)
        self.assertEqual(sms.messages, [])

    def test_terminal_sms_failure_webhook_queues_one_user_fallback(self):
        store = InMemoryAlertStore()
        sms = _Sms()
        admin = _Telegram()
        user = _Telegram()
        dispatcher, _ = self.dispatcher(
            self.snapshot(),
            store=store,
            sms=sms,
            admin_telegram=admin,
            user_telegram=user,
        )
        dispatcher.run(self.now)
        dispatcher.snapshot_provider.snapshot = self.snapshot("주의보")
        dispatcher.run(self.now + dt.timedelta(minutes=5))
        self.assertEqual(user.batches, [])
        message = sms.messages[0]
        result = store.deliveries[message.id]["result"]
        self.assertTrue(store.apply_provider_report(
            result.provider_message_id,
            "3113",
            self.now + dt.timedelta(minutes=6),
        ))
        self.assertFalse(store.apply_provider_report(
            result.provider_message_id,
            "3113",
            self.now + dt.timedelta(minutes=7),
        ))
        dispatcher.run(self.now + dt.timedelta(minutes=10))
        dispatcher.run(self.now + dt.timedelta(minutes=15))
        self.assertEqual(len(user.batches), 1)
        self.assertIn("통신사 최종 수신 실패", user.batches[0][0].text)
        self.assertTrue(any(
            "문자 최종 전달 결과" in message.text
            for batch in admin.batches
            for message in batch
        ))

    def test_admin_and_user_telegram_test_targets_are_separate(self):
        admin = _Telegram()
        user = _Telegram()
        dispatcher, _ = self.dispatcher(
            self.snapshot(), admin_telegram=admin, user_telegram=user
        )
        admin_result = dispatcher.send_telegram_test(
            TelegramAudience.ADMIN, self.now
        )
        user_result = dispatcher.send_telegram_test(
            TelegramAudience.USER, self.now
        )
        self.assertEqual(admin_result.status, "TELEGRAM_TEST_SENT")
        self.assertEqual(user_result.status, "TELEGRAM_TEST_SENT")
        self.assertEqual(len(admin.batches), 1)
        self.assertEqual(len(user.batches), 1)
        self.assertIn("관리자방", admin.batches[0][0].text)
        self.assertIn("사용자 채널", user.batches[0][0].text)

    def test_daily_nine_oclock_summary_is_sent_once(self):
        store = InMemoryAlertStore()
        admin = _Telegram()
        start = self.now.replace(hour=8, minute=55)
        dispatcher, _ = self.dispatcher(
            self.snapshot(), store=store, admin_telegram=admin
        )
        dispatcher.run(start)
        dispatcher.run(start + dt.timedelta(minutes=5))
        dispatcher.run(start + dt.timedelta(minutes=10))
        digests = [
            message
            for batch in admin.batches
            for message in batch
            if "자동 알림 일일 요약" in message.text
        ]
        self.assertEqual(len(digests), 1)

    def test_nine_and_eighteen_health_reports_are_once_and_use_silent_by_health(self):
        store = InMemoryAlertStore()
        admin = _Telegram()
        probe = _HealthProbe(healthy=True)
        dispatcher, _ = self.dispatcher(
            self.snapshot(),
            store=store,
            admin_telegram=admin,
            health_probe=probe,
        )
        morning = self.now.replace(hour=9, minute=0)
        dispatcher.run(morning)
        dispatcher.run(morning + dt.timedelta(minutes=5))
        evening = morning.replace(hour=18)
        dispatcher.run(evening)
        dispatcher.run(evening + dt.timedelta(minutes=5))
        reports = [
            message
            for batch in admin.batches
            for message in batch
            if "운영 상태" in message.text
        ]
        self.assertEqual(len(reports), 2)
        self.assertEqual(probe.calls, 2)
        self.assertTrue(all(item.silent for item in reports))
        self.assertIn("전날 실적", reports[0].text)
        self.assertNotIn("전날 실적", reports[1].text)
        self.assertIn("배포", reports[0].text)

    def test_degraded_heartbeat_is_audible_and_test_is_not_a_metric(self):
        store = InMemoryAlertStore()
        admin = _Telegram()
        dispatcher, _ = self.dispatcher(
            self.snapshot(),
            store=store,
            admin_telegram=admin,
            health_probe=_HealthProbe(healthy=False),
        )
        dispatcher.run(self.now)
        result = dispatcher.send_heartbeat_test(self.now)
        self.assertEqual(result.status, "HEARTBEAT_TEST_SENT")
        self.assertFalse(admin.batches[-1][0].silent)
        self.assertIn("[시험]", admin.batches[-1][0].text)
        values = store.metrics.get(self.now.date().isoformat(), {})
        self.assertNotIn("heartbeat_test", values)

    def test_designated_test_number_is_logged_outside_operational_metrics(self):
        store = InMemoryAlertStore()
        sms = _Sms()
        dispatcher, _ = self.dispatcher(
            self.snapshot(),
            store=store,
            sms=sms,
            settings=self.settings(test_phone="010-9999-0000"),
        )
        result = dispatcher.send_test(self.now)
        self.assertEqual(result.status, "TEST_SENT")
        self.assertEqual(len(sms.messages), 1)
        values = store.metrics[self.now.date().isoformat()]
        self.assertEqual(values["test_sms_attempted"], 1)
        self.assertNotIn("sms_attempted", values)
        delivery = next(iter(store.deliveries.values()))
        self.assertEqual(delivery["metric_scope"], "test")
        self.assertEqual(delivery["status"], SmsDeliveryStatus.ACCEPTED.value)

    def test_existing_delivery_reservation_is_never_sent_again(self):
        store = InMemoryAlertStore()
        sms = _Sms()
        dispatcher, _ = self.dispatcher(self.snapshot(), store=store, sms=sms)
        dispatcher.run(self.now)
        dispatcher.snapshot_provider.snapshot = self.snapshot("주의보")
        dispatcher.run(self.now + dt.timedelta(minutes=5))
        first_message = sms.messages[0]
        self.assertTrue(
            store.reserve_delivery(first_message, self.now).startswith("EXISTING_")
        )


class ContactAndProviderTests(unittest.TestCase):
    def test_solapi_webhook_only_4000_is_delivery_success(self):
        self.assertEqual(_provider_status("4000"), SmsDeliveryStatus.DELIVERED)
        self.assertEqual(_provider_status("4001"), SmsDeliveryStatus.FAILED)
        self.assertEqual(_provider_status("5000"), SmsDeliveryStatus.FAILED)

    def test_contact_rows_normalize_deduplicate_and_reject_invalid_rows(self):
        now = dt.datetime.now(dt.timezone.utc)
        rows = [
            {"facility_id": "F-1", "recipient_name": "담당", "phone": "010-1234-5678", "active": "TRUE"},
            {"facility_id": "F-1", "recipient_name": "중복", "phone": "01012345678", "active": "1"},
            {"facility_id": "F-2", "recipient_name": "미사용", "phone": "010-0000-0000", "active": "FALSE"},
        ]
        directory = build_contact_directory(rows, ("F-1", "F-2"), now)
        self.assertEqual(len(directory.recipients), 1)
        self.assertEqual(directory.recipients[0].phone, "01012345678")
        with self.assertRaisesRegex(ContactDataError, "등록되지 않은 시설코드"):
            build_contact_directory([
                {"facility_id": "UNKNOWN", "recipient_name": "담당", "phone": "01012345678", "active": "TRUE"}
            ], ("F-1",), now)

    def test_google_sheet_json_is_converted_without_leaking_rows(self):
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"values": [
                    ["facility_id", "recipient_name", "phone", "active", "note"],
                    ["F-1", "담당", "01012345678", "TRUE", ""],
                ]}

        class Session:
            def get(self, url, timeout):
                self.url = url
                return Response()

        provider = GoogleSheetContactProvider("sheet-id", session=Session())
        directory = provider.fetch(("F-1",))
        self.assertEqual(directory.unique_phone_count, 1)

    def test_solapi_acceptance_and_custom_delivery_id(self):
        class Request:
            def __init__(self, **values):
                self.values = values

        class Service:
            request_type = Request

            def send(self, request):
                self.request = request
                return {
                    "groupInfo": {"groupId": "G-1"},
                    "messageList": [{"messageId": "M-1"}],
                }

        service = Service()
        notifier = SolapiNotifier("key", "secret", "02-123-4567", service=service)
        from safety_dashboard.alerts.domain import OutgoingSmsMessage
        message = OutgoingSmsMessage(
            "delivery", "batch", "hash", "01012345678", "테스트",
            ("F-1",), ("T-1",),
        )
        result = notifier.send(message)
        self.assertEqual(result.status, SmsDeliveryStatus.ACCEPTED)
        self.assertEqual(result.provider_message_id, "M-1")
        self.assertEqual(service.request.values["customFields"]["deliveryId"], "delivery")

    def test_solapi_requests_message_list_for_delivery_tracking(self):
        class Request:
            def __init__(self, **values):
                self.values = values

        class RequestConfig:
            def __init__(self, *, show_message_list=False):
                self.show_message_list = show_message_list

        class Service:
            request_type = Request
            request_config_type = RequestConfig

            def send(self, request, request_config):
                self.request = request
                self.request_config = request_config
                return {
                    "groupInfo": {"groupId": "G-1"},
                    "messageList": [{"messageId": "M-1"}],
                }

        service = Service()
        notifier = SolapiNotifier("key", "secret", "02-123-4567", service=service)
        from safety_dashboard.alerts.domain import OutgoingSmsMessage
        message = OutgoingSmsMessage(
            "delivery", "batch", "hash", "01012345678", "테스트",
            ("F-1",), ("T-1",),
        )

        result = notifier.send(message)

        self.assertEqual(result.status, SmsDeliveryStatus.ACCEPTED)
        self.assertTrue(service.request_config.show_message_list)

    def test_solapi_registration_failure_is_not_treated_as_unknown(self):
        class Request:
            def __init__(self, **values):
                self.values = values

        class Failed:
            message_id = "M-FAILED"

        class MessageNotReceivedError(Exception):
            def __init__(self):
                self.failed_messages = [Failed()]

        class Service:
            request_type = Request

            def send(self, request):
                raise MessageNotReceivedError()

        from safety_dashboard.alerts.domain import OutgoingSmsMessage
        notifier = SolapiNotifier("key", "secret", "02-123-4567", service=Service())
        result = notifier.send(OutgoingSmsMessage(
            "delivery", "batch", "hash", "01012345678", "테스트",
            ("F-1",), ("T-1",),
        ))
        self.assertEqual(result.status, SmsDeliveryStatus.FAILED)
        self.assertEqual(result.provider_message_id, "M-FAILED")

    def test_solapi_sends_multiple_recipients_in_one_batch(self):
        class Request:
            def __init__(self, **values):
                self.values = values

        class Service:
            request_type = Request

            def send(self, requests):
                self.requests = requests
                return {
                    "groupInfo": {"groupId": "G-1"},
                    "messageList": [
                        {
                            "messageId": "M-2",
                            "customFields": {"deliveryId": "D-2"},
                        },
                        {
                            "messageId": "M-1",
                            "customFields": {"deliveryId": "D-1"},
                        },
                    ],
                }

        from safety_dashboard.alerts.domain import OutgoingSmsMessage
        messages = (
            OutgoingSmsMessage(
                "D-1", "batch", "hash-1", "01011112222", "테스트1",
                ("F-1",), ("T-1",),
            ),
            OutgoingSmsMessage(
                "D-2", "batch", "hash-2", "01033334444", "테스트2",
                ("F-2",), ("T-2",),
            ),
        )
        service = Service()
        notifier = SolapiNotifier("key", "secret", "02-123-4567", service=service)
        results = notifier.send_many(messages)
        self.assertEqual(len(service.requests), 2)
        self.assertEqual(
            [item.provider_message_id for item in results],
            ["M-1", "M-2"],
        )

    def test_solapi_balance_keeps_cash_and_point_separate(self):
        class Service:
            def get_balance(self):
                return {"balance": 12345.9, "point": 678.4}

        balance = SolapiNotifier(
            "key",
            "secret",
            "02-123-4567",
            service=Service(),
        ).fetch_balance()

        self.assertEqual(balance.balance, 12345)
        self.assertEqual(balance.point, 678)
        self.assertEqual(balance.available, 13023)


class _AdminStore:
    def __init__(self):
        self.reports = []

    def notification_status(self):
        return {"last_result": "NO_CHANGE"}

    def notification_metrics(self, start, end):
        return {"from": str(start), "to": str(end), "totals": {"poll_runs": 2}}

    def sms_count(self, day):
        return 0

    def monthly_sms_count(self, month):
        return 0

    def export_rows(self, start, end):
        return [{
            "record_type": "sms", "timestamp": str(start), "event": "",
            "facility_id": "F-1", "facility_name": "", "warning": "",
            "recipient_code": "abcdef", "delivery_status": "DELIVERED",
        }]

    def apply_provider_report(self, message_id, status_code, processed_at, delivery_id_hint=""):
        report = (message_id, status_code, delivery_id_hint)
        if report in self.reports:
            return False
        self.reports.append(report)
        return True


class _MonitoringApi:
    def monitoring(self, force_refresh=False, simulation=False):
        return {"api_version": "v1", "facilities": []}


class AlertAdminApiTests(unittest.TestCase):
    def setUp(self):
        self.store = _AdminStore()
        self.settings = AlertSettings(
            admin_token="admin-token",
            solapi_webhook_secret="webhook-secret",
        )
        self.admin = AlertAdminService(self.store, self.settings)

    def test_admin_token_webhook_hash_and_phone_free_csv(self):
        with self.assertRaises(AlertAdminAuthorizationError):
            self.admin.authorize_admin("wrong")
        self.admin.authorize_admin("admin-token")
        supplied = hashlib.sha1(b"webhook-secret").hexdigest()
        changed = self.admin.apply_webhook(supplied, [{
            "messageId": "M-1",
            "statusCode": "4000",
            "to": "01012345678",
            "customFields": {"deliveryId": "D-1"},
        }])
        self.assertEqual(changed, 1)
        self.assertEqual(self.store.reports[0], ("M-1", "4000", "D-1"))
        duplicate = self.admin.apply_webhook(supplied, [{
            "messageId": "M-1",
            "statusCode": "4000",
            "customFields": {"deliveryId": "D-1"},
        }])
        self.assertEqual(duplicate, 0)
        csv_data = self.admin.export_csv(dt.date(2026, 1, 1), dt.date(2026, 1, 2))
        self.assertNotIn(b"01012345678", csv_data)

    def test_http_routes_require_admin_token_and_accept_verified_webhook(self):
        client = TestClient(create_app(
            service=_MonitoringApi(),
            alert_admin_service=self.admin,
        ))
        self.assertEqual(
            client.get("/internal/v1/notifications/status").status_code,
            403,
        )
        status = client.get(
            "/internal/v1/notifications/status",
            headers={"X-Alert-Admin-Token": "admin-token"},
        )
        self.assertEqual(status.status_code, 200)
        webhook = client.post(
            "/api/v1/webhooks/solapi",
            headers={"X-Solapi-Secret": hashlib.sha1(b"webhook-secret").hexdigest()},
            json=[{"messageId": "M-2", "statusCode": "4000"}],
        )
        self.assertEqual(webhook.status_code, 200)
        self.assertEqual(webhook.json()["updated"], 1)

    def test_private_telegram_test_routes_select_different_audiences(self):
        class Dispatcher:
            def __init__(self):
                self.audiences = []
                self.heartbeat_calls = 0

            def send_telegram_test(self, audience):
                self.audiences.append(audience)
                return DispatchSummary(
                    "TELEGRAM_TEST_SENT",
                    "preview",
                    message_count=1,
                    accepted_count=1,
                )

            def send_heartbeat_test(self):
                self.heartbeat_calls += 1
                return DispatchSummary(
                    "HEARTBEAT_TEST_SENT",
                    "preview",
                    message_count=1,
                    accepted_count=1,
                )

        dispatcher = Dispatcher()
        client = TestClient(create_worker_app(dispatcher))
        admin = client.post("/internal/v1/test/telegram/admin")
        user = client.post("/internal/v1/test/telegram/user")
        heartbeat = client.post("/internal/v1/test/heartbeat")
        self.assertEqual(admin.status_code, 200)
        self.assertEqual(user.status_code, 200)
        self.assertEqual(heartbeat.status_code, 200)
        self.assertEqual(
            dispatcher.audiences,
            [TelegramAudience.ADMIN, TelegramAudience.USER],
        )
        self.assertEqual(dispatcher.heartbeat_calls, 1)


if __name__ == "__main__":
    unittest.main()
