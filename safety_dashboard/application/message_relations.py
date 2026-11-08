"""관리자가 확인한 후속 문자 연결. 원본을 합치거나 통제·시설 상태를 변경하지 않는다."""
from __future__ import annotations

import copy
import re
from collections import Counter
from typing import Literal
from pydantic import Field

from safety_dashboard.application.message_records import RecordConflict, RecordVersion, content_hash
from safety_dashboard.application.message_spatial import MessageSpatialService

MAX_DIRECT, MAX_NODES, MAX_DEPTH = 10, 30, 4


class RelationValidationError(ValueError):
    pass


class LinkMessage(RecordVersion):
    target_id: str = Field(pattern=r"^(manual-[a-f0-9]{32}|official-[a-f0-9]{64})$")
    kind: Literal["additional", "correction", "release"]
    reason: str = Field(min_length=1, max_length=500)
    confirmed: bool
    comparison_token: str = Field(pattern=r"^[a-f0-9]{64}$")
    cross_region_confirmed: bool = False
    cross_region_reason: str = Field(default="", max_length=500)


class UnlinkMessage(RecordVersion):
    target_id: str = Field(pattern=r"^(manual-[a-f0-9]{32}|official-[a-f0-9]{64})$")
    reason: str = Field(min_length=1, max_length=500)


def facts(record):
    return content_hash({key: record.get(key) for key in ("content_hash", "source_revision", "analysis_revision",
        "analysis_source_revision", "analysis_state")})


def order(record):
    return tuple(record.get("relation_order", [record["created_at"], record["id"]]))


def summary(record):
    return {key: copy.deepcopy(record.get(key)) for key in ("id", "version", "origin", "message", "source_revision", "analysis_revision")}


def segments(record):
    return [{"index": i, "intent": p["intent"], "evidence": p.get("evidence", ""), "starts_at": p.get("starts_at"),
             "ends_at": p.get("ends_at"), "locations": [{"text": loc["text"], "role": loc["role"]} for loc in p.get("locations", [])]}
            for i, p in enumerate((record.get("analysis") or {}).get("analysis", {}).get("parts", []))]


def compare_segments(parent, target):
    left, right = segments(parent), segments(target)
    def entries(parts):
        return [(loc["role"], re.sub(r"\s+", "", loc["text"]), part, loc) for part in parts for loc in part["locations"]]
    a, b = entries(left), entries(right)
    ca, cb = Counter((r, t) for r, t, _, _ in a), Counter((r, t) for r, t, _, _ in b)
    matches = []
    for role, text, part, loc in a:
        exact = [other for r, t, other, _ in b if (r, t) == (role, text)]
        matches.append({"text": loc["text"], "role": role, "before": part,
                        "after": exact[0] if ca[role, text] == cb[role, text] == 1 else None,
                        "status": "same_spelling" if ca[role, text] == cb[role, text] == 1 else "earlier_only"})
    for role, text, part, loc in b:
        if ca[role, text] != 1 or cb[role, text] != 1:
            matches.append({"text": loc["text"], "role": role, "before": None, "after": part, "status": "followup_only"})
    intents = {p["intent"] for p in right}
    return {"before": left, "after": right, "locations": matches, "has_release": "release" in intents,
            "has_active_restriction": "active_restriction" in intents,
            "caution": "같은 표기도 동일한 실제 장소라는 증명은 아닙니다. 누락된 장소를 해제로 추정하지 않으며 시설·통제 상태를 자동 변경하지 않습니다."}


PROVINCES = {
    "서울": "서울", "서울시": "서울", "서울특별시": "서울", "부산": "부산", "부산시": "부산", "부산광역시": "부산",
    "대구": "대구", "대구시": "대구", "대구광역시": "대구", "울산": "울산", "울산광역시": "울산",
    "경북": "경북", "경상북도": "경북", "경남": "경남", "경상남도": "경남", "경기": "경기", "경기도": "경기",
    "인천": "인천", "인천광역시": "인천", "광주": "광주", "광주광역시": "광주", "대전": "대전", "대전광역시": "대전",
    "세종": "세종", "세종특별자치시": "세종", "강원": "강원", "강원도": "강원", "강원특별자치도": "강원",
    "충북": "충북", "충청북도": "충북", "충남": "충남", "충청남도": "충남", "전북": "전북", "전라북도": "전북", "전북특별자치도": "전북",
    "전남": "전남", "전라남도": "전남", "제주": "제주", "제주도": "제주", "제주특별자치도": "제주",
}


def region_hint(parent, target):
    # Only explicit recipient metadata; issuer/text/place names are never invented as jurisdiction.
    def scopes(record):
        found = []
        for value in record["message"]["recipient_regions"]:
            words = value.split()
            if not words or words[0] not in PROVINCES:
                return []
            city = next((w for w in words[1:] if re.fullmatch(r"[가-힣]+[시군]", w)), "")
            found.append((PROVINCES[words[0]], city))
        return found
    left, right = scopes(parent), scopes(target)
    if not left or not right:
        return {"status": "unknown", "detail": "수신지역만으로 지역 관계를 판단하기 어렵습니다. 원문과 발행 정보를 직접 확인해 주세요."}
    overlap = any(p == q and (not c or not d or c == d) for p, c in left for q, d in right)
    return {"status": "overlap" if overlap else "disjoint", "detail":
        "수신지역에 겹치는 범위가 있습니다. 동일 사건이라는 증명은 아닙니다." if overlap else
        "수신지역이 다릅니다. 같은 이름의 다른 장소인지 확인하고, 광역 사건이면 연결 근거를 추가해 주세요."}


class MessageRelationService:
    def __init__(self, records):
        self.records = records

    def _graph(self, root, extra=None):
        nodes = {root["id"]: root}
        if extra: nodes[extra["id"]] = extra
        frontier = list(nodes.values())
        for depth in range(MAX_DEPTH + 1):
            wanted = {key for r in frontier for key in r.get("related_messages", {}) if key not in nodes}
            if not wanted: break
            if depth == MAX_DEPTH or len(nodes) + len(wanted) > MAX_NODES:
                raise RecordConflict("후속 연결 조회 한도를 넘었습니다. 연결 범위를 줄여 주세요.")
            loaded = self.records.store.get_many(sorted(wanted))
            if set(loaded) != wanted:
                raise RecordConflict("연결된 후속 기록을 찾을 수 없습니다. 연결을 확인해 주세요.")
            nodes.update(loaded); frontier = list(loaded.values())
        memo, heights = {}, {}
        def fingerprint(identifier, path=()):
            if identifier in path:
                raise RecordConflict("순환하는 후속 연결을 확인해 주세요.")
            if identifier in memo: return memo[identifier]
            r = nodes[identifier]
            children = {key: {"link": edge, "context": fingerprint(key, (*path, identifier))}
                        for key, edge in sorted(r.get("related_messages", {}).items())}
            heights[identifier] = 1 + max((heights[key] for key in children), default=-1)
            if heights[identifier] > MAX_DEPTH:
                raise RecordConflict("후속 연결은 최대 4단계까지 조회합니다. 연결 범위를 줄여 주세요.")
            memo[identifier] = content_hash({"facts": facts(r), "epoch": r.get("relation_epoch", 0), "children": children})
            return memo[identifier]
        hashes = {key: fingerprint(key) for key in nodes}
        return nodes, hashes

    @staticmethod
    def _current(parent, target, edge, target_hash):
        return edge["parent_facts"] == facts(parent) and edge["target_facts"] == facts(target) and edge["target_context"] == target_hash

    def _context(self, root, *, strict):
        nodes, hashes = self._graph(root)
        links = []
        stale = False
        for parent in sorted(nodes.values(), key=order):
            for key, edge in sorted(parent.get("related_messages", {}).items()):
                current = self._current(parent, nodes[key], edge, hashes[key])
                stale |= not current
                target_summary = summary(nodes[key])
                # Notes/identical feed observations/review status do not change source evidence.
                if strict: target_summary.pop("version")
                links.append({"parent_id": parent["id"], "target": target_summary, "edge": copy.deepcopy(edge),
                              "needs_reconfirm": not current, "segments": segments(nodes[key])})
        if strict and stale:
            raise RecordConflict("후속 문자 원문·분석 또는 연결이 변경됐습니다. 연결 비교에서 다시 확인해 주세요.")
        return {"epoch": root.get("relation_epoch", 0), "fingerprint": hashes[root["id"]], "links": links, "needs_reconfirm": stale}

    def context(self, root):
        return self._context(root, strict=True)

    def detail(self, identifier):
        root = self.records.get(identifier)
        return {"record_version": root["version"], **self._context(root, strict=False)}

    def candidates(self, identifier, before=None):
        root = self.records.get(identifier)
        page = self.records.list_page(before, 20)
        page["records"] = [r for r in page["records"] if r["id"] != root["id"]]
        return page

    def _pair(self, identifier, target_id):
        parent, target = self.records.get(identifier), self.records.get(target_id)
        if identifier == target_id or order(parent) >= order(target):
            raise RelationValidationError("먼저 발행된 기존 기록에서 이후 후속 문자를 연결해 주세요.")
        if (parent["origin"] == "example") != (target["origin"] == "example"):
            raise RelationValidationError("창작 예문은 창작 예문끼리만 연결할 수 있습니다.")
        MessageSpatialService._ready(parent); MessageSpatialService._ready(target)
        _, hashes = self._graph(parent, target)
        # Adding the edge may increase root depth; validate the proposed graph separately before saving.
        token = content_hash({"parent": hashes[identifier], "target": hashes[target_id], "versions": [parent["version"], target["version"]]})
        return parent, target, hashes, token

    def preview(self, identifier, target_id):
        parent, target, _, token = self._pair(identifier, target_id)
        return {"record_version": parent["version"], "parent": summary(parent), "target": summary(target),
                "comparison_token": token, "regions": region_hint(parent, target), "comparison": compare_segments(parent, target)}

    def link(self, identifier, request: LinkMessage):
        parent, target, hashes, token = self._pair(identifier, request.target_id)
        if parent["version"] != request.expected_version or token != request.comparison_token:
            raise RecordConflict("비교 대상이 변경됐습니다. 원문 비교를 다시 불러와 주세요.")
        if not request.confirmed or not request.reason.strip():
            raise RelationValidationError("같은 상황의 후속 문자임을 확인하고 연결 사유를 입력해 주세요.")
        if region_hint(parent, target)["status"] == "disjoint" and (not request.cross_region_confirmed or not request.cross_region_reason.strip()):
            raise RelationValidationError("수신지역이 다른 문자를 연결하려면 광역 사건 여부와 별도 근거를 확인해 주세요.")
        links = parent.setdefault("related_messages", {})
        previous = links.get(target["id"])
        if not previous and len(links) >= MAX_DIRECT:
            raise RelationValidationError(f"직접 연결은 최대 {MAX_DIRECT}건입니다.")
        links[target["id"]] = {"target_id": target["id"], "kind": request.kind, "reason": request.reason.strip(),
            "cross_region_reason": request.cross_region_reason.strip() if request.cross_region_confirmed else "",
            "confirmed_at": self.records.now().isoformat(), "revision": previous["revision"] + 1 if previous else 1,
            "parent_facts": facts(parent), "target_facts": facts(target), "target_context": hashes[target["id"]],
            "parent_source_revision": parent["source_revision"], "target_source_revision": target["source_revision"],
            "parent_analysis_revision": parent["analysis_revision"], "target_record_version": target["version"],
            "target_analysis_revision": target["analysis_revision"]}
        self._graph(parent)  # Bounded proposed graph, also checks cycles.
        return self._save(parent, request.expected_version, "message_reconfirmed" if previous else "message_linked", target["id"], request.reason.strip())

    def unlink(self, identifier, request: UnlinkMessage):
        parent = self.records.get(identifier)
        if parent["version"] != request.expected_version:
            raise RecordConflict("기록이 변경됐습니다. 다시 불러와 주세요.")
        if not request.reason.strip() or request.target_id not in parent.get("related_messages", {}):
            raise RelationValidationError("현재 연결과 연결 해제 사유를 확인해 주세요.")
        del parent["related_messages"][request.target_id]
        return self._save(parent, request.expected_version, "message_unlinked", request.target_id, request.reason.strip())

    def _save(self, record, expected, event, target, reason):
        record["relation_epoch"] = record.get("relation_epoch", 0) + 1
        record["relation_last_change"] = {"action": event, "target_id": target, "reason": reason, "at": self.records.now().isoformat()}
        record["review_state"] = "needs_confirmation"
        return self.records._save(record, expected, event)
