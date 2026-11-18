"""Ground a parcel lookup in the address actually quoted in an official message."""
from __future__ import annotations

from dataclasses import dataclass
import re

from safety_dashboard.application.message_facility_queries import area_tokens

AREA = r"(?:대구(?:시|광역시)?|부산(?:시|광역시)?|울산(?:시|광역시)?|경북|경상북도|경남|경상남도)(?:\s+[가-힣]{1,14}[시군구]){0,2}"
LOCALITY = r"[가-힣0-9]{1,18}[읍면동리]"
_PARCEL = re.compile(
    rf"(?<![가-힣])(?P<area>{AREA})\s+(?P<locality>(?:{LOCALITY}\s+){{1,3}})"
    r"(?P<number>(?:산\s*)?\d{1,5}(?:-\d{1,5})?)(?![\d-])"
)


@dataclass(frozen=True)
class MessageParcel:
    query: str
    scope: tuple[str, ...]
    locality: tuple[str, ...]
    number: str

    def matches(self, address: str) -> bool:
        other = message_parcel(address)
        return bool(other and other.scope[:len(self.scope)] == self.scope
                    and other.locality[-len(self.locality):] == self.locality and other.number == self.number)


def message_parcel(text: str) -> MessageParcel | None:
    matches = list(_PARCEL.finditer(text))
    if len(matches) != 1:
        return None
    match = matches[0]
    scope = area_tokens(match["area"])
    if not scope:
        return None
    locality = tuple(match["locality"].split())
    number = re.sub(r"\s+", "", match["number"])
    return MessageParcel(" ".join((*scope, *locality, number)), scope, locality, number)


def quoted_parcel(location_text: str, evidence: str) -> MessageParcel | None:
    parcel = message_parcel(evidence)
    if parcel and re.search(
        re.escape(parcel.locality[-1]) + r"\s+" + re.escape(parcel.number).replace("산", r"산\s*") + r"(?![\d-])",
        location_text,
    ):
        return parcel
    return None
