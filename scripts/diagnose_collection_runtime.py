"""Read two pipeline documents; replay at most two feed reads using memory writes only."""
from __future__ import annotations

import copy
import datetime as dt
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

from safety_dashboard.adapters.disaster_messages import SafetyDataDisasterMessageProvider, DEFAULT_API_URL, parse_disaster_response
from safety_dashboard.adapters.firestore_message_pipeline import FirestoreMessagePipelineStore
from safety_dashboard.application.message_automation import MessageAutomationSettings
from safety_dashboard.application.message_collection import OfficialMessageCollector
from safety_dashboard.application.message_feed_budget import OfficialRequestBudget
from safety_dashboard.application.message_pipeline import MemoryPipelineStore
from safety_dashboard.application.message_records import MemoryRecordStore, MessageRecordService

SOURCE_REVISION = "5f58be1d12a8ac57c0ec365e4eeb86b392fc348c"


def compare_transport(day, page, region, key):
    """Same seven-second deadline, one urllib request, no redirects or raw exports."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_args, **_kwargs):
            return None
    params = {"serviceKey":key, "pageNo":page, "numOfRows":100, "returnType":"json", "crtDt":day.replace('-', '')}
    if region:
        params['rgnNm'] = region
    started=time.monotonic()
    result={'transport':'urllib', 'timeout_seconds':7, 'status':'error'}
    try:
        request=urllib.request.Request(DEFAULT_API_URL+'?'+urllib.parse.urlencode(params),headers={'Accept':'application/json'})
        with urllib.request.build_opener(NoRedirect).open(request,timeout=7) as response:
            raw=response.read(2_000_001)
        if len(raw)>2_000_000:
            raise ValueError('response_cap')
        result.update(status='passed',parsed_rows=len(parse_disaster_response(json.loads(raw))))
    except Exception as error:
        result['error_type']=type(error).__name__
        reason=getattr(error,'reason',None)
        if isinstance(reason,BaseException):result['cause_type']=type(reason).__name__
    result['elapsed_ms']=round((time.monotonic()-started)*1000)
    return result


def partition_summary(part):
    day = part.get("date", "")
    return {"date": day if isinstance(day, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) else None,
            **{k: part[k] for k in ("page", "offset") if type(part.get(k)) is int},
            "verify_head": part.get("verify_head") is True,
            "region_filter_present": bool(part.get("region"))}


def diagnose(*, store=None, provider=None, now=None, compare=compare_transport):
    report = {"status": "passed", "probe_origin": "isolated_collection_replay", "source_revision": SOURCE_REVISION,
              "execution_environment": os.getenv('COLLECTION_PROBE_EXECUTION') if os.getenv('COLLECTION_PROBE_EXECUTION') in {'gen1','gen2'} else 'not_recorded',
              "feed_calls": 0, "max_feed_calls": 2, "model_calls": 0, "messages_sent": 0,
              "production_documents_written": 0, "production_write_access": "not_tested",
              "exceptions": [], "phase": "read_pipeline_metadata"}
    try:
        store = store if store is not None else FirestoreMessagePipelineStore("keco-safety-map")
        state = store.get("collection-state") or {}
        budget = store.get(OfficialRequestBudget.KEY)
        report["production_documents_read"] = 2
        report["partitions_before"] = [partition_summary(p) for p in state.get("work", [])[:12]]
        for key in ("start_at", "last_attempt_at", "last_success_at"):
            raw = state.get(key)
            try:
                report[key] = dt.datetime.fromisoformat(raw).isoformat() if raw else None
            except (TypeError, ValueError):
                report[key] = "invalid_timestamp"
        memory = MemoryPipelineStore()
        memory.values = copy.deepcopy({"collection-state": state, OfficialRequestBudget.KEY: budget})
        records_store = MemoryRecordStore()
        records = MessageRecordService(lambda: records_store, None, storage_mode="memory")
        source = provider if provider is not None else SafetyDataDisasterMessageProvider(os.getenv("SAFETY_DATA_API_KEY", ""),
            gate_factory=lambda: OfficialRequestBudget(memory, 450))

        class BoundedFeed:
            configured = source.configured

            def fetch_page(self, *args):
                if report["feed_calls"] >= 2:
                    raise RuntimeError("probe_call_cap")
                report["feed_calls"] += 1
                return source.fetch_page(*args)

        def trace(frame, event, arg):
            filename = frame.f_code.co_filename.rsplit("/", 1)[-1]
            if event == "exception" and filename in {"message_collection.py", "message_feed_budget.py", "disaster_messages.py"}:
                name = arg[0].__name__
                if name not in {"StopIteration", "GeneratorExit"} and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", name):
                    report["exceptions"].append({"file": filename, "function": frame.f_code.co_name,
                        "line": frame.f_lineno, "type": name})
                    report["exceptions"] = report["exceptions"][-12:]
            return trace

        report["phase"] = "bounded_memory_replay"
        settings = MessageAutomationSettings(enabled=True, contract_verified=True, max_pages=2, scan_seconds=40)
        collector = OfficialMessageCollector(BoundedFeed(), records, memory, settings,
            **({"now": now} if now else {}))
        previous = sys.gettrace()
        try:
            sys.settrace(trace)
            report["replay_result"] = collector.run()
        finally:
            sys.settrace(previous)
        after = memory.get("collection-state") or {}
        report["partitions_after"] = [partition_summary(p) for p in after.get("work", [])[:12]]
        report["memory_records"] = len(records_store.records)
        if report['feed_calls'] < 2 and any(e['type']=='ConnectTimeout' for e in report['exceptions']) and state.get('work'):
            part=state['work'][0]
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}',part.get('date','')) and type(part.get('page')) is int:
                report['feed_calls']+=1
                report['transport_comparison']=compare(part['date'],part['page'],part.get('region'),os.getenv('SAFETY_DATA_API_KEY',''))
        report["phase"] = "finished"
    except Exception as error:
        report.update(status="blocked", error_type=type(error).__name__ if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", type(error).__name__) else "unknown")
    return report


def handler(run=diagnose):
    class Handler(BaseHTTPRequestHandler):
        result = None

        def log_message(self, *_args):
            pass

        def do_POST(self):
            if self.path != "/verify" or self.headers.get("Content-Length", "0") not in ("", "0"):
                self.send_error(400)
                return
            if type(self).result is None:
                type(self).result = run()
            data = json.dumps(type(self).result, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    return Handler


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", int(os.getenv("PORT", "8080"))), handler()).serve_forever()
