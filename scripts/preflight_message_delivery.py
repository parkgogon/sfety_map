"""Bounded preflight: existing secrets/read-only Telegram, isolated Firestore, fake sends."""
from __future__ import annotations

import argparse
import base64
import copy
import datetime as dt
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import threading

PROJECT = 'keco-safety-map'
REGION = 'asia-northeast3'
RUNTIME = 'safety-dashboard-runtime@keco-safety-map.iam.gserviceaccount.com'
HOME = 'https://keco-safety-map.web.app/'
ROOT_COLLECTION = 'message_delivery_preflight'
KEYS = ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_USER_CHAT_ID', 'TELEGRAM_ADMIN_CHAT_ID')
SECRET_NAMES = {'TELEGRAM_BOT_TOKEN', 'TELEGRAM_USER_CHAT_ID', 'TELEGRAM_CHAT_ID', 'TELEGRAM_ADMIN_CHAT_ID'}


def require(value, code):
    if not value:
        raise ValueError(code)


def validate_bindings(bindings):
    require(set(bindings) == set(KEYS), 'three_existing_bindings_required')
    for key, ref in bindings.items():
        require(set(ref) == {'name', 'version'}, 'invalid_reference')
        allowed = {'TELEGRAM_CHAT_ID', 'TELEGRAM_ADMIN_CHAT_ID'} if key == KEYS[2] else {key}
        require(ref['name'] in allowed and re.fullmatch(r'latest|[1-9][0-9]{0,18}', ref['version']), 'invalid_reference')
    return bindings


def metadata(query):
    services, bindings = {}, None
    for name in ('safety-dashboard-api', 'safety-alert-worker', 'safety-message-worker'):
        value = query(['run', 'services', 'describe', name, '--region', REGION])
        spec = value['spec']['template']['spec']
        require(spec['serviceAccountName'] == RUNTIME, 'runtime_account_changed')
        env = {e['name']: e for e in spec['containers'][0].get('env', [])}
        source = env.get('APP_REVISION', {}).get('value', '')
        require(re.fullmatch(r'[a-f0-9]{40}', source), 'source_revision_missing')
        require(env.get('MESSAGE_DELIVERY_ENABLED', {}).get('value', 'false') == 'false', 'delivery_already_enabled')
        refs = {}
        for key in KEYS:
            ref = env.get(key, {}).get('valueFrom', {}).get('secretKeyRef')
            if ref:
                refs[key] = {'name': ref['name'], 'version': ref['key']}
        if name != 'safety-message-worker':
            validate_bindings(refs)
            require(bindings is None or bindings == refs, 'existing_api_worker_bindings_differ')
            bindings = refs
        base = env.get('DASHBOARD_BASE_URL', {}).get('value', HOME)
        require(base.rstrip('/') == HOME.rstrip('/'), 'public_map_origin_changed')
        services[name] = {'source_revision': source, 'runtime_account_matches': True,
                          'delivery_enabled': False, 'telegram_references': refs,
                          'traffic': value['status'].get('traffic', [])}
    require(len({v['source_revision'] for v in services.values()}) == 1, 'deployed_sources_differ')
    schedules = {}
    for name in ('safety-message-collect', 'safety-message-analyze', 'safety-alert-dispatch'):
        value = query(['scheduler', 'jobs', 'describe', name, '--location', REGION])
        schedules[name] = {k: value.get(k) for k in ('state', 'schedule', 'timeZone')}
    return {'services': services, 'schedules': schedules, 'bindings': bindings, 'public_map': HOME}


def query(arguments):
    result = subprocess.run(['gcloud', *arguments, '--project', PROJECT, '--format=json', '--quiet'],
                            capture_output=True, text=True, timeout=30)
    require(result.returncode == 0, 'metadata_unavailable')
    return json.loads(result.stdout)


def resolve_secrets(bindings, session):
    """Use the existing runtime's accessor permission; return payloads only in memory."""
    validate_bindings(bindings)
    values, versions = {}, {}
    for key, ref in bindings.items():
        url = f"https://secretmanager.googleapis.com/v1/projects/{PROJECT}/secrets/{ref['name']}/versions/{ref['version']}:access"
        response = session.get(url, timeout=10, allow_redirects=False)
        require(response.status_code == 200, 'existing_secret_access_unverified')
        body = response.json()
        match = re.fullmatch(r'projects/[A-Za-z0-9_-]+/secrets/'+re.escape(ref['name'])+r'/versions/([1-9][0-9]{0,18})', body.get('name', ''))
        require(match is not None, 'numeric_secret_version_unverified')
        require(ref['version'] == 'latest' or ref['version'] == match[1], 'resolved_version_mismatch')
        raw = base64.b64decode(body['payload']['data'], validate=True).decode().strip()
        require(0 < len(raw) <= 500, 'invalid_existing_secret')
        values[key] = raw
        versions[key] = {'secret_name': ref['name'], 'numeric_version': match[1]}
    require(re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+', values[KEYS[0]]), 'invalid_existing_bot_format')
    require(all(re.fullmatch(r'-[0-9]+', values[key]) for key in KEYS[1:]), 'group_chat_required')
    require(values[KEYS[1]] != values[KEYS[2]], 'staff_admin_must_differ')
    return values, versions


def telegram_check(values, session):
    """Fixed read-only Bot API methods; never accept a method or destination from input."""
    calls = 0
    def read(method, params):
        nonlocal calls
        require(method in {'getMe', 'getChat', 'getChatMember'} and calls < 5, 'read_only_method_required')
        calls += 1
        response = session.get(f'https://api.telegram.org/bot{values[KEYS[0]]}/{method}',
                               params=params, timeout=(3, 7), allow_redirects=False)
        require(response.status_code == 200, 'telegram_read_access_unverified')
        body = response.json()
        require(body.get('ok') is True and isinstance(body.get('result'), dict), 'telegram_read_access_unverified')
        return body['result']
    me = read('getMe', {})
    require(me.get('is_bot') is True and type(me.get('id')) is int, 'bot_identity_unverified')
    result = {}
    for label, key in (('staff_group', KEYS[1]), ('admin_group', KEYS[2])):
        chat = read('getChat', {'chat_id': values[key]})
        require(str(chat.get('id')) == values[key] and chat.get('type') in {'group', 'supergroup'}, 'group_identity_unverified')
        member = read('getChatMember', {'chat_id': values[key], 'user_id': me['id']})
        require((member.get('user') or {}).get('id') == me['id'], 'bot_membership_unverified')
        status = member.get('status')
        allowed = status in {'creator', 'administrator'} or (status == 'member' and chat.get('permissions', {}).get('can_send_messages') is True)
        allowed = allowed or (status == 'restricted' and member.get('is_member') is True and member.get('can_send_messages') is True)
        require(allowed, 'group_posting_permission_unverified')
        result[label] = {'group_identity_matches': True, 'bot_member': True, 'posting_permission_observed': True}
    return {'read_calls': calls, 'groups_distinct': True, 'groups': result, 'actual_send_receipt': 'not_tested'}


class ScopedClient:
    """Map the two adapters to subcollections of this run; reject every other root."""
    def __init__(self, client, root):
        self.client, self.root = client, root

    def collection(self, name):
        require(name in {'disaster_message_pipeline', 'disaster_message_reviews'}, 'production_collection_forbidden')
        return self.root.collection(name)

    def transaction(self):
        return self.client.transaction(max_attempts=3)

    def get_all(self, refs, **kwargs):
        require(all(ref.path.startswith(self.root.path+'/') for ref in refs), 'production_document_forbidden')
        return self.client.get_all(refs, **kwargs)


def storage_checks(client, *, fixture, now, revision, facility_path=Path('/app/facilities_info.csv'), transaction_runner=None):
    """Exercise current adapters/business logic with synthetic records and fake receipts."""
    from safety_dashboard.adapters.facility_csv import CsvFacilityRepository
    from safety_dashboard.adapters.firestore_message_notifications import FirestoreMessageNotificationStore
    from safety_dashboard.adapters.firestore_message_records import FirestoreMessageRecordStore
    from safety_dashboard.adapters.telegram import TelegramDeliveryResult
    from safety_dashboard.application.message_delivery import MessageDelivery, delivery_key
    from safety_dashboard.application.message_notification_jobs import MessageNotificationPreparation
    from safety_dashboard.application.message_records import MessageRecordService, RecordConflict
    catalog = CsvFacilityRepository(facility_path).snapshot()
    options = {'transaction_runner': transaction_runner} if transaction_runner else {}
    record_store = FirestoreMessageRecordStore(client=client, **options)
    store = FirestoreMessageNotificationStore(client=client, **options)
    clock = [now-dt.timedelta(minutes=10)]
    records = MessageRecordService(lambda: record_store, None, storage_mode='firestore', now=lambda: clock[0])
    planner = MessageNotificationPreparation(records, lambda: store, lambda: catalog, enabled=True,
        base_url=HOME, now=lambda: clock[0], delivery_tracking_enabled=True)
    planner.activate()
    class FakeSender:
        configured = True
        calls = 0
        def send_once(self, text):
            require(text and len(text) <= 3900, 'fixture_preview_invalid')
            self.calls += 1
            return TelegramDeliveryResult('sent', message_id=1, detail='receipt_confirmed')
    staff, admin = FakeSender(), FakeSender()
    def delivery(**kwargs):
        return MessageDelivery(planner, {'staff_group': staff, 'admin_group': admin}, enabled=True,
            binding='isolated-fake-binding', revision=kwargs.get('revision', revision), now=lambda: clock[0])
    service = delivery()
    def prepare(identifier):
        result = copy.deepcopy(fixture)
        issued = dt.datetime.fromisoformat(result['input']['issued_at'])
        shift = clock[0] - issued
        for part in result['analysis']['parts']:
            for key in ('starts_at', 'ends_at'):
                if part.get(key):
                    part[key] = (dt.datetime.fromisoformat(part[key])+shift).isoformat()
        result['input'].update(issued_at=clock[0].isoformat(), input_kind='official')
        message = {key: result['input'][key] for key in ('text', 'source', 'issued_at', 'recipient_regions')}
        record = records.register_official(message, 'isolated-preflight-'+identifier, clock[0].isoformat())['record']
        record = record_store.commit({**record, 'preflight_fixture': True, 'analysis': result,
            'analysis_state': 'completed', 'analysis_revision': 1, 'analysis_source_revision': record['source_revision'],
            'facility_digest': catalog[0]}, record['version'], 'isolated_preflight_fixture')
        prepared = planner.prepare_record(record['id'])
        require(prepared['state'] == 'pending', 'fixture_not_ready')
        return record, prepared['job_id']
    clock[0] = now-dt.timedelta(minutes=8)
    old, old_job = prepare('old')
    started = service.configure('start', None)
    service.run()
    require(staff.calls == 0 and store.get(delivery_key(old_job)) is None, 'old_preview_promoted')
    clock[0] += dt.timedelta(minutes=1)
    paused_record, paused_job = prepare('paused')
    service.consider_staff(paused_job)
    paused = service.configure('pause', started['generation'])
    service.run()
    require(staff.calls == 0 and not service.status()['active'], 'pause_boundary_failed')
    try:
        service.configure('start', started['generation'])
    except RecordConflict:
        pass
    else:
        raise ValueError('control_conflict_not_blocked')
    clock[0] += dt.timedelta(minutes=1)
    service.configure('start', paused['generation'])
    service.run()
    require(staff.calls == 0 and store.get(delivery_key(paused_job))['state'] == 'cancelled', 'paused_backlog_promoted')
    clock[0] += dt.timedelta(minutes=1)
    fresh, jid = prepare('fresh')
    before = record_store.history(fresh['id'], None, 10)
    require(planner._preview(fresh, catalog)['map_url'] == HOME, 'public_link_changed')
    service.run()
    delivery().run()
    outbox = store.get(delivery_key(jid))
    require(staff.calls == 1 and admin.calls == 0 and outbox['state'] == 'sent', 'fake_receipt_persistence_failed')
    require(outbox['message_id'] == 1 and len(service.page('deliveries')['items']) == 2, 'history_read_failed')
    require(record_store.history(fresh['id'], None, 10) == before, 'human_history_changed')
    require(records.get(fresh['id'])['review_state'] == 'unreviewed' and store.get(jid)['dispatch_enabled'] is False,
            'human_review_or_preview_permission_changed')
    require(not delivery(revision='other-revision').status()['active'], 'new_revision_activated')
    return {'isolated_transactions_and_history': True, 'old_preview_excluded': True, 'pause_resume_excludes_backlog': True,
        'control_conflict_rejected': True, 'new_revision_requires_start': True, 'fake_receipt_persisted_once': True,
        'human_review_unchanged': True, 'public_preview_link': HOME, 'fake_staff_requests': staff.calls,
        'actual_firestore_paths': 'message_delivery_preflight/<run>/disaster_message_{pipeline,reviews}'}


def cleanup(root):
    deleted = 0
    for name in ('disaster_message_pipeline', 'disaster_message_reviews'):
        collection = root.collection(name)
        rows = list(collection.limit(101).stream(timeout=10))
        require(len(rows) <= 100, 'cleanup_document_cap')
        for snap in rows:
            if name == 'disaster_message_reviews':
                versions = list(snap.reference.collection('versions').limit(11).stream(timeout=10))
                require(len(versions) <= 10, 'cleanup_version_cap')
                for version in versions:
                    version.reference.delete(timeout=5)
                    deleted += 1
            snap.reference.delete(timeout=5)
            deleted += 1
        require(not list(collection.limit(1).stream(timeout=5)), 'cleanup_incomplete')
    root.delete(timeout=5)
    return {'complete': not root.get(timeout=5).exists, 'documents_deleted': deleted+1}


def run():
    # Avoid HTTP library debug output containing the bot token or Secret payload.
    logging.disable(logging.CRITICAL)
    report = {'status': 'blocked', 'checked_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'production_documents_written': 0, 'production_control_changed': False, 'messages_sent': 0,
        'feed_model_place_calls': 0, 'secret_values_exported': False, 'phase': 'validate_run'}
    root, owns_root = None, False
    try:
        run_id = os.environ['PREFLIGHT_RUN_ID']
        revision = os.environ['PREFLIGHT_REVISION']
        require(re.fullmatch(r'[0-9]{8,20}', run_id), 'invalid_run_id')
        require(re.fullmatch(r'[a-f0-9]{40}', revision), 'invalid_revision')
        report['candidate_revision'] = revision
        import google.auth
        from google.auth.transport.requests import AuthorizedSession
        import requests
        credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
        report['phase'] = 'resolve_existing_secrets'
        values, report['fixed_versions'] = resolve_secrets(json.loads(os.environ['PREFLIGHT_BINDINGS']), AuthorizedSession(credentials))
        report['phase'] = 'read_only_telegram'
        report['telegram'] = telegram_check(values, requests.Session())
        values.clear()
        report['phase'] = 'public_staff_link'
        response = requests.get(HOME, timeout=(3, 7), allow_redirects=False)
        require(response.status_code == 200 and 'text/html' in response.headers.get('Content-Type', ''), 'public_map_unavailable')
        report['public_map'] = {'unauthenticated_http_200': True, 'url': HOME, 'real_employee_device': 'not_tested'}
        report['phase'] = 'isolated_firestore'
        from google.cloud import firestore
        client = firestore.Client(project=PROJECT)
        root = client.collection(ROOT_COLLECTION).document(run_id)
        root.create({'kind': 'isolated_synthetic_preflight', 'revision': revision,
                     'created_at': dt.datetime.now(dt.timezone.utc)}, timeout=5)
        owns_root = True
        fixture = json.loads(Path('/app/delivery-fixture.json').read_text())
        report['storage'] = storage_checks(ScopedClient(client, root), fixture=fixture,
                                          now=dt.datetime.now(dt.timezone.utc), revision=revision)
        report.update(status='passed', phase='finished')
    except Exception as error:
        report['error_type'] = type(error).__name__ if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}', type(error).__name__) else 'unknown'
        if isinstance(error, ValueError) and re.fullmatch(r'[a-z_]{1,80}', str(error)):
            report['reason'] = str(error)
    finally:
        if owns_root:
            try:
                report['cleanup'] = cleanup(root)
            except Exception:
                report.update(status='blocked', cleanup={'complete': False})
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
                    type(self).result = run()
            data = json.dumps(self.result, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['prepare', 'compare', 'serve'])
    args = parser.parse_args()
    if args.mode == 'serve':
        HTTPServer(('0.0.0.0', int(os.getenv('PORT', '8080'))), handler()).serve_forever()
        return
    out = Path('delivery-preflight')
    out.mkdir(exist_ok=True)
    snapshot = metadata(query)
    if args.mode == 'compare':
        require(snapshot == json.loads((out/'metadata-before.json').read_text()), 'production_metadata_changed')
        (out/'metadata-unchanged.json').write_text(json.dumps({'unchanged': True})+'\n')
        return
    (out/'metadata-before.json').write_text(json.dumps(snapshot, indent=2)+'\n')
    fixture = json.loads(Path('docs/evidence/2026-11-10/message-ai-judgment-fix/attempt-4/results.json').read_text())
    fixture = next(case['result'] for case in fixture['cases'] if case['id'] == 'event')
    (out/'delivery-fixture.json').write_text(json.dumps(fixture, ensure_ascii=False)+'\n')
    env = {'PREFLIGHT_RUN_ID': os.environ['GITHUB_RUN_ID'], 'PREFLIGHT_REVISION': os.environ['GITHUB_SHA'],
           'PREFLIGHT_BINDINGS': json.dumps(snapshot['bindings'])}
    (out/'runtime-env.json').write_text(json.dumps(env)+'\n')
    source = snapshot['services']['safety-message-worker']['source_revision']
    deployed_requirements = subprocess.run(['git', 'show', source+':requirements-api.txt'], capture_output=True, check=True).stdout
    require(deployed_requirements == Path('requirements-api.txt').read_bytes(), 'runtime_dependencies_changed')
    dockerfile = f'''FROM asia-northeast3-docker.pkg.dev/{PROJECT}/safety-dashboard/worker:{source}
RUN rm -rf /app/safety_dashboard
COPY safety_dashboard /app/safety_dashboard
COPY facilities_info.csv /app/facilities_info.csv
COPY scripts/preflight_message_delivery.py /app/preflight.py
COPY delivery-preflight/delivery-fixture.json /app/delivery-fixture.json
'''
    (out/'Dockerfile').write_text(dockerfile)


if __name__ == '__main__':
    main()
