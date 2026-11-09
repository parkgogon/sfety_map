"""Local-only integration fixture: no provider credentials, model HTTP or sends."""
import copy
import datetime as dt
import json
from pathlib import Path
import socket
import sys
import uuid

ROOT=Path(__file__).resolve().parents[4]
OUT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from safety_dashboard.admin.access import AdminAccessSettings,AdminAccessVerifier
from safety_dashboard.api.app import create_app
from safety_dashboard.application.message_records import MessageRecordService,MemoryRecordStore,RegisterMessage,AnalyzeRecord
from safety_dashboard.application.message_spatial import MessageSpatialService
from safety_dashboard.application.message_notification import notification_preview
from scripts.test_support import NetworkGuard
from tests.test_message_notification import point_case,analyzed_record,assessment,part,call,CATALOG,DIGEST

with NetworkGuard() as fixture_guard:
    first,_=point_case()
    text='대구광역시 달서구 전역이 단수 상태입니다. 시설 운영에 참고하세요.'
    area,_=analyzed_record(text,assessment(text,relevance='area_operations',refs=['FQ1']),
        steps=[call('find_monitored_facilities',{'area_text':'대구광역시 달서구','facility_name':None,'evidence':text})],parts=[part(text,'advisory')])
    text='기온이 내려갑니다. 외출 시 건강관리에 유의하시기 바랍니다.'
    general,_=analyzed_record(text,assessment(text,need='record_only',relevance='general',urgency='reference'),parts=[part(text,'prevention')])
    text='대구광역시 달서구 화재로 인근 주민은 즉시 대피하시기 바랍니다.'
    source,_=analyzed_record(text,assessment(text,relevance='area_operations'),questions=['정확한 발생 지점은 미확인입니다.'])
    text='중앙동 사거리 사고로 도로를 통제합니다. 인근 차량은 우회하세요.'
    unknown,_=analyzed_record(text,assessment(text,relevance='area_operations'),regions=['대구광역시','부산광역시'])
    fixture_guard.assert_unused()
fixtures={'point':first,'area':area,'general':general,'source_only':source,'ambiguous':unknown}

class Analyzer:
    calls=0
    def availability(self):return {'configured':True,'place_search_configured':True,'model':'offline-fixture'}
    def analyze(self,request):
        self.calls+=1
        result=copy.deepcopy(next(row['analysis'] for row in fixtures.values() if row['message']['text']==request.text))
        result['input']=request.model_dump(mode='json')
        return result

analyzer=Analyzer();store=MemoryRecordStore()
records=MessageRecordService(lambda:store,analyzer,storage_mode='memory',facility_digest=lambda:DIGEST)
seed={};previews={}
for label,fixture in fixtures.items():
    message=fixture['message']
    row=records.register_manual(RegisterMessage(registration_key=uuid.uuid4(),input_kind='example',
        text=message['text'],source='자동전파 판단 검수 · 창작 예문',
        issued_at=dt.datetime.now(dt.timezone.utc)-dt.timedelta(minutes=2),recipient_regions=message['recipient_regions']))['record']
    row=records.analyze(row['id'],AnalyzeRecord(expected_version=row['version']))
    seed[label]=row['id']
    previews[label]=notification_preview(row,(DIGEST,CATALOG),base_url='https://example.test')
(OUT/'seed.json').write_text(json.dumps(seed,ensure_ascii=False))
(OUT/'preview-cases.json').write_text(json.dumps(previews,ensure_ascii=False,indent=2))
app=create_app(admin_access_service=AdminAccessVerifier(AdminAccessSettings(password='local-fixture-password')),
    message_analysis_service=analyzer,message_record_service=records,
    message_spatial_service=MessageSpatialService(records,lambda:(DIGEST,CATALOG)))
app.mount('/assets',StaticFiles(directory=ROOT/'field_web/dist/assets'),name='assets')
@app.get('/control/messages')
def frontend():return FileResponse(ROOT/'field_web/dist/index.html')
@app.get('/__test/state')
def fixture_state():
    return {'fake_analyzer_calls':analyzer.calls,'records':{k:{'version':records.get(v)['version'],'review_state':records.get(v)['review_state']} for k,v in seed.items()}}
if __name__=='__main__':
    import uvicorn
    with NetworkGuard() as guard:
        sock=socket.socket();sock.bind(('127.0.0.1',0))
        (OUT/'api-port.txt').write_text(str(sock.getsockname()[1]))
        uvicorn.Server(uvicorn.Config(app,log_level='warning',access_log=False)).run(sockets=[sock])
        guard.assert_unused()
