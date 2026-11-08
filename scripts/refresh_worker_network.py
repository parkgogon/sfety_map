"""Recreate only the expected worker revision; preserve all runtime settings/state."""
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess

BASE=['--project=keco-safety-map','--region=asia-northeast3']


def describe():
    result=subprocess.run(['gcloud','run','services','describe','safety-alert-worker',*BASE,'--format=json'],capture_output=True,text=True,timeout=30,check=True)
    return json.loads(result.stdout)


def main():
    expected=os.environ['EXPECTED_WORKER_REVISION'];revision=os.environ['EXPECTED_APP_REVISION']
    if not re.fullmatch(r'safety-alert-worker-[a-z0-9-]+',expected) or not re.fullmatch(r'[a-f0-9]{40}',revision):raise ValueError('expected_revision')
    before=describe();spec=before['spec']['template']['spec']
    container=spec['containers'][0]
    env={item['name']:item.get('value') for item in container.get('env',[])}
    if before['status']['latestReadyRevisionName']!=expected or env.get('APP_REVISION')!=revision:raise ValueError('worker_changed')
    if not all(item.get('revisionName')==expected and item.get('percent')==100 for item in before['status']['traffic']):raise ValueError('unexpected_traffic')
    if not container['image'].endswith('/worker:'+revision):raise ValueError('unexpected_worker_image')
    suffix='net-refresh-'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d%H%M%S')
    subprocess.run(['gcloud','run','services','update','safety-alert-worker',*BASE,'--revision-suffix='+suffix,'--quiet'],capture_output=True,text=True,timeout=240,check=True)
    after=describe()
    result={'checked_at':dt.datetime.now(dt.timezone.utc).isoformat(),'previous_revision':expected,
        'revision':after['status']['latestReadyRevisionName'],'image':container['image'],
        'same_runtime_spec':after['spec']['template']['spec']==spec,'traffic':after['status']['traffic']}
    out=Path('release-check');out.mkdir(exist_ok=True)
    (out/'worker-refresh.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    assert result['same_runtime_spec'] and result['revision']!=expected
    assert all(item.get('revisionName')==result['revision'] and item.get('percent')==100 for item in result['traffic'])
    print('동일 이미지·실행 설정을 유지한 Worker 새 리비전 적용을 확인했습니다.')


if __name__=='__main__':main()
