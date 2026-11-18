"""Bounded production record audit. Firestore reads only; no providers or mutations."""
from __future__ import annotations

import collections
import datetime as dt
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
import os
import re
import threading

UTC = dt.timezone.utc
KST = dt.timezone(dt.timedelta(hours=9))
PROJECT = 'keco-safety-map'
MAX_SCAN, MAX_ROWS = 100, 40


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def safe_text(value, maximum=160):
    text = re.sub(r'\s+', ' ', str(value or '')).strip()
    text = re.sub(r'https?://\S+', '[링크 생략]', text)
    text = re.sub(r'(?<!\d)0\d{1,2}[- .]?\d{3,4}[- .]?\d{4}(?!\d)', '[연락처 생략]', text)
    text = re.sub(r'sk-(?:proj-)?[A-Za-z0-9_-]{16,}', '[키 생략]', text)
    return text[:maximum]


def when(value):
    try:
        moment = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(value)
        return moment.astimezone(UTC) if moment.tzinfo else None
    except (ValueError, TypeError):
        return None


def timestamp(value):
    moment = when(value)
    return moment.isoformat() if moment else None


def receipt(value):
    if not value:
        return None
    state = value.get('state')
    mid = value.get('message_id')
    return {'state': safe_text(state, 30), 'detail': safe_text(value.get('detail'), 90),
            'source_revision': value.get('source_revision'),
            'attempts': value.get('attempts'), 'created_at': timestamp(value.get('created_at')),
            'updated_at': timestamp(value.get('updated_at')), 'confirmed_api_receipt': state == 'sent' and type(mid) is int and mid > 0,
            'message_id': mid if state == 'sent' and type(mid) is int and mid > 0 else None,
            'resolution': safe_text(value.get('resolution'), 40) or None,
            'resolved_at': timestamp(value.get('resolved_at'))}


def screenshot_case(record):
    """Match the three user-supplied cases without exporting original text."""
    message = record.get('message', {})
    issued = when(message.get('issued_at'))
    if not issued or record.get('origin') != 'official':
        return None
    day = issued.astimezone(KST).date().isoformat()
    text = re.sub(r'\s+', '', message.get('text', ''))
    if day == '2026-11-10' and '범물' in text and '화재' in text:
        return 'beommul_fire'
    if day == '2026-11-17' and '상주' in text and '지진' in text:
        if '3.6' in text and ('조정' in text or '상세분석' in text):
            return 'sangju_earthquake_correction'
        if '3.7' in text:
            return 'sangju_earthquake_initial'
    return None


def probe_screenshot_source(*, fetch=None, validate=None, scope=None):
    """At most three official API reads; validate in memory, never import or send."""
    if fetch is None:
        from safety_dashboard.adapters.disaster_messages import SafetyDataDisasterMessageProvider
        fetch = SafetyDataDisasterMessageProvider(os.getenv('SAFETY_DATA_API_KEY', '')).fetch_page
    if validate is None:
        from safety_dashboard.application.message_records import MessageSource
        validate = lambda row: MessageSource(text=row.content, source='행정안전부 공개 재난문자 API',
            issued_at=row.created_at, recipient_regions=[r for r in row.regions if r != '-']).canonical()
    if scope is None:
        from safety_dashboard.application.message_collection import recipient_scope
        scope = recipient_scope
    report = {'status': 'passed', 'checked_at': dt.datetime.now(UTC).isoformat(),
        'api_calls': 0, 'production_documents_written': 0, 'model_calls': 0, 'messages_sent': 0,
        'query_start_date': '2026-11-17', 'query_region': None, 'pages': [], 'matches': [],
        'source_scan_complete': False}
    for page in range(1, 4):
        report['api_calls'] += 1
        response = fetch(None, dt.date(2026, 11, 17), page, 100)
        report['pages'].append({'page': page, 'rows': len(response['messages']),
            'skipped': response.get('skipped', 0), 'has_more': response['has_more']})
        for row in response['messages']:
            case = screenshot_case({'origin': 'official', 'message': {'text': row.content, 'issued_at': row.created_at.isoformat()}})
            if not case:
                continue
            item = {'case': case, 'issued_at': timestamp(row.created_at),
                'recipient_count': len(row.regions), 'max_recipient_length': max(map(len, row.regions), default=0),
                'recipient_scope': scope(row.regions), 'source_valid': True, 'validation_errors': []}
            try:
                validate(row)
            except ValueError as error:
                item['source_valid'] = False
                if callable(getattr(error, 'errors', None)):
                    for detail in error.errors(include_input=False)[:5]:
                        item['validation_errors'].append({'field': '.'.join(map(str, detail.get('loc', ()))),
                            'type': safe_text(detail.get('type'), 40),
                            'max_length': detail.get('ctx', {}).get('max_length'),
                            'actual_length': detail.get('ctx', {}).get('actual_length')})
                else:
                    item['validation_errors'] = [{'type': type(error).__name__}]
            report['matches'].append(item)
        if not response['has_more']:
            report['source_scan_complete'] = True
            break
    return report


class Reader:
    """Deliberately exposes no write, delete, transaction, or provider methods."""
    def __init__(self):
        from google.cloud import firestore
        self.client = firestore.Client(project=PROJECT)
        self.pipeline_collection = self.client.collection('disaster_message_pipeline')
        self.record_collection = self.client.collection('disaster_message_reviews')

    def latest_records(self, limit):
        from google.cloud import firestore
        assert 1 <= limit <= MAX_SCAN
        return [s.to_dict() for s in self.record_collection.order_by('sort_key', direction=firestore.Query.DESCENDING).limit(limit).stream(timeout=15)]

    def pipeline(self, keys):
        keys = list(dict.fromkeys(keys))
        assert len(keys) <= 150 and all(re.fullmatch(r'[A-Za-z0-9_.-]{1,240}', key) for key in keys)
        if not keys:
            return {}
        return {s.id: s.to_dict() for s in self.client.get_all([self.pipeline_collection.document(key) for key in keys], timeout=15) if s.exists}

    def history(self, prefix, limit):
        from google.cloud import firestore
        from google.cloud.firestore_v1.base_query import FieldFilter
        assert prefix in {'MH|', 'NE|'} and 1 <= limit <= 80
        q = self.pipeline_collection.where(filter=FieldFilter('queue_key', '>=', prefix)).where(filter=FieldFilter('queue_key', '<=', prefix+'~'))
        return [s.to_dict() for s in q.order_by('queue_key', direction=firestore.Query.DESCENDING).limit(limit).stream(timeout=15)]


def audit(reader, *, now=None):
    now = now or dt.datetime.now(UTC)
    cutoff = now-dt.timedelta(days=8)
    scanned = reader.latest_records(MAX_SCAN)
    official = [r for r in scanned if r.get('origin') == 'official' and (when(r.get('message', {}).get('issued_at')) or when(r.get('created_at')) or dt.datetime.min.replace(tzinfo=UTC)) >= cutoff]
    official.sort(key=lambda r: when(r.get('message', {}).get('issued_at')) or when(r['created_at']), reverse=True)
    selected = official[:MAX_ROWS]
    # Keep screenshot cases first so size limiting cannot hide an older match.
    selected.sort(key=lambda r: screenshot_case(r) is None)
    day = now.astimezone(KST).date().isoformat()
    month = now.astimezone(KST).strftime('%Y-%m')
    heads = ['notification-head-'+digest(r['id']) for r in selected]
    tasks = ['task-'+digest({k:r[k] for k in ('id', 'source_revision', 'content_hash')}) for r in selected]
    base = reader.pipeline(['collection-state', 'message-delivery-control', 'message-delivery-worker', 'queue-counts',
        'message-spend-day-'+day, 'message-spend-month-'+month, 'usage-'+day, 'message-spend-contract', *heads, *tasks])
    history = reader.history('MH|', 80)
    incidents = reader.history('NE|', 50)
    links = reader.pipeline([key for head in heads for key in (base.get(head, {}).get('decision_id'), base.get(head, {}).get('job_id')) if key])
    outbox_keys = ['message-delivery-'+digest(base[head]['job_id']) for head in heads if base.get(head, {}).get('job_id')]
    outbox_keys += ['message-delivery-'+digest(i['id']) for i in incidents]
    outboxes = reader.pipeline(outbox_keys)
    control, worker, collection = (base.get(k, {}) for k in ('message-delivery-control', 'message-delivery-worker', 'collection-state'))
    last = when(collection.get('last_attempt_at'))
    active = control.get('mode') == 'active' and worker.get('state') == 'active' and worker.get('generation') == control.get('generation') and worker.get('revision') == control.get('revision')
    state = 'error' if collection.get('last_error') else 'stale' if not last or (now-last).total_seconds() > 660 else 'partial' if collection.get('work') or collection.get('current_work') or collection.get('cycle_skipped') or collection.get('coverage_gap') else 'live'
    report = {'status': 'passed', 'checked_at': now.isoformat(), 'snapshot_is_atomic': False, 'window_start': cutoff.isoformat(), 'production_documents_written': 0,
        'feed_model_calls': 0, 'messages_sent_by_audit': 0, 'records_scanned': len(scanned), 'scan_limit_reached': len(scanned) == MAX_SCAN,
        'official_records_in_scanned_window': len(official), 'records_truncated': len(official) > MAX_ROWS,
        'collection': {'state':state, **{key: timestamp(collection.get(key)) for key in ('start_at','last_attempt_at','last_success_at','last_current_scan_success_at','last_backfill_success_at')},
            'last_error_stage': safe_text(collection.get('last_error_stage'), 40) if collection.get('last_error') else None,
            'remaining_partitions':len(collection.get('work',[]))+bool(collection.get('current_work')), 'skipped_rows':collection.get('cycle_skipped',0),
            'skipped_reasons': {key: collection.get('cycle_skipped_reasons', {}).get(key, 0)
                for key in ('source_fields', 'query_date', 'recipient_region', 'source_validation')},
            'coverage_gap':bool(collection.get('coverage_gap')), 'current_scan_interval_seconds':collection.get('current_scan_interval_seconds')},
        'delivery_control': {'mode':safe_text(control.get('mode'),20), 'started_at':timestamp(control.get('started_at')),
            'revision':safe_text(control.get('revision'),40), 'worker_at':timestamp(worker.get('at')), 'worker_state':safe_text(worker.get('state'),40),
            'same_generation_active':active, 'worker_stale':not when(worker.get('at')) or (now-when(worker.get('at'))).total_seconds()>180},
        'queue_counts':{k:base.get('queue-counts',{}).get(k,0) for k in ('pending','running','done','failed','obsolete','deferred')},
        'analysis_attempts_today':base.get('usage-'+day,{}).get('attempts',0),
        'spend': {label:{'settled_usd':base.get(key,{}).get('settled_nano',0)/1e9, 'reserved_usd':base.get(key,{}).get('reserved_nano',0)/1e9,
                  'unsettled_calls':base.get(key,{}).get('unsettled_calls',0), 'responses':base.get(key,{}).get('calls',0)}
                  for label,key in (('today','message-spend-day-'+day),('month','message-spend-month-'+month))},
        'screenshot_cases': {key: {'matches_in_scanned_records': sum(screenshot_case(r) == key for r in scanned),
            'record_ids': [r['id'] for r in scanned if screenshot_case(r) == key]}
            for key in ('beommul_fire', 'sangju_earthquake_initial', 'sangju_earthquake_correction')},
        'records': [], 'exceptions': []}
    for record, head_id, task in zip(selected, heads, tasks):
        rid = record['id'];head = base.get(head_id,{})
        decision = links.get(head.get('decision_id'),{});job = links.get(head.get('job_id'),{})
        snap = decision.get('snapshot',{});analysis = (record.get('analysis') or {}).get('analysis',{})
        assessment = analysis.get('notification_assessment') or {}
        related = [d for d in history if d.get('record_id') == rid]
        current_outbox = outboxes.get('message-delivery-'+digest(head['job_id'])) if head.get('job_id') else None
        row = {'record_id':rid,'screenshot_case':screenshot_case(record),'issued_at':timestamp(record['message'].get('issued_at')),'collected_at':timestamp(record.get('created_at')),
            'source_revision':record['source_revision'],'recipient_regions':[safe_text(r,50) for r in record['message'].get('recipient_regions',[])[:3]],
            'recipient_count':len(record['message'].get('recipient_regions',[])),
            'analysis_recipient_count':len((record.get('analysis') or {}).get('input',{}).get('recipient_regions',[])),
            'topic_keywords':[w for w in ('화재','산불','실종','호우','강풍','대설','지진','단수','통제','대피','훈련','안개','폭염','한파','건조','동파','침수') if w in record['message']['text']],
            'summary':safe_text(analysis.get('summary'),160),'analysis_state':safe_text(record.get('analysis_state'),30),
            'analysis_revision':record.get('analysis_revision'),'analysis_source_revision':record.get('analysis_source_revision'),
            'analysis_attempted_at':timestamp(record.get('analysis_attempted_at')),'analysis_error':safe_text(record.get('analysis_error'),140),
            'queue_state':safe_text(base.get(task,{}).get('state'),30),'queue_detail':safe_text(base.get(task,{}).get('detail'),90),
            'ai_need':assessment.get('need'),'ai_relevance':assessment.get('relevance'),'ai_reason':safe_text(assessment.get('reason'),160),
            'locations':[{'text':safe_text(loc.get('text'),60),'role':safe_text(loc.get('role'),30)} for part in analysis.get('parts',[]) for loc in part.get('locations',[])][:4],
            'decision_state':safe_text(head.get('state'),40),'server_decision':safe_text(snap.get('decision'),40),
            'server_reason':safe_text(snap.get('reason'),180),'decision_scope':safe_text(decision.get('scope'),30),'decision_at':timestamp(decision.get('created_at')),
            'job_state':safe_text(job.get('state'),30),'job_detail':safe_text(job.get('detail'),70),
            'facilities':[{'id':safe_text(f.get('id'),60),'name':safe_text(f.get('name'),60),'distance_m':f.get('distance_m')} for f in snap.get('facilities',[])[:5]],
            'current_delivery':receipt(current_outbox),'delivery_history':[receipt(d) for d in related[:3]],
            'confirmed_staff_receipts_in_scanned_history':sum(d.get('state')=='sent' and d.get('destination')=='staff_group' and type(d.get('message_id')) is int and d['message_id']>0 for d in related)}
        report['records'].append(row)
    for incident in incidents[:15]:
        report['exceptions'].append({'category':safe_text(incident.get('category'),50),'source_count':incident.get('source_count'),
            'updated_at':timestamp(incident.get('updated_at')),'record_ids':[r for r in incident.get('recent_record_ids',[]) if any(s['id']==r for s in selected)],
            'admin_delivery':receipt(outboxes.get('message-delivery-'+digest(incident['id'])))})
    report['history_states'] = dict(collections.Counter(d.get('state') for d in history))
    report['history_rows_scanned'] = len(history)
    report['history_scan_limit_reached'] = len(history) == 80
    # The existing private collector accepts 64 KiB. Preserve facts before prose.
    if len(json.dumps(report,ensure_ascii=False).encode()) > 60000:
        report['descriptions_shortened'] = True
        for row in report['records']:
            for key in ('summary','ai_reason','server_reason','analysis_error'):
                row[key] = row[key][:90]
            row['locations'] = row['locations'][:2];row['facilities'] = row['facilities'][:2]
    while len(json.dumps(report,ensure_ascii=False).encode()) > 60000:
        report['records'].pop();report['records_truncated'] = True
    report['records_returned'] = len(report['records'])
    return report


def handler():
    class Handler(BaseHTTPRequestHandler):
        result = None
        lock = threading.Lock()
        def log_message(self,*_args):pass
        def do_POST(self):
            if self.path != '/verify' or self.headers.get('Content-Length','0') != '0':
                self.send_error(400);return
            with self.lock:
                if type(self).result is None:
                    try:type(self).result = probe_screenshot_source() if os.getenv('AUDIT_SOURCE_CASES') == '1' else audit(Reader())
                    except Exception as error:type(self).result = {'status':'blocked','error_type':type(error).__name__,'production_documents_written':0,'messages_sent_by_audit':0}
            data=json.dumps(self.result,ensure_ascii=False).encode();self.send_response(200)
            self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    return Handler


if __name__ == '__main__':
    logging.disable(logging.CRITICAL)
    HTTPServer(('0.0.0.0',int(os.getenv('PORT','8080'))),handler()).serve_forever()
