import sys,json,os
from pathlib import Path
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[4];sys.path.insert(0,str(ROOT))
from safety_dashboard.adapters.facility_csv import CsvFacilityRepository
from safety_dashboard.application.facility_groups import FacilityGroupCatalog
facilities=CsvFacilityRepository(ROOT/'facilities_info.csv').list_monitored()
catalog=FacilityGroupCatalog.load(ROOT/'safety_dashboard/config/facility_groups.toml')
rows=[]
for f in facilities:
 g=catalog.group_for_type(f.facility_type)
 rows.append(dict(id=f.id,name=f.name,type=f.facility_type,group_id=g.id,group_label=g.label,latitude=f.location.latitude,longitude=f.location.longitude,address=f.address,public_contact='',grade='NONE',grade_label='영향 없음',grade_color='#176B87',meaning='검수용 고정 자료',recommended_action='추가 행동 없음',reasons=[]))
payload=dict(api_version='v1',generated_at='2026-10-25T05:00:00+09:00',status=dict(health='LIVE',fetched_at='2026-10-25T05:00:00+09:00',detail='검수용 고정 자료',zone_health='LIVE',zone_detail='검수용 고정 자료'),policy=dict(version='inspection-fixture',temporary=False),summary=dict(active_warning_count=0,affected_facility_count=0,high_risk_count=0,unassessed_count=0,highest_warning_level=''),groups=[dict(id=g.id,label=g.label,count=sum(f['group_id']==g.id for f in rows)) for g in catalog.groups],warnings=[],warning_zones=dict(type='FeatureCollection',features=[]),facilities=rows,notices=[])
class Handler(SimpleHTTPRequestHandler):
 def __init__(self,*a,**kw):super().__init__(*a,directory=str(ROOT/'field_web/dist'),**kw)
 def log_message(self,*a):pass
 def json(self,d,status=200):
  b=json.dumps(d,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
 def do_GET(self):
  p=urlsplit(self.path).path
  if p.startswith('/api/v1/monitoring'):return self.json(payload)
  if p=='/internal/v1/admin/session':return self.json(dict(authenticated=False))
  if p.startswith(('/api/','/internal/')):return self.json(dict(detail='검수 환경에서 제공하지 않는 조회입니다.'),503)
  if not (ROOT/'field_web/dist'/p.lstrip('/')).is_file():self.path='/index.html'
  super().do_GET()
 def do_POST(self):
  if urlsplit(self.path).path!='/api/v1/reports/nearby.pdf':return self.json(dict(detail='검수에서 금지한 요청'),403)
  from fastapi.testclient import TestClient
  from safety_dashboard.api.app import create_app
  with TestClient(create_app()) as client:
   r=client.post('/api/v1/reports/nearby.pdf',content=self.rfile.read(int(self.headers.get('Content-Length',0))),headers={'Content-Type':'application/json'})
  self.send_response(r.status_code)
  for k in ['content-type','content-disposition','cache-control','x-nearby-facility-count','x-nearby-facility-digest']: 
   if k in r.headers:self.send_header(k,r.headers[k])
  self.send_header('Content-Length',str(len(r.content)));self.end_headers();self.wfile.write(r.content)
print('Local verification server: 127.0.0.1:8765; fixed monitoring fixture; production paths are never proxied',flush=True)
ThreadingHTTPServer(('127.0.0.1',8765),Handler).serve_forever()
