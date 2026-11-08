"""Read deployment metadata only; never read secret versions or dispatch a job."""
import argparse
import json
from pathlib import Path
import subprocess

PROJECT='keco-safety-map'
REGION='asia-northeast3'
SAFE_ENV={'APP_REVISION','APP_MODULE','MESSAGE_REVIEW_STORE','MESSAGE_COLLECTION_ENABLED','MESSAGE_COLLECTION_CONTRACT_VERIFIED',
          'MESSAGE_ANALYSIS_DAILY_LIMIT','MESSAGE_COLLECTION_MAX_PAGES','MESSAGE_COLLECTION_CATCHUP_DAYS',
          'MESSAGE_COLLECTION_INTERVAL_MINUTES','MESSAGE_FEED_REQUEST_LIMIT','MESSAGE_COLLECTION_START_AT',
          'ALERT_AUTOMATION_MODE','ALERT_USER_DELIVERY_MODE','ALERT_INCLUDED_WARNING_TYPES','ALERT_EXCLUDED_WARNING_TYPES'}


def service_summary(value):
    template=value.get('spec',{}).get('template',{})
    spec=template.get('spec',{})
    container=(spec.get('containers') or [{}])[0]
    return {'ready_revision':value.get('status',{}).get('latestReadyRevisionName'),
            'traffic':value.get('status',{}).get('traffic',[]), 'image':container.get('image'),
            'runtime_account':spec.get('serviceAccountName'),
            'execution_environment':template.get('metadata',{}).get('annotations',{}).get('run.googleapis.com/execution-environment'),
            'settings':{e['name']:e['value'] for e in container.get('env',[]) if e.get('name') in SAFE_ENV and 'value' in e},
            'message_secret_versions':{e['name']:e['valueFrom']['secretKeyRef']['key'] for e in container.get('env',[])
                                      if e.get('name') in {'OPENAI_API_KEY','KAKAO_REST_API_KEY','SAFETY_DATA_API_KEY'} and e.get('valueFrom',{}).get('secretKeyRef')}}


def job_summary(value):
    target=value.get('httpTarget',{})
    return {**{k:value[k] for k in ('state','schedule','timeZone','status','lastAttemptTime','scheduleTime','retryConfig') if k in value},
            'uri':target.get('uri'),'oidc_account':target.get('oidcToken',{}).get('serviceAccountEmail'),
            'oidc_audience':target.get('oidcToken',{}).get('audience')}


def read(*args):
    result=subprocess.run(['gcloud',*args,'--project='+PROJECT,'--format=json'],capture_output=True,text=True,timeout=40)
    if result.returncode:raise RuntimeError('pilot_metadata_unavailable')
    return json.loads(result.stdout)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--revision',required=True);args=parser.parse_args()
    result={'services':{},'jobs':{}}
    for name in ('safety-dashboard-api','safety-message-worker','safety-alert-worker'):
        result['services'][name]=service_summary(read('run','services','describe',name,'--region='+REGION))
    for name in ('safety-message-collect','safety-message-analyze','safety-alert-dispatch'):
        result['jobs'][name]=job_summary(read('scheduler','jobs','describe',name,'--location='+REGION))
    policy=read('run','services','get-iam-policy','safety-message-worker','--region='+REGION)
    result['message_worker_public']=any(m in ('allUsers','allAuthenticatedUsers') for b in policy.get('bindings',[]) if b.get('role')=='roles/run.invoker' for m in b.get('members',[]))
    out=Path('release-check');out.mkdir(exist_ok=True)
    (out/'pilot-metadata.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    for name in ('safety-dashboard-api','safety-message-worker'):
        service=result['services'][name]
        assert service['settings']['APP_REVISION']==args.revision
        assert service['settings']['MESSAGE_COLLECTION_ENABLED']=='true'
        assert service['settings']['MESSAGE_COLLECTION_CONTRACT_VERIFIED']=='true'
        assert service['settings']['MESSAGE_COLLECTION_INTERVAL_MINUTES']=='15'
        assert service['settings']['MESSAGE_FEED_REQUEST_LIMIT']=='450'
        assert service['settings']['MESSAGE_ANALYSIS_DAILY_LIMIT']=='20'
        assert service['message_secret_versions']=={'OPENAI_API_KEY':'1','KAKAO_REST_API_KEY':'1','SAFETY_DATA_API_KEY':'1'}
    for name,cron,route in (('safety-message-collect','*/15 * * * *','collect'),('safety-message-analyze','* * * * *','analyze-next'),('safety-alert-dispatch','*/5 * * * *','dispatch')):
        job=result['jobs'][name]
        assert job['state']=='ENABLED' and job['schedule']==cron and job['uri'].endswith('/internal/v1/'+route)
        assert job['oidc_account']=='safety-alert-scheduler@'+PROJECT+'.iam.gserviceaccount.com'
    assert result['services']['safety-alert-worker']['execution_environment']=='gen2'
    assert not result['message_worker_public']
    print('Private worker, fixed versions, bounded pilot settings and three schedules verified. No jobs invoked.')


if __name__=='__main__':main()
