import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect

OUT=Path(__file__).parent
BASE='http://127.0.0.1:'+(OUT/'api-port.txt').read_text().strip()
seed=json.loads((OUT/'seed.json').read_text())
labels={'point':'요약 전파 추천','area':'요약 전파 추천','general':'기록 추천','source_only':'원문 중심 전파 추천','ambiguous':'판단 확인 필요'}
errors=[];unexpected=[];requests=[];checks=[]
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox','--disable-dev-shm-usage'])
    context=browser.new_context()
    page=context.new_page()
    page.add_init_script(path=str(OUT/'fake_sdk.js'))
    page.on('pageerror',lambda e:errors.append(str(e)))
    def route(r):
        u=urlsplit(r.request.url)
        if not r.request.url.startswith(BASE+'/'):
            unexpected.append(u.hostname+u.path);r.abort();return
        if u.path.startswith('/internal/'):
            if not u.path.startswith(('/internal/v1/admin/','/internal/v1/message-records','/internal/v1/message-analysis/')):
                unexpected.append(u.path);r.abort();return
            requests.append({'path':u.path,'method':r.request.method})
        r.continue_()
    context.route('**/*',route)
    response=context.request.post(BASE+'/internal/v1/admin/access',data={'password':'local-fixture-password'})
    assert response.ok
    before=context.request.get(BASE+'/__test/state').json()
    for width,height in ((1440,1000),(390,844),(360,800)):
        page.set_viewport_size({'width':width,'height':height})
        for name,identifier in seed.items():
            page.goto(BASE+'/control/messages?record_id='+identifier,wait_until='networkidle')
            region=page.get_by_role('region',name='전파 판단 미리보기',exact=True)
            expect(region.get_by_role('heading',name=labels[name],exact=True)).to_be_visible()
            expect(region).to_contain_text('미발송')
            if name=='area':
                assert 'km' not in region.get_by_label('전달 문안 미리보기').text_content()
            if name in ('general','ambiguous'):
                assert region.get_by_label('전달 문안 미리보기').count()==0
            if name=='source_only':
                assert 'km' not in region.get_by_label('전달 문안 미리보기').text_content()
            assert not region.get_by_role('button').count()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
            region.scroll_into_view_if_needed()
            if name in ('point','area','source_only') and width in (1440,390):
                region.screenshot(path=str(OUT/f'{name}-{width}.png'))
            checks.append({'case':name,'width':width,'decision':labels[name],'horizontal_overflow':False})
    after=context.request.get(BASE+'/__test/state').json()
    assert after==before
    assert not any(r['path'].endswith(('/analyze','/approve','/complete','/notice-copy')) for r in requests)
    assert not errors,errors
    assert not unexpected,unexpected
    result={'checks':checks,'page_errors':errors,'unexpected_requests':unexpected,'record_changes':0,
        'new_analysis_requests':0,'new_model_http_calls':0,'messages_sent':0,'map_mode':'local fake SDK; no real tiles',
        'state_before':before,'state_after':after,'preview_gets':sum(r['path'].endswith('/notification-preview') for r in requests)}
    (OUT/'browser-checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k not in ('checks','state_before','state_after')},ensure_ascii=False))
    browser.close()
