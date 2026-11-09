import copy
import datetime as dt
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from safety_dashboard.operations.rollout_message_delivery import BASE, PREFIX, allowed_browser_request, rollout
from scripts.build_message_review_deploy_config import build_config

NOW = dt.datetime.fromisoformat('2026-11-10T09:00:00+09:00')
REVISION = 'a'*40


def fixture():
    automation = {'auto_collection_enabled': True, 'feed_configured': True, 'interval_seconds': 300,
        'recent_scan_enabled': True, 'budget': {'limit': 20}, 'feed_budget': {'limit': 450},
        'spend_budget': {'enabled': True, 'daily': {'limit_usd': 1}, 'monthly': {'limit_usd': 20}},
        'start_at': '2026-11-08T22:45:00+09:00', 'state': 'partial', 'current_scan_interval_seconds': 300,
        'last_current_scan_success_at': NOW.isoformat()}
    status = {'deployment_enabled': True, 'can_activate': True, 'active': False, 'state': 'ready',
        'generation': None, 'worker': {'revision': REVISION, 'at': NOW.isoformat(), 'state': 'paused_or_unconfigured', 'generation': None}}
    session = Mock(headers={})
    values = {'/api/v1/health/operations': {'status': 'ok', 'reason': 'ready'}, PREFIX+'/automation': automation,
        PREFIX+'/status': {'storage_mode': 'firestore', 'notification_preparation_enabled': True},
        '/internal/v1/message-analysis/status': {'configured': True, 'place_search_configured': True},
        PREFIX+'/notifications/status': status}
    def get(url, **kwargs):
        return Mock(status_code=200, json=lambda:copy.deepcopy(values[url.removeprefix(BASE)]))
    def post(url, **kwargs):
        if url.endswith('/admin/access'):
            return Mock(status_code=200, json=lambda:{'status':'ok','token':'private-session'})
        return Mock(status_code=200, json=lambda:{'active':True,'state':'active','generation':'b'*32,'started_at':NOW.isoformat()})
    session.get.side_effect, session.post.side_effect = get, post
    return session, automation, status, values


class DeliveryRolloutTests(unittest.TestCase):
    def run_check(self, session, action='status', **kwargs):
        return rollout(session, password='private-password', revision=REVISION, action=action, now=NOW, **kwargs)

    def test_status_is_read_only_after_login_and_does_not_export_authentication(self):
        session, *_ = fixture()
        browser = Mock(return_value={'widths':[1440,390], 'control_posts':0})
        report = self.run_check(session, browser=browser)
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(session.post.call_count, 1)
        self.assertEqual(report['control_requests'], 0)
        self.assertNotIn('private-', json.dumps(report))
        browser.assert_called_once_with('private-password', active=False)

    def test_start_uses_one_control_request_and_current_generation(self):
        session, _, status, _ = fixture()
        status['generation'] = 'c'*32
        report = self.run_check(session, 'start')
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(report['control_requests'], 1)
        self.assertEqual(session.post.call_count, 2)
        self.assertEqual(session.post.call_args.kwargs['json'], {'action':'start','expected_generation':'c'*32})

    def test_no_start_before_regular_work_and_exact_limits_cutoff_and_revision(self):
        for change in ('error','missing_current_scan','different_worker','stale_worker','cutoff','cost','request_limit'):
            session, auto, status, _ = fixture()
            if change == 'error': auto['state']='error'
            if change == 'missing_current_scan': auto['last_current_scan_success_at']=None
            if change == 'different_worker': status['worker']['revision']='b'*40
            if change == 'stale_worker': status['worker']['at']=(NOW-dt.timedelta(minutes=4)).isoformat()
            if change == 'cutoff': auto['start_at']=NOW.isoformat()
            if change == 'cost': auto['spend_budget']['daily']['limit_usd']=2
            if change == 'request_limit': auto['feed_budget']['limit']=500
            with self.subTest(change=change):
                report = self.run_check(session, 'start')
                self.assertEqual(report['status'], 'blocked')
                self.assertEqual(session.post.call_count, 1)

    def test_existing_active_control_is_not_restarted_or_moved(self):
        session, _, status, _ = fixture();status.update(active=True,state='active')
        report=self.run_check(session,'start')
        self.assertEqual(report['reason'],'delivery_not_off_before_start')
        self.assertEqual(report['control_requests'],0)

    def test_non_ready_operations_response_cannot_start_even_with_http_200(self):
        session, _, _, values = fixture()
        values['/api/v1/health/operations']['reason'] = 'kma_unavailable'
        report = self.run_check(session, 'start')
        self.assertEqual(report['reason'], 'operations_not_ready')
        self.assertEqual(session.post.call_count, 1)

    def test_lost_start_acknowledgement_is_read_back_without_second_post(self):
        session, _, status, values = fixture()
        original=session.post.side_effect
        def post(url, **kwargs):
            if url.endswith('/admin/access'):return original(url,**kwargs)
            values[PREFIX+'/notifications/status']={**status,'active':True,'state':'active','started_at':NOW.isoformat(),'generation':'b'*32}
            raise TimeoutError('private-provider-error')
        session.post.side_effect=post
        report=self.run_check(session,'start')
        self.assertEqual(report['status'],'passed')
        self.assertEqual(session.post.call_count,2)

    def test_unknown_start_without_saved_activation_is_not_retried(self):
        session, *_=fixture()
        session.post.side_effect=[Mock(status_code=200,json=lambda:{'status':'ok','token':'private-session'}),TimeoutError('private')]
        report=self.run_check(session,'start')
        self.assertEqual(report['reason'],'start_not_confirmed_do_not_retry')
        self.assertEqual(session.post.call_count,2)

    def test_observation_requires_worker_to_acknowledge_this_generation(self):
        session, _, status, _=fixture()
        status.update(active=True,state='active',generation='b'*32,worker_stale=False)
        status['worker'].update(state='active',generation='c'*32)
        self.assertEqual(self.run_check(session,'observe')['reason'],'current_generation_not_observed')
        status['worker']['generation']='b'*32
        self.assertEqual(self.run_check(session,'observe')['status'],'passed')

    def test_browser_cannot_start_reconsider_refresh_or_dispatch(self):
        for path in (PREFIX+'/notifications/control',PREFIX+'/feed','/internal/v1/dispatch','/api/v1/monitoring/refresh'):
            self.assertFalse(allowed_browser_request(BASE+path,'POST'))
        self.assertTrue(allowed_browser_request(BASE+PREFIX+'/notifications?kind=exceptions','GET'))
        self.assertTrue(allowed_browser_request(BASE+'/internal/v1/admin/access','POST'))
        self.assertFalse(allowed_browser_request('https://api.telegram.org/getMe','GET'))
        self.assertFalse(allowed_browser_request('https://private@keco-safety-map.web.app/','GET'))

    def test_versioned_release_matches_reviewed_configuration_with_fixed_staff_version_two(self):
        root=Path(__file__).resolve().parents[1]
        release=json.loads((root/'.github/message-delivery-release.json').read_text())
        proposed=json.loads((root/'docs/evidence/2026-11-10/message-delivery-runtime/proposed-repository-variables.json').read_text())
        self.assertEqual(build_config(release),build_config(proposed))
        self.assertIn('TELEGRAM_USER_CHAT_ID=TELEGRAM_USER_CHAT_ID:2',build_config(release)['MESSAGE_DELIVERY_SECRET_BINDINGS'])
