"""Bounded private runtime diagnostics. No source payloads, keys, AI or delivery exports."""
from __future__ import annotations
import collections
import datetime as dt
from http.server import BaseHTTPRequestHandler,HTTPServer
import json
import os
import socket
import ssl
import time
from contextlib import contextmanager
import urllib3.util.connection

import requests
from safety_dashboard.adapters.disaster_messages import (DEFAULT_API_URL,parse_disaster_response,_find_message_rows,_find_total_count,_parse_time,_value)
from safety_dashboard.adapters.firestore_message_pipeline import FirestoreMessagePipelineStore
from safety_dashboard.adapters.firestore_alerts import FirestoreAlertStore
from safety_dashboard.adapters.kma import WARNING_URL,validate_warning_response
from safety_dashboard.application.message_collection import recipient_scope
from safety_dashboard.application.message_analysis import REGION_ALIASES
from safety_dashboard.application.message_feed_budget import OfficialRequestBudget
from safety_dashboard.application.message_records import MessageSource
from safety_dashboard.application.context_info import KST


@contextmanager
def trace_connection(stages):
    connect=urllib3.util.connection.create_connection;wrap=ssl.SSLContext.wrap_socket
    def traced(name,original,*args,**kwargs):
        start=time.monotonic();item={'stage':name}
        try:
            value=original(*args,**kwargs);item['success']=True;return value
        except Exception as error:
            item.update(success=False,**exception_summary(error));raise
        finally:
            item['elapsed_ms']=round((time.monotonic()-start)*1000);stages.append(item)
    urllib3.util.connection.create_connection=lambda *a,**kw:traced('tcp',connect,*a,**kw)
    ssl.SSLContext.wrap_socket=lambda *a,**kw:traced('tls',wrap,*a,**kw)
    try:yield
    finally:urllib3.util.connection.create_connection=connect;ssl.SSLContext.wrap_socket=wrap


def exception_summary(error):
    seen=set();queue=[error];classes=[];codes=[]
    while queue and len(seen)<12:
        value=queue.pop(0)
        if not isinstance(value,BaseException) or id(value) in seen:continue
        seen.add(id(value));classes.append(type(value).__name__)
        if isinstance(getattr(value,'errno',None),int):codes.append(value.errno)
        queue.extend([value.__cause__,value.__context__,getattr(value,'reason',None)])
        queue.extend(a for a in value.args if isinstance(a,BaseException))
    return {'exception_types':list(dict.fromkeys(classes)),'errno':list(dict.fromkeys(codes))}


def page_summary(payload,day,today,start_at):
    rows=_find_message_rows(payload) or []
    data=parse_disaster_response(payload)
    reasons=collections.Counter();samples=[]
    for raw in rows:
        try:_parse_time(_value(raw,'CRT_DT','crtDt','crt_dt'))
        except (KeyError,ValueError,TypeError):reasons['parse_time']+=1
    for row in data:
        row_day=row.created_at.astimezone(KST).date();scope=recipient_scope(row.regions)
        reason='outside_target'
        if not day<=row_day<=today:reason='outside_query_date'
        elif scope is None:reason='unrecognized_recipient'
        elif scope:
            try:MessageSource(text=row.content,source='행정안전부 공개 재난문자 API',issued_at=row.created_at,recipient_regions=[r for r in row.regions if r!='-']).canonical()
            except ValueError:reason='source_validation'
            else:reason='eligible'
        reasons[reason]+=1
        if reason in ('outside_query_date','unrecognized_recipient','source_validation'):
            before=bool(start_at and row.created_at<dt.datetime.fromisoformat(start_at))
            reasons['skipped_before_start' if before else 'skipped_since_start']+=1
            if len(samples)<8:
                samples.append({'reason':reason,'issued_date':row_day.isoformat(),'before_start':before,
                    'text_length':len(row.content),'recipient_count':len(row.regions),
                    'known_province_prefixes':sorted({p for p in REGION_ALIASES for r in row.regions if r.startswith(p)}),
                    'recipient_shape':{'empty_or_dash':any(r in ('','-') for r in row.regions),'underscore':any('_' in r for r in row.regions),
                        'brackets':any(any(c in r for c in '[]()') for r in row.regions),'newline':any('\n' in r for r in row.regions),
                        'known_province_anywhere':any(p in r for p in REGION_ALIASES for r in row.regions)}})
    return {'query_date':day.isoformat(),'rows':len(rows),'parsed':len(data),'parser_skipped':len(rows)-len(data),
            'total_count':_find_total_count(payload),'reasons':dict(reasons),'skipped_shapes':samples}


def diagnose():
    result={'status':'passed','probe_origin':'cloud_run_runtime','feed_calls':0,'kma_calls':0,'model_calls':0,'messages_sent':0,'source_records_written':0}
    store=FirestoreMessagePipelineStore('keco-safety-map')
    state=store.get('collection-state') or {}
    result['collection_state']={k:state.get(k) for k in ('start_at','last_attempt_at','last_success_at','cycle_skipped','coverage_gap','last_error')}
    result['remaining_partitions']=len(state.get('work',[]))
    try:
        existing=FirestoreAlertStore('keco-safety-map').notification_status()
        result['kma_state']={k:v.isoformat() if isinstance(v,dt.datetime) else v for k,v in existing.items()
            if k in ('kma_health','last_run_at','kma_failure_category','kma_failure_summary','kma_failure_evidence','kma_last_success_at','kma_consecutive_errors')}
    except Exception as error:result['kma_state']={'error':exception_summary(error)}
    today=dt.datetime.now(KST).date();result['feed_pages']=[]
    # Original two dates plus the current Korean day; three reads maximum.
    days=list(dict.fromkeys([dt.date(2026,11,8),dt.date(2026,11,7),today]))
    for day in days:
        entry={'query_date':day.isoformat(),'stages':[]}
        try:
            OfficialRequestBudget(store,450).reserve();result['feed_calls']+=1
            with trace_connection(entry['stages']):
                response=requests.get(DEFAULT_API_URL,params={'serviceKey':os.environ['SAFETY_DATA_API_KEY'],'returnType':'json','crtDt':day.strftime('%Y%m%d'),'pageNo':1,'numOfRows':100},timeout=(7,12),allow_redirects=False)
            response.raise_for_status()
            if not 200<=response.status_code<300:raise ValueError('non_success')
            entry.update(page_summary(response.json(),day,today,state.get('start_at')))
        except Exception as error:entry['error']=exception_summary(error)
        result['feed_pages'].append(entry)
    result['kma_requests']=[]
    try:
        addresses=socket.getaddrinfo('apihub.kma.go.kr',443,type=socket.SOCK_STREAM)
        result['kma_dns']={'families':sorted({a[0].name for a in addresses}),'addresses':sorted({a[4][0] for a in addresses})}
    except Exception as error:result['kma_dns']=exception_summary(error)
    for read_timeout in (7,20,7):
        started=time.monotonic();entry={'read_timeout_seconds':read_timeout,'stages':[]}
        try:
            result['kma_calls']+=1
            with trace_connection(entry['stages']):
                response=requests.get(WARNING_URL,params={'fe':'f','tm':dt.datetime.now(KST).strftime('%Y%m%d%H%M'),'disp':'0','help':'0','authKey':os.environ['KMA_API_KEY']},timeout=(7,read_timeout),allow_redirects=False)
            entry['http_status']=response.status_code
            if response.status_code==200:
                try:validate_warning_response(response.text);entry['valid_warning_format']=True
                except ValueError:entry['valid_warning_format']=False
            entry['redirect']=300<=response.status_code<400
        except Exception as error:entry.update(exception_summary(error))
        entry['elapsed_ms']=round((time.monotonic()-started)*1000);result['kma_requests'].append(entry)
    return result


def handler(run=diagnose):
    class Handler(BaseHTTPRequestHandler):
        result=None
        def log_message(self,*args):pass
        def do_POST(self):
            if self.path!='/verify' or self.headers.get('Content-Length','0') not in ('','0'):self.send_error(400);return
            if type(self).result is None:
                try:type(self).result=run()
                except Exception as error:type(self).result={'status':'blocked','error':exception_summary(error)}
            data=json.dumps(type(self).result,ensure_ascii=False).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    return Handler


if __name__=='__main__':HTTPServer(('0.0.0.0',int(os.getenv('PORT','8080'))),handler()).serve_forever()
