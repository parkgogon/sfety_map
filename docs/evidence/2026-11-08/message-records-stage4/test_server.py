import copy
import datetime as dt
import json
import sys
from pathlib import Path
sys.path.insert(0, '/workspace/sfety_map')
from safety_dashboard.admin.access import AdminAccessSettings, AdminAccessVerifier
from safety_dashboard.api.app import create_app
from safety_dashboard.application.context_info import KST
from safety_dashboard.application.message_records import MessageRecordService, MemoryRecordStore
from safety_dashboard.application.message_feed import OfficialFeedService
from safety_dashboard.domain.models import DisasterMessage
from scripts.test_support import NetworkGuard

root = Path('/workspace/sfety_map')
report = json.loads((root/'docs/evidence/2026-11-08/disaster-message-ai/places-final-reassessed-results.json').read_text())
fixtures = {row['result']['input']['text']: row['result'] for row in report['cases']}
from tests.test_message_relations import analysis as scripted_analysis
original_text = '가람교와 푸른교는 침수 우려로 오늘 10시부터 통제합니다. 우회하여 주시기 바랍니다.'
followup_text = '오늘 15시 가람교 통제는 해제하였으나 푸른교 통제는 유지됩니다. 구간별로 확인 바랍니다.'
for text, released in [(original_text, False), (followup_text, True)]:
    value = copy.deepcopy(report['cases'][0]['result'])
    value.update(scripted_analysis(released))
    value.update(model='local-scripted-fixture', model_calls=0, elapsed_ms=0, trace=[], nearby=[], review_required=True)
    value['analysis']['summary'] = '창작 검수: 가람교 해제·푸른교 통제 유지 구간별 확인' if released else '창작 검수: 두 교량의 통제 안내'
    for index, part in enumerate(value['analysis']['parts']):
        part['evidence'] = ('오늘 15시 가람교 통제는 해제하였으나' if index == 0 else '푸른교 통제는 유지됩니다.') if released else '가람교와 푸른교는 침수 우려로 오늘 10시부터 통제합니다.'
        part['starts_at'] = None if released else '2026-11-08T10:00:00+09:00'
        part.update(description=part['evidence'], time_text='오늘 15시' if released else '오늘 10시')
    fixtures[text] = value
class Analyzer:
    def availability(self): return {'configured': True, 'place_search_configured': True, 'model': 'local-fixture'}
    def analyze(self, request):
        result = copy.deepcopy(fixtures[request.text]); result['input'] = request.model_dump(mode='json')
        return result
class Provider:
    configured = True
    def fetch_page(self, region, date, page, size):
        text = report['cases'][1]['result']['input']['text']
        row = DisasterMessage('local-fixture-SN-1', dt.datetime.combine(date, dt.time(10,10), KST), '안전안내', '화재', text, ('대구광역시 달서구',))
        return {'messages': [row], 'has_more': page < 3, 'skipped': 0}
analyzer = Analyzer()
records = MessageRecordService(MemoryRecordStore, analyzer, storage_mode='memory', facility_digest=lambda: 'fixture-csv')
app = create_app(admin_access_service=AdminAccessVerifier(AdminAccessSettings(password='local-fixture-password')),
                 message_analysis_service=analyzer, message_record_service=records,
                 message_feed_service=OfficialFeedService(Provider(), 'local-fixture-password'))
if __name__ == '__main__':
    import uvicorn
    import socket
    with NetworkGuard() as guard:
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        Path('/workspace/analysis/contest/message-records-stage4/api-port.txt').write_text(str(port))
        uvicorn.Server(uvicorn.Config(app, log_level='warning', access_log=False)).run(sockets=[sock])
        guard.assert_unused()
