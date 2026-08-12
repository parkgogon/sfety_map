import datetime as dt
import hashlib
import unittest

from fastapi.testclient import TestClient

from safety_dashboard.adapters.google_sheet_contacts import GoogleSheetContactProvider
from safety_dashboard.adapters.solapi import SolapiNotifier
from safety_dashboard.adapters.firestore_alerts import _provider_status
from safety_dashboard.alerts.admin import (
    AlertAdminAuthorizationError,
    AlertAdminService,
)
from safety_dashboard.alerts.contacts import ContactDataError, build_contact_directory
from safety_dashboard.alerts.domain import (
    ContactDirectory,
    FacilityRecipient,
    SmsDeliveryResult,
    SmsDeliveryStatus,
)
from safety_dashboard.alerts.memory_store import InMemoryAlertStore
from safety_dashboard.alerts.service import AlertDispatcher
from safety_dashboard.alerts.settings import AlertSettings
from safety_dashboard.alerts.transitions import detect_transitions, impacts_from_snapshot
from safety_dashboard.api.app import create_app
from safety_dashboard.application.monitoring import MonitoringService
from safety_dashboard.domain import (
    DataHealth,
    Facility,
    GeoPoint,
    Warning,
    WarningFeed,
    WarningLevel,
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

    def fetch(self, valid_facility_ids):
        if self.error:
            raise ContactDataError("테스트 연락처 장애")
        return ContactDirectory(
            tuple(self.recipients),
            "revision",
            dt.datetime.now(dt.timezone.utc),
        )


class _Sms:
    def __init__(self):
        self.messages = []

    def send(self, message):
        self.messages.append(message)
        return SmsDeliveryResult(
            SmsDeliveryStatus.ACCEPTED,
            provider_message_id=f"provider-{len(self.messages)}",
        )


class _Telegram:
    def __init__(self):
        self.batches = []

    def send_batch(self, messages):
        self.batches.append(tuple(messages))
        return object()


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

    def snapshot(self, raw_level=None, health=DataHealth.LIVE, minute=0):
        warnings = ()
        if raw_level:
            level = {
                "주의보": WarningLevel.ADVISORY,
                "경보": WarningLevel.WARNING,
            }[raw_level]
            warnings = (
                Warning(
                    f"W-{raw_level}-{minute}", "기상청", "L1070000", "L1070300",
                    "경상북도", "구미시", "강풍", raw_level, level,
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
            recipient_hmac_secret="test-hmac-secret",
            dashboard_base_url="https://keco-safety-map.web.app",
            daily_cap=50,
            cap_warning=40,
            pending_seconds=1800,
        )
        defaults.update(values)
        return AlertSettings(**defaults)

    def dispatcher(self, snapshot, contacts=None, store=None, sms=None, settings=None):
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
                _Telegram(),
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

    def test_contact_failure_holds_transition_and_recovers_as_delayed(self):
        store = InMemoryAlertStore()
        sms = _Sms()
        dispatcher, contacts = self.dispatcher(self.snapshot(), store=store, sms=sms)
        dispatcher.run(self.now)
        contacts.error = True
        dispatcher.snapshot_provider.snapshot = self.snapshot("주의보")
        result = dispatcher.run(self.now + dt.timedelta(minutes=5))
        self.assertEqual(result.status, "CONTACTS_ERROR")
        self.assertEqual(len(store.load_pending(self.now + dt.timedelta(minutes=6))), 2)
        contacts.error = False
        recovered = dispatcher.run(self.now + dt.timedelta(minutes=10))
        self.assertEqual(recovered.status, "DISPATCHED")
        self.assertEqual(len(sms.messages), 1)
        self.assertIn("[지연 알림]", sms.messages[0].text)

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


class _AdminStore:
    def __init__(self):
        self.reports = []

    def notification_status(self):
        return {"last_result": "NO_CHANGE"}

    def notification_metrics(self, start, end):
        return {"from": str(start), "to": str(end), "totals": {"poll_runs": 2}}

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


if __name__ == "__main__":
    unittest.main()
