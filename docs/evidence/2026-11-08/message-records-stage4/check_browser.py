import json
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from playwright.sync_api import sync_playwright,expect
out=Path('/workspace/analysis/contest/message-records-stage4')
errors=[];unexpected=[];analysis_calls=[];checks=[];copy_checks=[]
original='가람교와 푸른교는 침수 우려로 오늘 10시부터 통제합니다. 우회하여 주시기 바랍니다.'
followup='오늘 15시 가람교 통제는 해제하였으나 푸른교 통제는 유지됩니다. 구간별로 확인 바랍니다.'
base='http://127.0.0.1:5177'
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
 context=browser.new_context(viewport={'width':1440,'height':1050},permissions=['clipboard-read','clipboard-write'])
 page=context.new_page();page.add_init_script(path=str(out/'fake_sdk.js'))
 page.on('pageerror',lambda e:errors.append(str(e)))
 def route(r):
  url=r.request.url
  if url.endswith('/analyze'):analysis_calls.append('fixture-analysis')
  if url.endswith('/notice-copy'):copy_checks.append('checked')
  if not url.startswith(base+'/'):
   unexpected.append('external');r.abort()
  elif ('/api/' in url or '/internal/' in url) and not any(a in url for a in ('/internal/v1/admin/','/internal/v1/message-analysis/','/internal/v1/message-records')):
   unexpected.append(url.split('?')[0]);r.abort()
  else:r.continue_()
 page.route('**/*',route)
 page.goto(base+'/control/messages')
 page.get_by_label('관리자 비밀번호').fill('local-fixture-password');page.get_by_role('button',name='로그인',exact=True).click()
 page.get_by_role('heading',name='등록한 재난문자',exact=True).wait_for()
 review=page.get_by_role('region',name='검토 결과와 안내 초안',exact=True)
 related=page.get_by_role('region',name='후속 문자 연결과 구간 비교',exact=True)
 def register(text,hour):
  page.get_by_role('button',name='사고 발생',exact=True).click()
  page.get_by_label('문자 원문',exact=True).fill(text);page.get_by_label('발신처·출처',exact=True).fill('창작 검수 문자')
  page.get_by_label('발행 시각 (한국 시간)',exact=True).fill('2026-11-08T'+hour+':00')
  page.get_by_label('문자 수신지역',exact=True).fill('경상북도 구미시')
  page.get_by_role('button',name='등록하고 분석하기',exact=True).click()
  review.get_by_label('완료할 검토 결과',exact=True).wait_for()
  return parse_qs(urlparse(page.url).query)['record_id'][0]
 def complete(note=''):
  review.get_by_label('완료할 검토 결과',exact=True).select_option('no_action')
  review.get_by_label('검토 완료 사유',exact=True).fill('창작 시나리오 검수: 시설 선정 없이 문서 흐름만 확인')
  if note:review.get_by_label('확인 질문 보완 메모',exact=True).fill(note)
  review.get_by_role('button',name='검토 완료하고 초안 만들기',exact=True).click()
  review.get_by_role('heading',name='검토 완료 · 추가 조치 없음',exact=True).wait_for()
 parent_id=register(original,'10');parent_url=page.url;complete()
 original_record=context.request.get(base+'/internal/v1/message-records/'+parent_id).json()
 old_notice=original_record['notice_draft']['text']
 page.get_by_role('button',name='새 문자 등록',exact=True).click();target_id=register(followup,'15')
 target_record=context.request.get(base+'/internal/v1/message-records/'+target_id).json()
 page.goto(parent_url);review.get_by_role('heading',name='검토 완료 · 추가 조치 없음',exact=True).wait_for()
 related.get_by_role('button',name='연결할 후속 문자 찾기',exact=True).click()
 candidate=related.locator('.message-record-list li').filter(has_text=followup)
 candidate.get_by_role('button',name='이 문자와 비교',exact=True).click()
 preview=related.get_by_role('region',name='후속 문자 원문 비교',exact=True)
 expect(preview).to_contain_text('일부 구간 해제와 통제 유지가 함께')
 expect(preview).to_contain_text('가람교 (통제 장소) · 같은 표기 · 이전: 통제 유지 · 후속: 해제')
 expect(preview).to_contain_text('푸른교 (통제 장소) · 같은 표기 · 이전: 통제 유지 · 후속: 통제 유지')
 for width in (1440,390,360):
  page.set_viewport_size({'width':width,'height':1050 if width==1440 else 844})
  page.evaluate("scrollTo(0,document.querySelector('.message-related-preview').getBoundingClientRect().top+scrollY-85)")
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
  page.screenshot(path=str(out/f'comparison-{width}.png'))
 checks.append('1440/390/360px: original/follow-up comparison has no horizontal overflow; release/continuing control stay separate')
 page.set_viewport_size({'width':1440,'height':1050})
 preview.get_by_label('후속 연결 종류',exact=True).select_option('release')
 preview.get_by_label('후속 연결 사유',exact=True).fill('창작 검수: 같은 교량 두 곳의 일부 해제 안내임을 원문으로 확인')
 preview.get_by_role('checkbox',name='원문·시각·지역·구간을 대조했으며 같은 상황의 후속 문자로 연결합니다',exact=True).check()
 preview.get_by_role('button',name='검토 대상으로 연결',exact=True).click()
 review.get_by_label('검토 완료 사유',exact=True).wait_for()
 assert review.get_by_label('저장한 안내 초안',exact=True).count()==0
 linked=context.request.get(base+'/internal/v1/message-records/'+parent_id).json()
 assert linked['review_state']=='needs_confirmation' and linked['review_completion'] is None
 assert linked['analysis']==original_record['analysis'] and linked['message']==original_record['message']
 assert context.request.get(base+'/internal/v1/message-records/'+target_id).json()==target_record
 assert review.get_by_label('검토 완료 사유',exact=True).input_value()==''
 checks.append('manual relationship invalidates old completion/notice; source analysis and independent target record unchanged')
 review.get_by_label('완료할 검토 결과',exact=True).select_option('no_action')
 review.get_by_label('검토 완료 사유',exact=True).fill('창작 검수: 구간별 근거 재확인')
 expect(review.get_by_role('button',name='검토 완료하고 초안 만들기',exact=True)).to_be_disabled()
 note='창작 검수: 가람교만 해제이며 푸른교는 계속 통제 중임. 전체 종료로 판단하지 않음.'
 complete(note)
 text=review.get_by_label('저장한 안내 초안',exact=True).input_value()
 assert original in text and followup in text and '전체 해제 추정 금지' in text and note in text
 assert '해제: 오늘 15시 가람교 통제는 해제하였으나' in text and '통제 유지: 푸른교 통제는 유지됩니다.' in text
 review.get_by_role('button',name='현재 초안 복사',exact=True).click()
 review.get_by_text('초안을 클립보드에 복사했습니다. 실제 발송·수신 기록은 아닙니다.',exact=True).wait_for()
 assert page.evaluate('navigator.clipboard.readText()')==text
 checks.append('linked follow-up requires segment review note; new draft includes both verbatim originals and partial release caution, server-checked clipboard')
 page.reload();related.get_by_text('연결 사유: 창작 검수: 같은 교량 두 곳의 일부 해제 안내임을 원문으로 확인',exact=True).wait_for()
 review.get_by_label('저장한 안내 초안',exact=True).wait_for();assert len(analysis_calls)==2
 checks.append('relationship/completion/notice survive reload without new analysis')
 completed=context.request.get(base+'/internal/v1/message-records/'+parent_id).json()
 response=context.request.post(base+'/internal/v1/message-records/'+target_id+'/analyze',data={'expected_version':target_record['version'],'reference_radius_km':3})
 assert response.status==200,response.text();analysis_calls.append('fixture-analysis-direct')
 check=context.request.post(base+'/internal/v1/message-records/'+parent_id+'/notice-copy',data={'expected_version':completed['version'],'draft_revision':completed['notice_draft']['revision']})
 assert check.status==409,check.text();copy_checks.append('blocked-after-followup-change')
 review.get_by_role('button',name='검토 결과 다시 불러오기',exact=True).click()
 expect(review.get_by_role('button',name='현재 초안 복사',exact=True)).to_be_disabled()
 related.get_by_role('button',name='후속 연결 다시 불러오기',exact=True).click()
 related.get_by_text('해제 관련 · 창작 예문 · 재확인 필요',exact=True).wait_for()
 related.get_by_role('button',name='이 연결 비교·재확인',exact=True).click()
 preview.get_by_label('후속 연결 사유',exact=True).fill('창작 검수: 후속 분석 새 버전에서 부분 해제·유지 다시 확인')
 preview.get_by_role('checkbox',name='원문·시각·지역·구간을 대조했으며 같은 상황의 후속 문자로 연결합니다',exact=True).check()
 preview.get_by_role('button',name='비교를 다시 확인하고 저장',exact=True).click()
 review.get_by_label('검토 완료 사유',exact=True).wait_for();complete(note)
 checks.append('target reanalysis dynamically blocks previous copy despite unchanged parent version; explicit reconfirmation and new completion restore current draft')
 related.get_by_role('button',name='연결 해제 사유 입력',exact=True).click()
 related.get_by_label('연결 해제 사유',exact=True).fill('창작 검수: 관계 취소 동작과 이력 보존 확인')
 related.get_by_role('button',name='사유를 남기고 연결 해제',exact=True).click()
 related.get_by_text('연결한 후속 문자가 없습니다.',exact=True).wait_for()
 assert review.get_by_label('저장한 안내 초안',exact=True).count()==0
 assert context.request.get(base+'/internal/v1/message-records/'+target_id).status==200
 page.get_by_role('button',name='변경 이력 보기',exact=True).click()
 history=context.request.get(base+'/internal/v1/message-records/'+parent_id+'/history').json()
 linked_version=next(row['record']['version'] for row in history['versions'] if row['event']=='message_reconfirmed')
 page.get_by_role('button',name=f'{linked_version}판 · 후속 연결 재확인',exact=True).click()
 past=page.get_by_role('region',name='과거 후속 연결',exact=True);past.wait_for()
 assert '후속 분석 새 버전' in past.text_content() and '분석 2판' in past.text_content()
 assert past.locator('input,textarea,button').count()==0
 checks.append('unlink preserves both records and historical link reasons/analysis revisions, no resurrection of old completion')
 assert not errors,errors
 assert not unexpected,unexpected
 context.close();browser.close()
result={'status':'passed','transport':'real local React/API/CSV/memory store; scripted bridge messages/analysis, fake map SDK, no real tiles',
 'fixture_analysis_requests':len(analysis_calls),'copy_basis_checks':len(copy_checks),'new_openai_kakao_calls':0,'actual_messages_sent':0,
 'checks':checks,'page_errors':errors,'unexpected_requests':unexpected}
(out/'checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False))
