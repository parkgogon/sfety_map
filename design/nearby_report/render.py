"""같은 입력의 기존/개선 PDF를 생성한다. 실제 지도 캡처 파일만 받는다."""
import argparse
import dataclasses
import datetime as dt
import json
from pathlib import Path
import time

from design.nearby_report.cases import ROOT, build_cases
from design.nearby_report.pdf import NearbyPreviewRenderer
from safety_dashboard.adapters.nearby_pdf_report import NearbyPdfReportRenderer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="capture.mjs 출력 폴더")
    parser.add_argument("--cases", default="", help="쉼표로 구분한 시안 ID, 기본 전체")
    args = parser.parse_args()
    records = []
    font = ROOT / "fonts/NotoSansKR.ttf"
    for data, report in build_cases():
        case_id = data["id"]
        if args.cases and case_id not in args.cases.split(","):
            continue
        metadata = json.loads((args.directory / f"{case_id}.json").read_text())
        report = dataclasses.replace(report, generated_at=dt.datetime.fromisoformat(metadata["generated_at"]))
        start = time.perf_counter()
        before = NearbyPdfReportRenderer(font).render(report)
        (args.directory / f"{case_id}-before.pdf").write_bytes(before)
        before_seconds = time.perf_counter() - start
        start = time.perf_counter()
        after = NearbyPreviewRenderer(font).render(report, (args.directory / f"{case_id}.png").read_bytes(), metadata)
        (args.directory / f"{case_id}-after.pdf").write_bytes(after)
        records.append({"id": case_id, "synthetic": data["synthetic"], "facilities": len(report.facilities),
                        "beforePdfMs": round(before_seconds * 1000), "afterPdfMs": round((time.perf_counter() - start) * 1000),
                        "beforeBytes": len(before), "afterBytes": len(after)})
        print(case_id, len(report.facilities), "facilities", records[-1]["afterPdfMs"], "ms")
    (args.directory / "pdf-results.json").write_text(json.dumps(records, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
