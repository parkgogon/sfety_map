"""Built React app + actual local API, entirely fake data and senders."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect

OUT=Path(__file__).parent
BASE='http://127.0.0.1:'+Path('/tmp/notification-stage4-port.txt').read_text().strip()
checks=[];errors=[];unexpected=[];requests=[]
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox','--disable-dev-shm-usage'])
    context=browser.new_context()
    context.add_init_script(path=str(OUT.parent/'message-auto-forwarding-stage1/fake_sdk.js'))
    def route(r):
        u=urlsplit(r.request.url)
        if not r.request.url.startswith(BASE+'/'):
            unexpected.append(u.hostname+u.path);r.abort();return
        if u.path.startswith(('/internal/','/api/')):
            requests.append({'path':u.path,'method':r.request.method})
        r.continue_()
    context.route('**/*',route)
    assert context.request.post(BASE+'/internal/v1/admin/access',data={'password':'local-fixture-password'}).ok
    before=context.request.get(BASE+'/__test/state').json()
    page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
    for width,height in ((1440,1000),(390,844),(360,800)):
        page.set_viewport_size({'width':width,'height':height})
        page.goto(BASE+'/control/messages?view=delivery',wait_until='networkidle')
        expect(page.get_by_role('heading',name='재난문자 자동전파 중',exact=True)).to_be_visible()
        expect(page.get_by_text('수신 결과 미상',exact=True)).to_be_visible()
        expect(page.get_by_text('전송 응답 확인',exact=True).first).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
        page.screenshot(path=str(OUT/f'deliveries-{width}.png'),full_page=True)
        page.get_by_role('button',name='판단 기록',exact=True).click()
        expect(page.get_by_text('전파 결과: 전송 응답 확인',exact=True)).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
        page.get_by_role('button',name='확인 필요',exact=True).click()
        expect(page.get_by_text('같은 사유 원문 1건 · 중복 관측 제외',exact=True).first).to_be_visible()
        page.screenshot(path=str(OUT/f'exceptions-{width}.png'),full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
        checks.append({'width':width,'tabs':3,'horizontal_overflow':False,'fixture_receipts':'sent/unknown/waiting'})
    # One global pause/start, never a per-message send. Only the local memory control changes.
    page.get_by_role('button',name='전파 일시정지',exact=True).click()
    expect(page.get_by_role('heading',name='자동전파 일시정지',exact=True)).to_be_visible()
    page.once('dialog',lambda d:d.accept())
    page.get_by_role('button',name='자동전파 시작',exact=True).click()
    expect(page.get_by_role('heading',name='재난문자 자동전파 중',exact=True)).to_be_visible()
    after=context.request.get(BASE+'/__test/state').json()
    for field in ('fake_analysis_calls','fake_staff_requests','fake_admin_requests','human_versions','review_states'):
        assert before[field]==after[field],field
    assert before['generation']!=after['generation']
    assert not any(r['path'].endswith(('/analyze','/approve','/complete','/dispatch','/send')) for r in requests)
    assert not unexpected,unexpected
    assert not errors,errors
    report={'fixture_only':True,'checks':checks,'page_errors':errors,'unexpected_requests':unexpected,
        'browser_model_requests':0,'real_model_http_calls':0,'real_messages_sent':0,'production_deployed':False,
        'global_control_changes':2,'human_record_changes':0,'fake_sender_calls_during_browser_actions':0}
    (OUT/'browser-checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))
    browser.close()
