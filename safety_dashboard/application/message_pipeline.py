"""Persistent leases, conservative analysis budget and source-version queue."""
from __future__ import annotations
import copy
import datetime as dt
import threading
from typing import Protocol
from safety_dashboard.application.context_info import KST
from safety_dashboard.application.message_analysis import AnalysisBusy, AnalysisUnavailable
from safety_dashboard.application.message_records import content_hash, RecordConflict
UTC = dt.timezone.utc
LEASE_SECONDS = 300
STATES = ('pending', 'running', 'done', 'failed', 'obsolete', 'deferred')
PREFIX = dict(zip(STATES, ('P', 'R', 'D', 'F', 'X', 'H')))

def stamp(value):
    return value.astimezone(UTC).isoformat(timespec='microseconds')

def moment(value):
    return dt.datetime.fromisoformat(value).astimezone(UTC)

class PipelineStore(Protocol):

    def get(self, key):
        ...

    def run(self, keys, update):
        ...

    def scan(self, low, high, limit):
        ...

class MemoryPipelineStore:
    """Explicit local/test backend; never a fallback for Firestore failure."""

    def __init__(self):
        self.values, self.lock = ({}, threading.RLock())

    def get(self, key):
        with self.lock:
            return copy.deepcopy(self.values.get(key))

    def run(self, keys, update):
        with self.lock:
            writes, result = update({k: copy.deepcopy(self.values.get(k)) for k in keys})
            self.values.update(copy.deepcopy(writes))
            return copy.deepcopy(result)

    def scan(self, low, high, limit):
        with self.lock:
            values = sorted((v for v in self.values.values() if low <= v.get('queue_key', '') <= high), key=lambda v: v['queue_key'])
            return copy.deepcopy(values[:limit])

class AnalysisDailyLimit(AnalysisBusy):
    pass

class AnalysisRunGate:

    def __init__(self, store, daily_limit=20, *, now=lambda: dt.datetime.now(UTC)):
        self.store, self.daily_limit, self.now = (store, daily_limit, now)

    def acquire(self, owner):
        now = self.now()
        day = now.astimezone(KST).date().isoformat()
        key = 'usage-' + day

        def reserve(values):
            lock = values['analysis-lease'] or {}
            if lock.get('owner') and moment(lock['expires_at']) > now:
                raise AnalysisBusy('다른 문자 분석이 진행 중입니다. 잠시 후 다시 확인해 주세요.')
            usage = values[key] or {'day': day, 'attempts': 0}
            if usage['attempts'] >= self.daily_limit:
                raise AnalysisDailyLimit('오늘의 문자 분석 한도에 도달했습니다. 대기 기록은 보존되며 다음 날 다시 처리합니다.')
            usage['attempts'] += 1
            return ({key: usage, 'analysis-lease': {'owner': owner, 'started_at': stamp(now), 'expires_at': stamp(now + dt.timedelta(seconds=LEASE_SECONDS))}}, usage)
        try:
            return self.store.run(['analysis-lease', key], reserve)
        except AnalysisBusy:
            raise
        except Exception:
            raise AnalysisUnavailable('분석 한도 저장소를 확인하지 못했습니다. 분석을 시작하지 않았습니다.') from None

    def release(self, owner):

        def release(values):
            lock = values['analysis-lease'] or {}
            return ({'analysis-lease': {}} if lock.get('owner') == owner else {}, None)
        self.store.run(['analysis-lease'], release)

    def status(self):
        now = self.now()
        day = now.astimezone(KST).date().isoformat()
        usage = self.store.get('usage-' + day) or {}
        lock = self.store.get('analysis-lease') or {}
        active = bool(lock.get('owner') and moment(lock['expires_at']) > now)
        used = int(usage.get('attempts', 0))
        return {'day': day, 'attempts': used, 'limit': self.daily_limit, 'remaining': max(0, self.daily_limit - used), 'active': active}

class PipelineLeases:

    def __init__(self, store):
        self.store = store

    def acquire(self, name, owner, now):

        def claim(values):
            current = values[name] or {}
            if current.get('owner') and moment(current['expires_at']) > now:
                return ({}, False)
            return ({name: {'owner': owner, 'expires_at': stamp(now + dt.timedelta(seconds=LEASE_SECONDS))}}, True)
        return self.store.run([name], claim)

    def write(self, name, owner, now, key, value):

        def update(values):
            lock = values[name] or {}
            if lock.get('owner') != owner or moment(lock['expires_at']) <= now:
                raise RecordConflict('수집 실행권이 만료됐습니다.')
            return ({key: value}, None)
        self.store.run([name, key], update)

    def owns(self, name, owner, now):
        lock = self.store.get(name) or {}
        return lock.get('owner') == owner and moment(lock['expires_at']) > now

    def release(self, name, owner):

        def release(values):
            return ({name: {}} if (values[name] or {}).get('owner') == owner else {}, None)
        self.store.run([name], release)

def task_id(record):
    return 'task-' + content_hash({'id': record['id'], 'source_revision': record['source_revision'], 'content_hash': record['content_hash']})

class MessageAnalysisQueue:

    def __init__(self, store):
        self.store = store

    @staticmethod
    def _key(task):
        when = task.get('lease_expires_at') if task['state'] == 'running' else task.get('available_at', task['enqueued_at'])
        return f"{PREFIX[task['state']]}|{when}|{task['enqueued_at']}|{task['id']}"

    @staticmethod
    def _stats(values, old, new):
        counts = copy.deepcopy(values or {s: 0 for s in STATES})
        if old:
            counts[old] = max(0, int(counts.get(old, 0)) - 1)
        counts[new] = int(counts.get(new, 0)) + 1
        return counts

    def enqueue(self, record, now):
        key = task_id(record)

        def add(values):
            if values[key]:
                return ({}, False)
            ready = record.get('analysis_state') == 'completed' and record.get('analysis_source_revision') == record['source_revision']
            failed = record.get('analysis_state') == 'failed'
            state = 'done' if ready else 'failed' if failed else 'pending'
            task = {'id': key, 'record_id': record['id'], 'source_revision': record['source_revision'], 'content_hash': record['content_hash'], 'state': state, 'enqueued_at': stamp(now), 'available_at': stamp(now), 'owner': '', 'attempts': 0, 'detail': 'existing_result' if ready else 'previous_failure' if failed else 'queued'}
            task['queue_key'] = self._key(task)
            return ({key: task, 'queue-counts': self._stats(values['queue-counts'], None, state)}, True)
        return self.store.run([key, 'queue-counts'], add)

    def due(self, now, limit=20):
        return self.store.scan('P|', 'P|' + stamp(now) + '|~', limit)

    def expired(self, now, limit=20):
        return self.store.scan('R|', 'R|' + stamp(now) + '|~', limit)

    def claim(self, key, owner, now):

        def claim(values):
            task = values[key]
            if not task or task['state'] != 'pending' or moment(task['available_at']) > now:
                return ({}, None)
            task.update(state='running', owner=owner, lease_expires_at=stamp(now + dt.timedelta(seconds=LEASE_SECONDS)), attempts=task['attempts'] + 1)
            task['queue_key'] = self._key(task)
            return ({key: task, 'queue-counts': self._stats(values['queue-counts'], 'pending', 'running')}, task)
        return self.store.run([key, 'queue-counts'], claim)

    def finish(self, key, state, now, detail, *, owner=None, delay=0):
        if state not in STATES:
            raise ValueError('queue_state')

        def finish(values):
            task = values[key]
            if not task or (owner is not None and (task['state'] != 'running' or task.get('owner') != owner)):
                return ({}, False)
            old = task['state']
            task.update(state=state, detail=detail, owner='', available_at=stamp(now + dt.timedelta(seconds=delay)), updated_at=stamp(now))
            task['queue_key'] = self._key(task)
            return ({key: task, 'queue-counts': self._stats(values['queue-counts'], old, state)}, True)
        return self.store.run([key, 'queue-counts'], finish)

    def sync_record(self, record, now):
        if record.get('origin') != 'official':
            return
        if record.get('analysis_state') == 'completed' and record.get('analysis_source_revision') == record['source_revision']:
            self.finish(task_id(record), 'done', now, 'stored_result')

    def counts(self):
        values = self.store.get('queue-counts') or {}
        return {s: int(values.get(s, 0)) for s in STATES}
