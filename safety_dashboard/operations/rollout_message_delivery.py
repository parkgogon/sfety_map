"""Verify the deployed release, start once when authorized, and observe regular work.

Only the start action changes production delivery control. No feed/model/dispatch/test
endpoints or Telegram provider are invoked. Password/session values stay in memory.
"""
from __future__ import annotations

import datetime as dt
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
import os
import re
import threading
from urllib.parse import urlsplit

BASE = 'https://keco-safety-map.web.app'
PREFIX = '/internal/v1/message-records'
UTC = dt.timezone.utc
READS = {'/api/v1/health/operations', '/internal/v1/message-analysis/status',
         PREFIX+'/status', PREFIX+'/automation', PREFIX+'/notifications/status'}


def require(value, code):
    if not value:
        raise ValueError(code)


def fresh(value, seconds, now):
    try:
        age = (now-dt.datetime.fromisoformat(value)).total_seconds()
        return -10 <= age <= seconds
    except (TypeError, ValueError):
        return False


def checks(automation, status, revision, now, action):
    require(automation['auto_collection_enabled'] and automation['feed_configured'], 'collection_not_configured')
    require(automation['interval_seconds'] == 300 and automation.get('recent_scan_enabled'), 'recent_scan_not_enabled')
    require(automation['budget']['limit'] == 20 and automation['feed_budget']['limit'] == 450, 'request_limits_differ')
    spend = automation.get('spend_budget', {})
    require(spend.get('enabled') and spend['daily']['limit_usd'] == 1 and spend['monthly']['limit_usd'] == 20, 'spend_limits_differ')
    require(dt.datetime.fromisoformat(automation['start_at']) == dt.datetime.fromisoformat('2026-11-08T22:45:00+09:00'), 'collection_cutoff_changed')
    worker = status.get('worker') or {}
    require(worker.get('revision') == revision and fresh(worker.get('at'), 180, now), 'regular_worker_not_observed')
    require(automation.get('state') in {'live', 'partial'}, 'regular_collection_not_ready')
    interval = automation.get('current_scan_interval_seconds', 300)
    require(type(interval) is int and 300 <= interval <= 3600, 'current_scan_interval_invalid')
    require(fresh(automation.get('last_current_scan_success_at'), interval*2+60, now), 'current_scan_not_observed')
    require(status.get('deployment_enabled') and status.get('can_activate'), 'delivery_not_configured')
    if action == 'observe':
        require(status.get('active') and worker.get('state') == 'active' and not status.get('worker_stale'), 'active_worker_not_observed')
        require(worker.get('generation') == status.get('generation'), 'current_generation_not_observed')
    else:
        require(not status.get('active') and status.get('state') in {'ready', 'paused'}, 'delivery_not_off_before_start')


def allowed_browser_request(url, method):
    parsed = urlsplit(url)
    own = parsed.scheme == 'https' and parsed.hostname == 'keco-safety-map.web.app' and not parsed.username and not parsed.password and parsed.port in (None, 443)
    path = parsed.path
    return own and ((method == 'GET' and (not path.startswith(('/internal/', '/api/'))
        or path in READS or path in {PREFIX+'/notifications', '/internal/v1/admin/session'}))
        or method == 'POST' and path == '/internal/v1/admin/access')


def browser_check(password, *, active=False):
    from playwright.sync_api import sync_playwright, expect
    denied, errors, widths = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', headless=True,
                                   args=['--no-sandbox', '--disable-dev-shm-usage'])
        context = browser.new_context(viewport={'width': 1440, 'height': 1050})
        def route(r):
            if allowed_browser_request(r.request.url, r.request.method):
                r.continue_()
            else:
                denied.append(True)
                r.abort()
        context.route('**/*', route)
        page = context.new_page()
        page.on('pageerror', lambda _: errors.append(True))
        page.goto(BASE+'/control/messages?view=delivery', wait_until='networkidle', timeout=60000)
        page.get_by_label('관리자 비밀번호', exact=True).fill(password)
        page.get_by_role('button', name='로그인', exact=True).click()
        heading = '재난문자 자동전파 중' if active else re.compile('자동전파 (시작 대기|일시정지)')
        page.get_by_role('heading', name=heading, exact=True).wait_for(timeout=30000)
        for width in (1440, 390):
            page.set_viewport_size({'width': width, 'height': 1050})
            page.get_by_role('button', name='전파 일시정지' if active else '자동전파 시작', exact=True).wait_for()
            for label in ('판단 기록', '확인 필요', '전파 이력'):
                page.get_by_role('button', name=label, exact=True).click()
                expect(page.get_by_role('button', name=label, exact=True)).to_have_attribute('aria-pressed', 'true')
            page.get_by_role('heading', name=heading, exact=True).wait_for()
            require(page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'mobile_horizontal_overflow')
            widths.append(width)
        browser.close()
    require(not denied and not errors, 'browser_requests_or_errors')
    return {'widths': widths, 'three_tabs': True, 'page_errors': 0, 'unexpected_requests': 0, 'control_posts': 0}


def rollout(session, *, password, revision, action, now=None, browser=None):
    require(re.fullmatch(r'[a-f0-9]{40}', revision) and action in {'status', 'start', 'observe'}, 'invalid_release_target')
    require(bool(password), 'admin_password_missing')
    fixed_now = now
    now = now or dt.datetime.now(UTC)
    report = {'status': 'blocked', 'action': action, 'source_revision': revision, 'checked_at': now.isoformat(),
              'control_requests': 0, 'test_messages_sent': 0, 'manual_feed_model_dispatch_calls': 0, 'phase': 'login'}
    def request(path, body=None):
        require(path in READS or path == '/internal/v1/admin/access' or action == 'start' and path == PREFIX+'/notifications/control', 'forbidden_endpoint')
        response = session.get(BASE+path, timeout=(3, 20), allow_redirects=False) if body is None else session.post(
            BASE+path, json=body, timeout=(3, 20), allow_redirects=False)
        require(response.status_code == 200, 'protected_request_failed')
        return response.json()
    try:
        authenticated = request('/internal/v1/admin/access', {'password': password})
        require(authenticated.get('status') == 'ok', 'admin_authentication_failed')
        session.headers['X-Alert-Admin-Token'] = authenticated['token']
        report['phase'] = 'release_checks'
        health = request('/api/v1/health/operations')
        require(health.get('status') == 'ready', 'operations_not_ready')
        configured = request(PREFIX+'/status')
        require(configured.get('storage_mode') == 'firestore' and configured.get('notification_preparation_enabled'), 'persistent_preparation_not_ready')
        analysis = request('/internal/v1/message-analysis/status')
        require(analysis.get('configured') and analysis.get('place_search_configured'), 'analysis_not_configured')
        automation = request(PREFIX+'/automation')
        status = request(PREFIX+'/notifications/status')
        report['automation'] = {key: automation.get(key) for key in ('state', 'interval_seconds', 'start_at', 'last_attempt_at',
            'last_success_at', 'last_current_scan_success_at', 'last_backfill_success_at', 'remaining_partitions',
            'current_scan_interval_seconds', 'budget', 'feed_budget', 'spend_budget')}
        report['delivery'] = {key: status.get(key) for key in ('active', 'state', 'generation', 'started_at', 'worker', 'worker_stale')}
        checks(automation, status, revision, now, action)
        if browser and action != 'start':
            report['phase'] = 'browser'
            report['browser'] = browser(password, active=action == 'observe')
        if action == 'start':
            report['phase'] = 'start_once'
            report['control_requests'] = 1
            try:
                status = request(PREFIX+'/notifications/control', {'action': 'start', 'expected_generation': status['generation']})
            except Exception:
                # A lost acknowledgement must not move the cutoff again. Read only.
                status = request(PREFIX+'/notifications/status')
            require(status.get('active') is True and fresh(status.get('started_at'), 120, fixed_now or dt.datetime.now(UTC)), 'start_not_confirmed_do_not_retry')
            report['delivery'] = {key: status.get(key) for key in ('active', 'state', 'generation', 'started_at', 'worker', 'worker_stale')}
        report.update(status='passed', phase='finished')
    except Exception as error:
        report['error_type'] = type(error).__name__
        if isinstance(error, ValueError) and re.fullmatch(r'[a-z_]{1,80}', str(error)):
            report['reason'] = str(error)
    return report


def handler():
    class Handler(BaseHTTPRequestHandler):
        result = None
        lock = threading.Lock()
        def log_message(self, *_args):
            pass
        def do_POST(self):
            if self.path != '/verify' or self.headers.get('Content-Length', '0') != '0':
                self.send_error(400)
                return
            with self.lock:
                if type(self).result is None:
                    import requests
                    type(self).result = rollout(requests.Session(), password=os.getenv('ADMIN_ACCESS_PASSWORD', ''),
                        revision=os.getenv('VERIFY_APP_REVISION', ''), action=os.getenv('VERIFY_DELIVERY_ACTION', 'status'), browser=browser_check)
            data = json.dumps(self.result, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    return Handler


if __name__ == '__main__':
    logging.disable(logging.CRITICAL)
    HTTPServer(('0.0.0.0', int(os.getenv('PORT', '8080'))), handler()).serve_forever()
