"""Recheck the six retained authored responses, with all network blocked."""
from pathlib import Path
import datetime as dt
import json
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from scripts.test_support import NetworkGuard
from scripts.evaluate_disaster_messages import check_case, check_notification, server_preview, write_report
from safety_dashboard.adapters.facility_csv import CsvFacilityRepository


def main():
    directory = Path(__file__).resolve().parent
    with NetworkGuard() as guard:
        report = json.loads((directory/'ai-original-results.json').read_text())
        examples = {e['id']: e for e in json.loads((ROOT/'field_web/src/messageExamples.json').read_text())}
        assert len(report['cases']) == 6 and {r['id'] for r in report['cases']} == set(examples)
        catalog = CsvFacilityRepository(ROOT/'facilities_info.csv').snapshot()
        for row in report['cases']:
            row['original_status'] = row['status']
            if not row.get('result'):
                continue
            example, result = examples[row['id']], row['result']
            assert result['input']['input_kind'] == 'example'
            assert all(result['input'][k] == example[k] for k in ('text', 'source', 'issued_at'))
            row['checks'] = {**check_case(example, result, with_places=True),
                            **check_notification(example, result, catalog=catalog)}
            preview = server_preview(example, result, catalog)
            row['server_gate'] = {k: preview[k] for k in ('decision', 'reason', 'dispatch_enabled')}
            row['status'] = 'pass' if all(row['checks'].values()) else 'needs_review'
        report.update(reassessment=True, reassessed_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                      additional_external_calls=0, status='pass' if all(r['status']=='pass' for r in report['cases']) else 'needs_review')
        write_report(report, directory/'ai-rechecked')
        guard.assert_unused()
        print(json.dumps({r['id']:r['status'] for r in report['cases']}))


if __name__ == '__main__':
    main()
