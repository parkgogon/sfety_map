"""Conservative emergency original-text policy for proven AI unavailability only."""
from __future__ import annotations

import datetime as dt
import re

from safety_dashboard.application.message_facility_queries import target_region_in
from safety_dashboard.application.message_notification import _map_url

KST = dt.timezone(dt.timedelta(hours=9))
REASONS = {"ai_daily_limit": "일일 분석 건수 한도", "ai_spend_limit": "AI 비용 한도",
           "ai_unavailable": "AI 연결/비용 원장 확인 불가", "ai_analysis_failed": "AI 분석 실패/결과 미상"}
EXCLUDED = re.compile(r"훈련|연습|시연|테스트|가상|예방|내일|모레|예정|계획|해제|취소|종료|오발송|정정|사칭|피싱|가짜|거짓|허위|잘못|오류|아니|아님|않|없|불필요|말[고아]|자제|경우|발생\s*시|시에는|[하되일]면|때|땐|만약|필요시|유사시|비상시|우려|대비|평소|사전|가능성|행동요령|문구|문자는|문장은|인용|예시|예문|어제|지난|당시|전날|지시했|요청했|안내했|명령했|\d{1,2}\s*[시월일]|\d{1,2}:\d{2}|[?？\"'“”‘’「」『』]")
OUTSIDE = re.compile(r"(?<![가-힣])(?:서울(?:특별시)?|인천(?:광역시)?|광주(?:광역시)?|대전(?:광역시)?|세종(?:특별자치시)?|경기(?:도)?|강원(?:특별자치도|도)?|충북|충청북도|충남|충청남도|전북|전북특별자치도|전라북도|전남|전라남도|제주(?:특별자치도|도)?)(?=\s|[.,·:：\[\]()의]|$)")
# Deliberately narrow: a current imperative, not the presence of the word 대피.
EVACUATE = re.compile(r"(?:지금|즉시|긴급히|신속히)\s*(?:(?:안전한\s*곳|높은\s*곳|인근\s*대피소)(?:으로|로)\s*)?대피(?:하세요|하십시오|하시기\s*바랍니다)[.!。]?(?=\s|\[|$)")


def unavailable_reason(record, check=None):
    if record.get("analysis_state") == "failed":
        return "ai_analysis_failed"
    if record.get("analysis_state") != "not_analyzed":
        return None
    return check(record) if check else None


def emergency_original_preview(record, base, reason, *, now, base_url=""):
    """Return None on ambiguity. Recipient/issuer labels cannot establish the site."""
    if (reason not in REASONS or record.get("origin") != "official"
            or record.get("analysis_state") not in {"failed", "not_analyzed"}):
        return None
    text = record["message"]["text"]
    body = re.sub(r"\[[^\]]*\]", "", text).strip()
    if not target_region_in(body) or OUTSIDE.search(body) or EXCLUDED.search(text):
        return None
    command = EVACUATE.search(body)
    if not command:
        return None
    try:
        issued = dt.datetime.fromisoformat(record["message"]["issued_at"])
        if issued.tzinfo is None or not -dt.timedelta(minutes=5) <= now-issued <= dt.timedelta(hours=1):
            return None
    except (TypeError, ValueError, KeyError):
        return None
    map_url = _map_url(base_url, [])
    rendered = ("[재난문자 원문 안내 · AI 분석 불가]\n"
                f"발행 {issued.astimezone(KST):%Y-%m-%d %H:%M} KST\n"
                f"{text}\n\nAI 분석을 완료하지 못해 공식 원문을 안내합니다. "
                "발생 지점·관련 시설·거리는 확인되지 않았습니다.")
    if map_url:
        rendered += "\n현장 지도: "+map_url
    if len(rendered) > 3900:
        return None
    return {**base, "decision": "notify_source_only", "reason": "소관 지역의 현재 대피 지시 원문 대체 기준에 해당합니다.",
            "preparation_kind": "raw_emergency_fallback", "fallback_rule": "current_evacuation_v1",
            "fallback_unavailable_reason": reason, "fallback_evidence": command.group(),
            "assessment": None, "facilities": [], "facility_count": 0, "map_url": map_url,
            "limitations": ["AI 분석 불가 · "+REASONS[reason], "관련 시설과 거리를 추정하지 않습니다."],
            "preview_text": rendered}
