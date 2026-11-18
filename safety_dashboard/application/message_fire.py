"""Evidence required for a regional fire notice when the exact site is unresolved."""
from __future__ import annotations

from dataclasses import dataclass
import re

from safety_dashboard.application.message_address import AREA, LOCALITY
from safety_dashboard.application.message_facility_queries import area_tokens

_FIRE = re.compile(r"(?P<kind>산불|화재)(?:가)?\s*발생(?=(?:[.,/!。 ]|했|하였|하여|함|$))")
_PLACE = re.compile(rf"(?<![가-힣])(?P<area>{AREA})(?=\s|$)(?P<site>[^,./:;!?]{{0,80}})$")
_LOCALITY = re.compile(rf"^(?P<local>(?:{LOCALITY}\s*){{1,3}})")
_ACTION = re.compile(
    r"(?:(?:입산\s*및\s*)?(?:화재\s*)?현장\s*주변\s*)?(?:접근|입산)(?:을)?\s*(?:금지|자제)"
    r"|(?:즉시|신속히|긴급히)\s*(?:(?:안전한\s*곳|대피소)(?:으로|로)\s*)?"
    r"대피(?:하세요|하십시오|하시기\s*바랍니다)"
)
_EXCLUDED = re.compile(
    r"훈련|연습|시연|오인|오보|가상|가정|예방|대비|해제|취소|정정|예정|인용|"
    r"(?:진화|진압)\s*(?:완료|됐|되었)|(?:대피|통제)\s*종료|"
    r"발생\s*(?:시|우려|가능성|위험)|(?:금지|자제|대피)\s*(?:가\s*)?(?:불필요|필요\s*없|아님|하지\s*않)|"
    r"[?\"“”「」『』]"
)
_OTHER_REGION = re.compile(
    r"(?<![가-힣])(?:서울|인천|광주|대전|세종|경기|강원|충청[남북]도|전라[남북]도|전북|전남|충북|충남|제주)"
    r"(?:특별시|광역시|특별자치[시도]|도)?(?=\s|[.,]|$)"
)


@dataclass(frozen=True)
class FireGuidance:
    scope: tuple[str, ...]
    location: str
    kind: str
    instruction: str


def fire_guidance(text: str) -> FireGuidance | None:
    body = " ".join(re.sub(r"\[[^\]]{1,80}\]", "", text).split())
    if _EXCLUDED.search(body) or _OTHER_REGION.search(body):
        return None
    fires = list(_FIRE.finditer(body))
    if len(fires) != 1:
        return None
    fire = fires[0]
    action = _ACTION.search(body, fire.end())
    match = _PLACE.search(body[:fire.start()].rstrip())
    if not match or not action:
        return None
    scope = area_tokens(match["area"])
    site = _LOCALITY.match(match["site"].strip())
    if not scope or (len(scope) == 1 and (not scope[0].endswith("광역시") or not site)):
        return None
    location = " ".join(filter(None, (match["area"], site["local"].strip() if site else "")))
    return FireGuidance(scope, location, fire["kind"], action.group())
