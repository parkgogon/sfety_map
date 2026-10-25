import sys,dataclasses
from pathlib import Path
sys.path.insert(0,'/workspace/sfety_map-improvements')
from safety_dashboard.adapters.facility_csv import CsvFacilityRepository
from safety_dashboard.adapters.nearby_pdf_report import NearbyPdfReportRenderer
from safety_dashboard.application.nearby_report import NearbyReport
from safety_dashboard.domain.models import GeoPoint
from tests.test_nearby_report import facility
root=Path('/workspace/sfety_map-improvements');out=Path('/workspace/improvement-checks/report');out.mkdir(exist_ok=True)
renderer=NearbyPdfReportRenderer(root/'fonts/NotoSansKR.ttf');inventory=CsvFacilityRepository(root/'facilities_info.csv').list_monitored()
for name,radius in [('single',2),('many-real',50)]:
 report=NearbyReport.build(GeoPoint(35.8714,128.6014),'동인청사 인근 검수 기준점','대구광역시 중구 동인동',radius,inventory)
 (out/f'{name}.pdf').write_bytes(renderer.render(report));print(name,len(report.facilities))
rows=[facility(f'f-{i:03}',i,name=f'검수시설 {i:03}') for i in range(195)]
rows[-1]=dataclasses.replace(rows[-1],name='긴시설명'*28+'마지막시설',address='긴 한글 주소 '*400,department='검수 담당부서')
report=NearbyReport.build(GeoPoint(0,0),'합성 195개 시설 페이지 분할 검수','실제 시설·실제 위치가 아닌 검수 입력',1,rows)
(out/'many-synthetic.pdf').write_bytes(renderer.render(report))
