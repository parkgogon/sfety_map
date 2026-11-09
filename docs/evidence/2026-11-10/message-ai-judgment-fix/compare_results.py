"""Apply the same current checks to retained authored responses, without network."""
import datetime as dt
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT))
from scripts.test_support import NetworkGuard
from scripts.evaluate_disaster_messages import check_case,check_notification,server_preview
from safety_dashboard.adapters.facility_csv import CsvFacilityRepository
from safety_dashboard.application.message_analysis import MessageAnalysisInput,MessageAnalysisService


def replay_passed_case(case,catalog,model):
    """Re-run retained real tool arguments with fake transport/place data, no new inference."""
    result=case['result']
    class RetainedClient:
        configured=True
        def __init__(self):self.model=model;self.turn=0
        def respond(self,items,tools,instructions,timeout):
            calls=case['tool_exchanges'][self.turn]['calls'];self.turn+=1
            assert len(calls)==1 and calls[0]['name'] in {t['name'] for t in tools}
            return [{'type':'function_call','name':c['name'],'call_id':f'retained-{self.turn}',
                'arguments':json.dumps(c['arguments'],ensure_ascii=False)} for c in calls]
    class RetainedPlaces:
        configured=True
        def search(self,query,timeout):return [p for p in result.get('candidates',[]) if p['query']==query]
    replay=MessageAnalysisService(RetainedClient(),RetainedPlaces(),lambda:catalog[1]).analyze(MessageAnalysisInput.model_validate(result['input']))
    assert replay['analysis']==result['analysis']
    return True


def main():
    directory=Path(__file__).resolve().parent
    examples={r['id']:r for r in json.loads((ROOT/'field_web/src/messageExamples.json').read_text())}
    sources={
        'baseline':directory.parent/'message-delivery-preflight/ai-original-results.json',
    }
    sources.update({p.parent.name.replace('-', '_'):p for p in sorted(directory.glob('attempt-*/results.json'))})
    output={'checked_at':dt.datetime.now(dt.timezone.utc).isoformat(),'additional_external_calls':0,
        'messages_sent':0,'as_of':'example issued_at plus one minute; origin remains example','reports':{}}
    with NetworkGuard() as guard:
        catalog=CsvFacilityRepository(ROOT/'facilities_info.csv').snapshot()
        for label,path in sources.items():
            report=json.loads(path.read_text())
            assert len(report['cases'])==6 and {c['id'] for c in report['cases']}==set(examples)
            rows=[]
            for case in report['cases']:
                row={'id':case['id'],'status':'error','server_decision':'analysis_unavailable'}
                if case.get('result'):
                    result=case['result'];example=examples[case['id']]
                    assert result['input']['input_kind']=='example'
                    assert all(result['input'][key]==example[key] for key in ('text','source','issued_at'))
                    checks={**check_case(example,result,with_places=True),**check_notification(example,result,catalog=catalog)}
                    preview=server_preview(example,result,catalog)
                    row.update(status='pass' if all(checks.values()) else 'needs_review',checks=checks,
                        server_decision=preview['decision'],model_need=result['analysis'].get('notification_assessment',{}).get('need'),
                        server_dispatch_enabled=preview['dispatch_enabled'])
                    if report['status']=='pass':
                        row['retained_agent_path_replayed']=replay_passed_case(case,catalog,report['model'])
                rows.append(row)
            output['reports'][label]={'cases':rows,'passed':sum(r['status']=='pass' for r in rows),
                'settled_usd':report.get('spend_budget',{}).get('daily',{}).get('settled_usd'),
                'reserved_usd':report.get('spend_budget',{}).get('daily',{}).get('reserved_usd')}
        guard.assert_unused()
    (directory/'comparison.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v['passed'] for k,v in output['reports'].items()}))


if __name__=='__main__':main()
