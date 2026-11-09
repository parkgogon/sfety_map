"""Preflight cannot send, export secrets, or address production collections."""
import base64
import datetime as dt
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from scripts.preflight_message_delivery import (
    KEYS, HOME, ScopedClient, metadata, resolve_secrets, storage_checks, telegram_check,
)
from tests.test_message_notification_store import AtomicFirestore

ROOT = Path(__file__).resolve().parents[1]
BINDINGS = {key: {'name': key if key != KEYS[2] else 'TELEGRAM_CHAT_ID', 'version': '1' if key == KEYS[0] else 'latest'} for key in KEYS}
VALUES = {KEYS[0]: '123:fake-token', KEYS[1]: '-100111', KEYS[2]: '-100222'}


def response(value):
    return Mock(status_code=200, json=lambda: value)


class DeliveryPreflightTests(unittest.TestCase):
    def test_accessor_response_resolves_latest_to_numeric_without_exporting_payloads(self):
        session = Mock()
        session.get.side_effect = [response({'name': f"projects/123456/secrets/{ref['name']}/versions/1",
            'payload': {'data': base64.b64encode(VALUES[key].encode()).decode()}}) for key, ref in BINDINGS.items()]
        values, versions = resolve_secrets(BINDINGS, session)
        self.assertEqual(values, VALUES)
        self.assertEqual({r['numeric_version'] for r in versions.values()}, {'1'})
        self.assertNotIn('fake-token', json.dumps(versions))
        for call in session.get.call_args_list:
            self.assertIn('secretmanager.googleapis.com/v1/projects/keco-safety-map/secrets/', call.args[0])
            self.assertFalse(call.kwargs['allow_redirects'])

    def test_version_mismatch_and_same_staff_admin_room_fail_closed(self):
        for wrong_version, same_room in ((True, False), (False, True)):
            session = Mock()
            session.get.side_effect = [response({'name': f"projects/123456/secrets/{ref['name']}/versions/{'2' if wrong_version else '1'}",
                'payload': {'data': base64.b64encode((VALUES[KEYS[1]] if same_room and key == KEYS[2] else VALUES[key]).encode()).decode()}})
                for key, ref in BINDINGS.items()]
            with self.assertRaises(ValueError):
                resolve_secrets(BINDINGS, session)

    def test_telegram_checks_use_only_five_read_requests_and_keep_id_title_private(self):
        session = Mock()
        session.get.side_effect = [response({'ok': True, 'result': {'id': 123, 'is_bot': True}}), *[
            item for key in KEYS[1:] for item in (
                response({'ok': True, 'result': {'id': int(VALUES[key]), 'type': 'supergroup', 'title': 'private-room',
                                                'permissions': {'can_send_messages': True}}}),
                response({'ok': True, 'result': {'user': {'id': 123}, 'status': 'member'}}))]]
        result = telegram_check(VALUES, session)
        self.assertEqual(result['read_calls'], 5)
        self.assertEqual([c.args[0].rsplit('/', 1)[-1] for c in session.get.call_args_list],
                         ['getMe', 'getChat', 'getChatMember', 'getChat', 'getChatMember'])
        self.assertFalse(session.post.called)
        self.assertNotIn('private-room', json.dumps(result))
        self.assertNotIn('-100111', json.dumps(result))

    def test_unverified_membership_or_posting_permission_blocks_preflight(self):
        for status, can_send in (('left', True), ('kicked', True), ('member', False), ('restricted', True)):
            session = Mock()
            session.get.side_effect = [response({'ok': True, 'result': {'id': 123, 'is_bot': True}}),
                response({'ok': True, 'result': {'id': int(VALUES[KEYS[1]]), 'type': 'supergroup', 'permissions': {'can_send_messages': can_send}}}),
                response({'ok': True, 'result': {'user': {'id': 123}, 'status': status}})]
            with self.assertRaises(ValueError):
                telegram_check(VALUES, session)
            self.assertFalse(session.post.called)

    def test_existing_admin_private_destination_is_readable_without_claiming_post_permission(self):
        session = Mock()
        values = {**VALUES, KEYS[2]: '123456'}
        session.get.side_effect = [response({'ok': True, 'result': {'id': 123, 'is_bot': True}}),
            response({'ok': True, 'result': {'id': int(values[KEYS[1]]), 'type': 'supergroup'}}),
            response({'ok': True, 'result': {'user': {'id': 123}, 'status': 'administrator'}}),
            response({'ok': True, 'result': {'id': 123456, 'type': 'private'}})]
        result = telegram_check(values, session)
        self.assertEqual(result['read_calls'], 4)
        self.assertTrue(result['groups']['admin_group']['read_access_observed'])
        self.assertIsNone(result['groups']['admin_group']['posting_permission_observed'])
        self.assertFalse(session.post.called)

    def test_private_staff_destination_is_never_accepted_as_the_staff_group(self):
        session = Mock()
        session.get.side_effect = [response({'ok': True, 'result': {'id': 123, 'is_bot': True}}),
            response({'ok': True, 'result': {'id': int(VALUES[KEYS[1]]), 'type': 'private'}})]
        with self.assertRaisesRegex(ValueError, 'staff_group_required'):
            telegram_check(VALUES, session)

    def test_scoped_adapters_cannot_address_other_collections_or_production_documents(self):
        client, root = Mock(), Mock(path='message_delivery_preflight/123456789')
        scoped = ScopedClient(client, root)
        scoped.collection('disaster_message_pipeline')
        root.collection.assert_called_once_with('disaster_message_pipeline')
        for name in ('alert_state', 'message_delivery_preflight', 'disaster_message_pipeline/x'):
            with self.assertRaises(ValueError):
                scoped.collection(name)
        with self.assertRaises(ValueError):
            scoped.get_all([Mock(path='disaster_message_reviews/private')])
        self.assertFalse(client.collection.called)
        self.assertFalse(client.get_all.called)

    def test_current_business_flow_round_trips_transactions_history_and_activation_boundaries(self):
        client = AtomicFirestore()
        report = json.loads((ROOT/'docs/evidence/2026-11-10/message-ai-judgment-fix/attempt-4/results.json').read_text())
        fixture = next(case['result'] for case in report['cases'] if case['id'] == 'event')
        result = storage_checks(client, fixture=fixture, now=dt.datetime.fromisoformat('2026-11-10T08:00:00+09:00'),
                                revision='a'*40, facility_path=ROOT/'facilities_info.csv', transaction_runner=client.runner)
        self.assertEqual(result['fake_staff_requests'], 1)
        self.assertTrue(result['human_review_unchanged'])
        self.assertTrue(result['pause_resume_excludes_backlog'])
        self.assertEqual(result['public_preview_link'], HOME)

    def test_metadata_requires_same_runtime_and_existing_api_worker_bindings(self):
        def query(args):
            if args[0] == 'scheduler':
                return {'state': 'ENABLED', 'schedule': '*/5 * * * *', 'timeZone': 'Asia/Seoul'}
            return {'spec': {'template': {'spec': {'serviceAccountName': 'safety-dashboard-runtime@keco-safety-map.iam.gserviceaccount.com',
                'containers': [{'env': [{'name': 'APP_REVISION', 'value': 'a'*40}, *[
                    {'name': key, 'valueFrom': {'secretKeyRef': {'name': ref['name'], 'key': ref['version']}}}
                    for key, ref in BINDINGS.items()]]}]}}}, 'status': {'traffic': []}}
        self.assertEqual(metadata(query)['bindings'], BINDINGS)
        def changed(args):
            value = query(args)
            if args[0] == 'run' and args[3] == 'safety-dashboard-api':
                value['spec']['template']['spec']['containers'][0]['env'][1]['valueFrom']['secretKeyRef']['key'] = '2'
            return value
        with self.assertRaisesRegex(ValueError, 'existing_api_worker_bindings_differ'):
            metadata(changed)
