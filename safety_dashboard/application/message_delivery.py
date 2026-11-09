"""Official-message delivery outbox. Preview jobs and human review stay separate."""
from __future__ import annotations

import datetime as dt
import re
import uuid

from safety_dashboard.application.message_analysis import AnalysisUnavailable
from safety_dashboard.application.message_notification_jobs import (
    CONFIG_KEY, NOTIFIABLE, head_key, job_key, source_key, record_basis, preview_hash,
)
from safety_dashboard.application.message_pipeline import UTC, moment, stamp
from safety_dashboard.application.message_records import RecordConflict, content_hash

CONTROL = "message-delivery-control"
HEARTBEAT = "message-delivery-worker"
MAX_ATTEMPTS = 3


def delivery_key(job_id):
    return "message-delivery-"+content_hash(job_id)


def history_key(identifier):
    return "message-delivery-history-"+identifier


def pending_key(destination, when, identifier):
    return ("MO|" if destination == "staff_group" else "MA|")+when+"|"+identifier


def history(value):
    allowed = ("id", "record_id", "source_revision", "destination", "state", "detail", "preview_text",
               "created_at", "updated_at", "attempts", "message_id", "available_at", "resolved_at", "resolution")
    return {**{k: value.get(k) for k in allowed}, "queue_key": "MH|"+value["updated_at"]+"|"+value["id"]}


class MessageDelivery:
    def __init__(self, preparation, senders, *, enabled=False, ready=True, binding="", revision="local",
                 now=lambda: dt.datetime.now(UTC)):
        self.preparation, self.senders = preparation, senders
        self.enabled, self.ready, self.binding, self.revision, self.now = enabled, ready, binding, revision, now

    def _configured(self):
        return bool(self.ready and self.binding and all(self.senders.get(name) and self.senders[name].configured
                                                       for name in ("staff_group", "admin_group")))

    def _active(self, control):
        return bool(self.enabled and self.preparation.enabled and self._configured() and control
                    and control.get("mode") == "active" and control.get("revision") == self.revision
                    and control.get("binding") == self.binding)

    def status(self):
        base = {"deployment_enabled": self.enabled, "can_activate": bool(self.enabled and self.preparation.enabled and self._configured()),
                "active": False, "state": "disabled", "generation": None, "started_at": None,
                "detail": "자동전파 운영 연결이 비활성입니다. 저장된 판단과 전파 준비는 발송을 뜻하지 않습니다.", "worker": None}
        if not self.preparation.enabled:
            return base
        store = self.preparation.store_factory()
        control = store.get(CONTROL) or {}
        result = {**base, "generation": control.get("generation"), "started_at": control.get("started_at"), "worker": store.get(HEARTBEAT)}
        if not self.enabled:
            return result
        if not self._configured():
            return {**result, "state": "needs_configuration", "detail": "공식 수집·비용 제한·직원방/관리자방 연결 설정을 확인해야 합니다."}
        if self._active(control):
            worker = result["worker"] or {}
            reference = worker.get("at") if worker.get("revision") == self.revision else control["started_at"]
            stale = (self.now()-moment(reference or control["started_at"])).total_seconds() > 180
            stale = stale or (worker.get('generation') == control['generation'] and worker.get('state') != 'active')
            return {**result, "state": "active", "active": True, "worker_stale": stale,
                    "detail": "공식 문자 판단 후 기존 직원 단체방에 자동전파합니다. 건별 승인은 필요하지 않습니다."}
        if control.get("mode") == "paused":
            return {**result, "state": "paused", "detail": "자동전파가 일시정지되어 있습니다. 다시 시작하면 그 시각 이후의 새 문자부터 처리합니다."}
        return {**result, "state": "ready", "detail": "현재 배포에서 자동전파를 시작할 수 있습니다. 기존 미리보기·시작 전 문자는 보내지 않습니다."}

    def configure(self, action, expected_generation):
        if not self.preparation.enabled:
            raise AnalysisUnavailable("알림 준비 기능이 연결되지 않았습니다.")
        if action == "start" and not (self.enabled and self._configured()):
            raise AnalysisUnavailable("운영 연결과 예산 설정을 확인한 뒤 전파를 시작할 수 있습니다.")
        if action not in {"start", "pause"}:
            raise ValueError("delivery_action")
        if action == "start":
            self.preparation.activate()
        store, now = self.preparation.store_factory(), self.now()
        generation = uuid.uuid4().hex
        event = "message-delivery-control-event-"+generation

        def change(values):
            old = values[CONTROL] or {}
            if old.get("generation") != expected_generation:
                raise RecordConflict("전파 설정이 변경됐습니다. 현재 상태를 다시 불러와 주세요.")
            value = {"mode": "active" if action == "start" else "paused", "generation": generation,
                     "revision": self.revision, "binding": self.binding, "updated_at": stamp(now),
                     "started_at": stamp(now) if action == "start" else old.get("started_at")}
            return {CONTROL: value, event: {"action": action, "at": stamp(now), "generation": generation,
                                           "revision": self.revision}}, None
        store.run([CONTROL, event], change)
        return self.status()

    def reconsider(self, record_id, expected_version, expected_generation):
        """Explicitly rearm only a never-attempted source with newly verified evidence."""
        if not self.enabled or not self.preparation.enabled:
            raise AnalysisUnavailable("자동전파 운영 연결이 비활성입니다.")
        store, now = self.preparation.store_factory(), self.now()
        record = self.preparation.records.get(record_id)
        if record['version'] != expected_version:
            raise RecordConflict("현재 원문과 판단을 다시 불러와 주세요.")
        jid, hid, slot = job_key(record), head_key(record_id), source_key(record)
        old_job, old_head = store.get(jid), store.get(hid)
        catalog = self.preparation.catalog()
        basis = record_basis(record, catalog[0], self.preparation.policy_version, self.preparation.base_url)
        preview = self.preparation._preview(record, catalog, old_job)
        semantic = preview_hash(preview)
        did = 'notification-decision-'+content_hash({'source':slot,'basis':basis,'preview':semantic,'scope':'eligible'})
        oid, event = delivery_key(jid), 'message-delivery-reconsider-'+uuid.uuid4().hex
        keys = [CONTROL, CONFIG_KEY, jid, hid, slot, did, oid, history_key(oid), event]
        def rearm(current, values):
            control, existing = values[CONTROL], values[oid]
            if (not self._active(control) or control['generation'] != expected_generation or not current
                    or current['version'] != expected_version or values[jid] != old_job or values[hid] != old_head):
                raise RecordConflict("전파 설정 또는 판단이 바뀌었습니다. 다시 확인해 주세요.")
            if existing and existing['attempts']:
                raise RecordConflict("이미 전파를 요청한 원문입니다. 자동 재등록하지 않으며 수신 결과를 별도로 확인해 주세요.")
            issued = current['message'].get('issued_at')
            if (current.get('origin') != 'official' or not issued or moment(issued) < moment(control['started_at'])
                    or preview['decision'] not in NOTIFIABLE or not preview.get('preview_text')):
                raise RecordConflict("현재 전달 가능한 새 공식 문자와 근거가 필요합니다.")
            prep_config = values[CONFIG_KEY]
            if not prep_config or moment(issued) < moment(prep_config['started_at']):
                raise RecordConflict("전파 준비 시작 전 원문입니다.")
            job = {'id':jid,'record_id':record_id,'source_key':slot,'source_revision':current['source_revision'],
                   'content_hash':current['content_hash'],'basis_hash':basis,'preview_hash':semantic,'decision_id':did,
                   'phase':'preview','dispatch_enabled':False,'destination':'staff_group','state':'pending',
                   'detail':'manually_reconsidered','snapshot':preview,'delivery_generation':control['generation'],
                   'preparation_started_at':prep_config['started_at'],'created_at':stamp(now),'updated_at':stamp(now),
                   'checked_at':stamp(now),'queue_key':'NJ|'+stamp(now)+'|'+jid}
            source = values[slot] or {'record_id':record_id,'source_revision':current['source_revision'],'content_hash':current['content_hash'],'created_at':stamp(now)}
            writes = {jid:job,slot:{**source,'finalized':True,'manual_reconsiderations':source.get('manual_reconsiderations',0)+1},
                      hid:{'record_id':record_id,'source_key':slot,'decision_id':did,'basis_hash':basis,'job_id':jid,'state':'pending',
                           'updated_at':stamp(now),'queue_key':'NH|'+stamp(now)+'|'+hid},
                      event:{'record_id':record_id,'source_key':slot,'action':'reconsider','at':stamp(now),'basis_hash':basis}}
            if not values[did]:writes[did]={'id':did,'record_id':record_id,'source_key':slot,'basis_hash':basis,'scope':'eligible','snapshot':preview,'created_at':stamp(now)}
            if existing:
                queued = self._new_outbox(oid,'staff_group',preview['preview_text'],control,job_id=jid,record_id=record_id,
                                          source_revision=current['source_revision'],basis_hash=basis)
                writes.update({oid:queued,history_key(oid):history(queued)})
            return writes, False, {'state':'pending','sent':False}
        return store.run_record(record_id,keys,rearm)

    def _valid_staff(self, record, job, head, prep_config, control, catalog, basis, preview):
        return bool(record and job and job.get("state") == "pending" and job.get("phase") == "preview"
            and job.get("dispatch_enabled") is False and job.get("destination") == "staff_group"
            and record.get("origin") == "official" and self._active(control)
            and job.get("delivery_generation") == control.get("generation")
            and prep_config and prep_config.get("started_at") == job.get("preparation_started_at")
            and job["created_at"] >= control["started_at"]
            and record["message"].get("issued_at") and moment(record["message"]["issued_at"]) >= moment(control["started_at"])
            and head and head.get("job_id") == job["id"] and head.get("decision_id") == job["decision_id"]
            and record_basis(record, catalog[0], self.preparation.policy_version, self.preparation.base_url) == basis == job["basis_hash"]
            and preview["decision"] in NOTIFIABLE and preview.get("preview_text")
            and preview_hash(preview) == job["preview_hash"])

    def _new_outbox(self, identifier, destination, text, control, **extra):
        now = stamp(self.now())
        return {"id": identifier, "destination": destination, "preview_text": text, "state": "pending",
                "detail": "queued", "attempts": 0, "generation": control["generation"], "created_at": now,
                "updated_at": now, "available_at": now, "queue_key": pending_key(destination, now, identifier), **extra}

    def consider_staff(self, job_id):
        store = self.preparation.store_factory()
        job = store.get(job_id)
        if not job:
            return
        record = self.preparation.records.get(job["record_id"])
        catalog = self.preparation.catalog()
        basis = record_basis(record, catalog[0], self.preparation.policy_version, self.preparation.base_url)
        preview = self.preparation._preview(record, catalog, job)
        identifier, hid = delivery_key(job_id), head_key(record["id"])

        def prepare(current, values):
            if values[identifier] or not current or current["version"] != record["version"] or values[job_id] != job:
                return {}, False, None
            if not self._valid_staff(current, job, values[hid], values[CONFIG_KEY], values[CONTROL], catalog, basis, preview):
                return {}, False, None
            value = self._new_outbox(identifier, "staff_group", preview["preview_text"], values[CONTROL],
                job_id=job_id, record_id=record["id"], source_revision=record["source_revision"], basis_hash=basis)
            return {identifier: value, history_key(identifier): history(value)}, False, None
        store.run_record(record["id"], [identifier, history_key(identifier), job_id, hid, CONFIG_KEY, CONTROL], prepare)

    def consider_incident(self, incident):
        store = self.preparation.store_factory()
        identifier = delivery_key(incident["id"])
        def prepare(values):
            control, current = values[CONTROL], values[incident["id"]]
            if (values[identifier] or not self._active(control) or not current
                    or current.get("latest_new_source_generation") != control.get("generation")
                    or current.get("latest_new_source_at", current["created_at"]) < control["started_at"]):
                return {}, None
            text = current["preview_text"]+f"\n보관된 같은 사유 원문 {current['source_count']}건(시작 전 기록 포함). 동일 사유는 묶어 안내합니다."
            value = self._new_outbox(identifier, "admin_group", text, control, incident_id=incident["id"], record_id=None)
            return {identifier: value, history_key(identifier): history(value)}, None
        store.run([CONTROL, incident["id"], identifier, history_key(identifier)], prepare)

    def _claim(self, identifier):
        store = self.preparation.store_factory()
        outbox = store.get(identifier)
        if not outbox or outbox["state"] not in {"pending", "waiting"}:
            return None
        now = self.now()
        if moment(outbox["available_at"]) > now:
            return None
        job = record = catalog = basis = preview = None
        extra = []
        if outbox["destination"] == "staff_group":
            record = self.preparation.records.get(outbox["record_id"])
            job = store.get(outbox["job_id"])
            catalog = self.preparation.catalog()
            basis = record_basis(record, catalog[0], self.preparation.policy_version, self.preparation.base_url)
            preview = self.preparation._preview(record, catalog, job)
            extra = [outbox["job_id"], head_key(record["id"]), CONFIG_KEY]
        attempt_id = "message-delivery-attempt-"+uuid.uuid4().hex
        keys = [CONTROL, identifier, history_key(identifier), attempt_id, *extra]
        def claim(current, values):
            control = values[CONTROL]
            if values[identifier] != outbox:
                return {}, False, None
            valid = self._active(control) and control["generation"] == outbox["generation"]
            if record:
                valid = valid and bool(current and current["version"] == record["version"] and values[outbox["job_id"]] == job
                    and self._valid_staff(current, job, values[head_key(record["id"])], values[CONFIG_KEY], control, catalog, basis, preview))
            if not valid:
                value = {**outbox, "state": "cancelled", "detail": "source_or_activation_changed", "updated_at": stamp(now), "queue_key": "MC|"+stamp(now)+"|"+identifier}
                return {identifier: value, history_key(identifier): history(value)}, False, None
            value = {**outbox, "state": "sending", "detail": "request_started", "attempt_id": attempt_id,
                     "attempts": outbox["attempts"]+1, "updated_at": stamp(now), "expires_at": stamp(now+dt.timedelta(seconds=300)),
                     "queue_key": "MR|"+stamp(now+dt.timedelta(seconds=300))+"|"+identifier}
            attempt = {"id": attempt_id, "delivery_id": identifier, "state": "sending", "started_at": stamp(now),
                       "destination": outbox["destination"], "source_revision": outbox.get("source_revision")}
            return {identifier: value, history_key(identifier): history(value), attempt_id: attempt}, False, value
        if record:
            return store.run_record(record["id"], keys, claim)
        def claim_admin(values):
            writes, _, result = claim(None, values)
            return writes, result
        return store.run(keys, claim_admin)

    def _finish(self, claimed, state, detail, *, message_id=None, retry_after=None):
        store, now = self.preparation.store_factory(), self.now()
        identifier, attempt_id = claimed["id"], claimed["attempt_id"]
        incident_id = "notification-incident-"+now.astimezone(dt.timezone(dt.timedelta(hours=9))).date().isoformat()+"-delivery_"+state
        marker = incident_id+"-"+content_hash(identifier)
        alert = claimed["destination"] == "staff_group" and state in {"unknown", "rejected"}
        keys = [identifier, history_key(identifier), attempt_id, *([incident_id, marker] if alert else [])]
        def finish(values):
            current = values[identifier]
            if not current or current.get("attempt_id") != attempt_id or current["state"] not in {"sending", "unknown"}:
                return {}, None
            value = {**current, "state": state, "detail": detail, "message_id": message_id, "updated_at": stamp(now),
                     "queue_key": "MT|"+stamp(now)+"|"+identifier}
            if state == "waiting":
                value["available_at"] = stamp(now+dt.timedelta(seconds=max(60, retry_after or 60)))
                value["queue_key"] = pending_key(value["destination"],value["available_at"],identifier)
            attempt = {**values[attempt_id], "state": state, "detail": detail, "message_id": message_id, "finished_at": stamp(now)}
            writes = {identifier: value, history_key(identifier): history(value), attempt_id: attempt}
            if alert and not values[marker]:
                incident = values[incident_id] or {"id": incident_id, "category": "delivery_"+state, "source_count": 0,
                    "created_at": stamp(now), "destination": "admin_group", "phase": "preview", "dispatch_enabled": False}
                writes[incident_id] = {**incident, "source_count": incident["source_count"]+1, "updated_at": stamp(now),
                    "latest_new_source_at": stamp(now),
                    "latest_new_source_generation": claimed["generation"],
                    "queue_key": "NE|"+stamp(now)+"|"+incident_id,
                    "preview_text": "[재난문자 전파 확인 필요]\n직원방 전파의 "+("수신 결과가 미상입니다. 중복을 피하려고 자동 재발송하지 않습니다." if state == "unknown" else "요청이 거절되었습니다. 연결 설정과 전파 이력을 확인해 주세요.")}
                writes[marker] = {"delivery_id": identifier}
            return writes, None
        store.run(keys, finish)

    def run(self):
        if not self.enabled or not self.preparation.enabled:
            return {"state": "disabled", "sent": 0}
        store = self.preparation.store_factory()
        # Recover in-flight attempts even when paused. No expired attempt is resent.
        for item in store.scan("MR|", "MR|"+stamp(self.now())+"|~", 20):
            self._finish(item, "unknown", "worker_interrupted")
        control = store.get(CONTROL) or {}
        active = self._active(control)
        heartbeat = {"at": stamp(self.now()), "revision": self.revision, "generation": control.get('generation'),
                     "state": "active" if active else "paused_or_unconfigured"}
        store.run([HEARTBEAT], lambda values: ({HEARTBEAT: heartbeat}, None))
        if not active:
            return {"state": "paused", "sent": 0}
        for job in store.scan("NJ|", "NJ|~", 50):
            self.consider_staff(job["id"])
        for incident in store.scan("NE|", "NE|~", 20, reverse=True):
            self.consider_incident(incident)
        processed, sent, destinations = 0, 0, set()
        candidates = [item for prefix in ("MO|", "MA|") for item in store.scan(prefix, prefix+stamp(self.now())+"|~", 20)]
        for item in candidates:
            if item["destination"] in destinations:
                continue
            claimed = self._claim(item["id"])
            if not claimed:
                continue
            destinations.add(claimed["destination"])
            # Claim is the durable beginning of a request; a pause cannot recall an in-flight request.
            try:
                receipt = self.senders[claimed["destination"]].send_once(claimed["preview_text"])
                state = receipt.state
                if state == "rate_limited":
                    state = "waiting" if claimed["attempts"] < MAX_ATTEMPTS else "rejected"
                if state not in {"sent", "rejected", "waiting", "unknown"} or state == "sent" and not receipt.message_id:
                    state = "unknown"
                self._finish(claimed, state, receipt.detail, message_id=receipt.message_id if state == "sent" else None,
                             retry_after=receipt.retry_after)
            except Exception:
                # Includes a lost settlement acknowledgement. Never send again in this run.
                # The persisted sending lease recovers to unknown if storage is unavailable.
                raise AnalysisUnavailable("전파 결과 저장을 확인하지 못했습니다. 자동 재발송하지 않으며 이력을 확인해야 합니다.") from None
            processed += 1
            sent += state == "sent"
        return {"state": "active", "processed": processed, "sent": sent}

    def page(self, kind, before=None, limit=20):
        if not self.preparation.enabled:
            return {"items": [], "next_cursor": None}
        prefix = {"deliveries": "MH|", "decisions": "NH|", "exceptions": "NE|"}[kind]
        if before and (not before.startswith(prefix) or len(before) > 240 or not re.fullmatch(r"[A-Za-z0-9_|:.+\-]+", before)):
            raise ValueError("delivery_cursor")
        store = self.preparation.store_factory()
        rows = store.scan(prefix, before or prefix+"~", limit+2, reverse=True)
        rows = [r for r in rows if r["queue_key"] != before]
        page = rows[:limit]
        if kind == "decisions":
            items = []
            for row in page:
                decision = store.get(row['decision_id'])
                jid = 'notification-job-'+row['source_key'].removeprefix('notification-source-')
                outbox = store.get(delivery_key(jid))
                can_reconsider = row['state'] in {'reconsideration_required','invalidated'} and decision['snapshot']['decision'] in NOTIFIABLE and not (outbox and outbox['attempts'])
                items.append({**row,'decision':decision,'can_reconsider':can_reconsider,'delivery_state':outbox.get('state') if outbox else None})
            page = items
        return {"items": page, "next_cursor": page[-1]["queue_key"] if len(rows) > limit else None}

    def acknowledge(self, identifier, resolution):
        if resolution not in {"confirmed_received", "handled_separately"}:
            raise ValueError("delivery_resolution")
        store, now = self.preparation.store_factory(), self.now()
        def acknowledge(values):
            current = values[identifier]
            if not current or current["state"] not in {"unknown", "rejected"}:
                raise RecordConflict("확인이 필요한 전파 이력을 다시 불러와 주세요.")
            if current.get("resolved_at"):
                return {}, None
            value = {**current, "resolution": resolution, "resolved_at": stamp(now), "updated_at": stamp(now)}
            return {identifier: value, history_key(identifier): history(value)}, None
        store.run([identifier, history_key(identifier)], acknowledge)
        return {"state": "acknowledged", "resent": False}
