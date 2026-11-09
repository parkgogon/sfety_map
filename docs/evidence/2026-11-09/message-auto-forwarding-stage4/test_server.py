"""Local integration fixture. Only fake senders; no credentials or scheduled worker."""
import json
from pathlib import Path
import socket
import sys
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT))
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from safety_dashboard.api.app import create_app
from safety_dashboard.admin.access import AdminAccessSettings,AdminAccessVerifier
from safety_dashboard.application.message_spatial import MessageSpatialService
from safety_dashboard.application.message_automation import MessageAutomationStatus,MessageAutomationSettings
from safety_dashboard.application.message_pipeline import stamp
from safety_dashboard.adapters.telegram import TelegramDeliveryResult
from scripts.test_support import NetworkGuard
from tests.test_message_delivery import DeliveryFixture
from tests.test_message_notification import CATALOG,DIGEST

with NetworkGuard() as guard:
    f=DeliveryFixture()
    f.analyzer.availability.return_value={'configured':True,'place_search_configured':True,'model':'offline-fixture'}
    record,sent=f.ready('browser-sent');f.delivery.run()
    unknown_record,unknown=f.ready('browser-unknown')
    f.staff.results=[TelegramDeliveryResult('unknown',detail='outcome_unknown')]
    f.delivery.run();f.delivery.run()
    _,waiting=f.ready('browser-waiting')
    f.staff.results=[TelegramDeliveryResult('rate_limited',retry_after=60,detail='provider_rate_limit')]
    f.delivery.run()
    f.planner.fallback_enabled=True
    f.planner.failure_check=lambda record:'ai_daily_limit'
    general=f.register('browser-general',message={**f.message,'text':'대구 전역에 폭염이 예상됩니다. 건강관리에 유의하세요.'})
    f.planner.prepare_record(general['id'])
    f.pipeline.values['collection-state']={'start_at':stamp(f.clock[0]),'last_attempt_at':stamp(f.clock[0]),
        'last_success_at':stamp(f.clock[0]),'last_latest_success_at':stamp(f.clock[0]),'last_backfill_success_at':stamp(f.clock[0]),'work':[]}
    f.pipeline.values['usage-'+f.clock[0].date().isoformat()]={'attempts':3}
    guard.assert_unused()

automation=MessageAutomationStatus(MessageAutomationSettings(enabled=True,contract_verified=True,latest_first_enabled=True,
    interval_seconds=300,spend_budget_enabled=True),lambda:f.pipeline,True,now=lambda:f.clock[0])
original_status=f.delivery.status
def fixture_status():
    result=original_status()
    return {**result,'detail':'로컬 검수용 창작 데이터입니다. 전송 응답은 가짜이며 실제 발송은 없습니다. '+result['detail']}
f.delivery.status=fixture_status
app=create_app(admin_access_service=AdminAccessVerifier(AdminAccessSettings(password='local-fixture-password')),
    message_analysis_service=f.analyzer,message_record_service=f.records,
    message_spatial_service=MessageSpatialService(f.records,lambda:(DIGEST,CATALOG)),
    message_notification_preparation_service=f.planner,message_delivery_service=f.delivery,message_automation_service=automation)
app.mount('/assets',StaticFiles(directory=ROOT/'field_web/dist/assets'),name='assets')
@app.get('/')
@app.get('/control/messages')
def frontend():return FileResponse(ROOT/'field_web/dist/index.html')
@app.get('/favicon.ico')
def icon():return FileResponse(ROOT/'field_web/dist/index.html')
@app.get('/__test/state')
def test_state():
    return {'fake_analysis_calls':f.analyzer.analyze.call_count,'fake_staff_requests':len(f.staff.calls),
        'fake_admin_requests':len(f.admin.calls),'human_versions':{r['id']:r['version'] for r in f.records.store.records.values()},
        'review_states':{r['id']:r['review_state'] for r in f.records.store.records.values()},
        'record_id':record['id'],'generation':f.delivery.status()['generation']}

if __name__=='__main__':
    import uvicorn
    with NetworkGuard() as guard:
        sock=socket.socket();sock.bind(('127.0.0.1',0))
        Path('/tmp/notification-stage4-port.txt').write_text(str(sock.getsockname()[1]))
        uvicorn.Server(uvicorn.Config(app,log_level='warning',access_log=False)).run(sockets=[sock])
        guard.assert_unused()
