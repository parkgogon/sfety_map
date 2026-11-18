"""Match official KMA earthquake reports to magnitude-only corrections."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from hashlib import sha256
import re

KEY_PREFIX = "message-earthquake-"
KST = dt.timezone(dt.timedelta(hours=9))
_REPORT = re.compile(
    r"(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s*"
    r"(?P<province>경북|경상북도|경남|경상남도|대구(?:광역)?시?|부산(?:광역)?시?|울산(?:광역)?시?)\s+"
    r"(?P<district>[가-힣]{1,15}[시군구])\s+"
    r"(?P<direction>동|서|남|북|북동|북서|남동|남서)쪽\s*(?P<km>\d{1,4}(?:\.\d)?)\s*km\s+지역"
    r"(?:에서\s*발생한)?\s*규모\s*(?P<initial>\d\.\d)\s*지진(?P<tail>.*?)\s*\[기상청\]"
)
_INITIAL = re.compile(r"발생\s*(?:[/／]\s*(?P<guidance>추가\s*지진\s*발생\s*상황에\s*유의\s*(?:바람|바랍니다)[.]?))?")
_CORRECTION = re.compile(
    r"은\s*상세\s*분석을\s*통해\s*규모\s*(?P<adjusted>\d\.\d)\s*(?:으?로)\s*조정(?:됨|되었습니다)[.]?"
)
_PROVINCES = {"경상북도": "경북", "경상남도": "경남",
              **{name + suffix: name for name in ("대구", "부산", "울산") for suffix in ("시", "광역시")}}


@dataclass(frozen=True)
class Earthquake:
    key: str
    area: str
    location: str
    occurred_at: dt.datetime
    issued_at: dt.datetime
    magnitude: str
    is_correction: bool
    guidance: str

    def source(self, record):
        return {"record_id": record["id"], "source_revision": record["source_revision"],
                "issued_at": self.issued_at.astimezone(dt.timezone.utc).isoformat(timespec="microseconds"),
                "is_correction": self.is_correction}

    def is_latest(self, record, episode):
        return bool(episode and episode["latest"] == self.source(record))


def earthquake_report(record) -> Earthquake | None:
    if record.get("origin") != "official":
        return None
    message = record["message"]
    match = _REPORT.fullmatch(" ".join(message["text"].split()))
    if not match or not message.get("issued_at"):
        return None
    tail = match["tail"].strip()
    initial = _INITIAL.fullmatch(tail)
    correction = _CORRECTION.fullmatch(tail)
    if not initial and not correction:
        return None
    try:
        occurred_at = dt.datetime.strptime(match["time"], "%Y-%m-%d %H:%M").replace(tzinfo=KST)
        issued_at = dt.datetime.fromisoformat(message["issued_at"])
        if issued_at.tzinfo is None or issued_at < occurred_at:
            return None
    except ValueError:
        return None
    province = _PROVINCES.get(match["province"], match["province"])
    area = f"{province} {match['district']}"
    location = f"{area} {match['direction']}쪽 {match['km']}km 지역"
    # An exact origin time, area, direction, distance and preliminary magnitude
    # keep separate earthquakes from being grouped on a general topic or area.
    key = KEY_PREFIX + sha256(f"{occurred_at.isoformat()}|{location}|{match['initial']}".encode()).hexdigest()
    guidance = (initial["guidance"] or "") if initial else ""
    return Earthquake(key, area, location, occurred_at, issued_at,
                      correction["adjusted"] if correction else match["initial"], bool(correction), guidance)


def observe_earthquake(record, report, episode):
    incoming = report.source(record)
    latest = (episode or {}).get("latest")
    if latest:
        # A replay of the preliminary bulletin cannot replace a correction.
        def order(value):
            return value["is_correction"], value["issued_at"], value["record_id"], value["source_revision"]

        if order(incoming) <= order(latest):
            return None
    return {**(episode or {}), "latest": incoming}
