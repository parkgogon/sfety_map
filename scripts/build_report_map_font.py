"""전용 지도 페이지의 고정 문구에 필요한 Noto 글리프만 추출한다."""
from pathlib import Path
from fontTools import subset

ROOT = Path(__file__).resolve().parents[1]
options = subset.Options()
options.recalc_timestamp = False
options.name_IDs = [*options.name_IDs, 13, 14]
font = subset.load_font(str(ROOT / "fonts/NotoSansKR-Regular.ttf"), options)
subsetter = subset.Subsetter(options=options)
subsetter.populate(text=(ROOT / "field_web/report-map.js").read_text() + "0123456789kmN ·↑.– ")
subsetter.subset(font)
for record in font["name"].names:
    if record.nameID in (1, 3, 4, 6, 16):
        font["name"].setName("ReportMapKo", record.nameID, record.platformID, record.platEncID, record.langID)
# 배포되는 폰트 파일 자체에서도 저작권과 OFL 전문을 확인할 수 있게 보존한다.
font["name"].setName((ROOT / "field_web/report-map-font.LICENSE.txt").read_text(), 13, 3, 1, 1033)
subset.save_font(font, str(ROOT / "field_web/report-map-font.ttf"), options)
