"""Explicitly requested, bounded live evaluation of six authored examples.

Separate from the network-blocked unit tests. Only OpenAI and optional Kakao
adapters are constructed; no API server, monitoring worker or notifier is used.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from safety_dashboard.adapters.facility_csv import CsvFacilityRepository
from safety_dashboard.adapters.kakao_places import KakaoPlaceSearch
from safety_dashboard.adapters.openai_messages import OpenAIConnectionError, OpenAIResponsesClient
from safety_dashboard.application.message_analysis import AnalysisUnavailable, MessageAnalysisInput, MessageAnalysisService

CASE_IDS = ("prevention", "event", "scheduled", "partial_release", "ambiguous", "destination")
KST = dt.timezone(dt.timedelta(hours=9))


def select_examples(examples: list[dict], case: str) -> list[dict]:
    # Keep the paid batch fixed even if the UI examples are expanded later.
    if len(examples) != len(CASE_IDS) or {example["id"] for example in examples} != set(CASE_IDS):
        raise ValueError("The live evaluation requires exactly the six reviewed example IDs.")
    return [example for example in examples if case == "all" or example["id"] == case]


def check_case(example: dict, result: dict, *, with_places: bool = False) -> dict[str, bool]:
    """Small, explicit acceptance checks; passing still requires human review."""
    parts = result["analysis"]["parts"]
    intents = {part["intent"] for part in parts}
    locations = [location for part in parts for location in part["locations"]]
    checks = {
        "expected_intents": set(example["expected_intents"]) <= intents,
        "expected_location_roles": set(example["expected_roles"]) <= {location["role"] for location in locations},
        "review_required": result["review_required"] is True,
    }
    if example["expected_start"]:
        checks["publication_relative_start"] = any(part["starts_at"] == example["expected_start"] for part in parts)
    case_id = example["id"]
    if case_id == "prevention":
        checks["no_incident_or_unnecessary_lookup"] = "event" not in intents and not any(
            step["tool"] in {"search_places", "find_nearby_facilities"} for step in result["trace"])
    if case_id == "scheduled":
        checks["not_current_restriction"] = "active_restriction" not in intents
        checks["scheduled_end"] = any(part["ends_at"] == "2026-11-08T12:00:00+09:00" for part in parts)
    if case_id == "partial_release":
        checks["released_segment"] = any(part["intent"] == "release" and "가람교" in part["evidence"] for part in parts)
        checks["still_restricted_segment"] = any(part["intent"] == "active_restriction" and "푸른교" in part["evidence"] for part in parts)
        checks["release_end_time"] = any(part["intent"] == "release" and part["starts_at"] is None
                                         and part["ends_at"] == "2026-11-07T15:00:00+09:00" for part in parts)
    if case_id == "ambiguous":
        checks["asks_for_location_confirmation"] = bool(result["analysis"]["questions"])
    if case_id == "destination":
        checks["incident_site"] = any("와룡산" in place["text"] and place["role"] == "incident_site" for place in locations)
        checks["destination_role"] = any("성서초등학교" in place["text"] and place["role"] == "evacuation_destination" for place in locations)
        checks["destination_not_incident"] = not any("성서초등학교" in place["text"] and place["role"] in {"incident_site", "restricted_area"} for place in locations)
    if with_places:
        searches = [step for step in result["trace"] if step["tool"] == "search_places"]
        lookups = [step for step in result["trace"] if step["tool"] == "find_nearby_facilities" and step["status"] == "ok"]
        candidates = {candidate["id"]: candidate for candidate in result.get("candidates", [])}
        # Locally rejected arguments have not reached the provider. A corrected
        # retry is legitimate agent recovery; only an unavailable provider fails
        # this check. Required primary searches are checked separately below.
        checks["no_place_provider_failures"] = all(step["status"] != "unavailable" for step in searches)
        checks["auditable_facility_lookup_scope"] = all(
            step.get("candidate_id") in candidates
            and candidates[step["candidate_id"]].get("scope_matches_source") is True
            and step.get("role") == candidates[step["candidate_id"]].get("role")
            and step["role"] in {"incident_site", "restricted_area", "evacuation_area"}
            for step in lookups)
        if case_id in {"event", "scheduled", "destination"}:
            role = "restricted_area" if case_id == "scheduled" else "incident_site"
            checks["primary_place_search_attempted"] = any(step.get("role") == role and step["status"] in {"ok", "not_found"} for step in searches)
        if case_id == "ambiguous":
            checks["no_city_guess_facility_lookup"] = not lookups and not result["nearby"]
        if case_id == "destination":
            checks["separate_incident_and_destination_queries"] = not any(
                "와룡산" in candidate["query"] and "성서초등학교" in candidate["query"] for candidate in candidates.values())
            destination_ids = {key for location in locations if location["role"] == "evacuation_destination" for key in location["candidate_ids"]}
            checks["destination_school_kind_matches"] = all(
                candidates[key].get("category_group_code") == "SC4" for key in destination_ids if key in candidates)
        if case_id in {"event", "destination"}:
            primary_ids = {key for location in locations if location["role"] == "incident_site" for key in location["candidate_ids"]}
            primary = [candidates[key] for key in primary_ids if key in candidates]
            kind = "산업단지" if case_id == "event" else "산"
            checks["primary_place_kind_matches"] = bool(primary) and all(
                candidate.get("category_name", "").split(" > ")[-1] == kind for candidate in primary)
            checks["reference_facility_lookup_exercised"] = any(
                step.get("candidate_id") in primary_ids and step.get("role") == "incident_site" for step in lookups)
    return checks


def evaluate(examples, service, client, *, with_places=False, pause=time.sleep, clock=time.monotonic):
    rows = []
    last_started = None
    for example in examples:
        # Honor the same service's 20-second start interval; never run in parallel.
        if last_started is not None:
            delay = max(0, 20.1 - (clock() - last_started))
            if delay:
                pause(delay)
        last_started = clock()
        before = client.usage_snapshot()
        row = {"id": example["id"], "label": example["label"], "status": "error"}
        abort_batch = False
        try:
            result = service.analyze(MessageAnalysisInput(
                **{key: example[key] for key in ("text", "source", "issued_at")},
                reference_radius_km=3, input_kind="example"))
            checks = check_case(example, result, with_places=with_places)
            row.update(status="pass" if all(checks.values()) else "needs_review", checks=checks, result=result)
        except OpenAIConnectionError as error:
            row["error"] = str(error)  # Only adapter-authored public messages.
            abort_batch = True
        except AnalysisUnavailable as error:
            row["error"] = str(error)
        except Exception:
            row["error"] = "평가 처리 오류. 원본 예외·외부 응답은 기록하지 않았습니다."
            abort_batch = True
        after = client.usage_snapshot()
        row["usage"] = {key: after[key] - before[key] for key in after}
        row["elapsed_ms"] = round((clock() - last_started) * 1000)
        rows.append(row)
        print(f"{example['id']}: {row['status']}", flush=True)
        if abort_batch:
            break
    return rows


def write_report(report: dict, output_dir: Path, secrets: tuple[str, ...] = ()) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    def redacted(text):
        for secret in secrets:
            if secret:
                text = text.replace(secret, "[REDACTED]")
        return text
    (output_dir / "results.json").write_text(redacted(json.dumps(report, ensure_ascii=False, indent=2)), encoding="utf-8")
    lines = ["# 재난문자 AI 실제 모델 평가", "", f"- 상태: {report['status']}",
             f"- 모델: `{report['model']}`", f"- 장소 검색: {report['place_search_mode']}",
             "- 창작 예문 평가이며 실제 재난·발송 실적이 아닙니다.",
             "- 아래 통과는 지정한 점검 항목의 결과입니다. 전체 의미·장소 후보는 사람이 검토해야 합니다.",
             "- 실제 과금은 OpenAI Usage에서 확인합니다. 토큰 수를 비용으로 단정하지 않습니다.", "",
             "| 예문 | 점검 결과 | API 요청 | 입력 토큰 | 출력 토큰 | 처리 시간 | 장소 후보 | 시설 조회 |", "|---|---|---:|---:|---:|---:|---:|---:|"]
    if report.get("reassessment"):
        lines[2:2] = ["- 기존 실제 API 응답 재평가입니다. 추가 OpenAI/Kakao 호출은 0건이며, 아래 사용량·시간은 원본 실행 값입니다."]
    for row in report["cases"]:
        usage = row["usage"]
        result = row.get("result", {})
        lookups = sum(step["tool"] == "find_nearby_facilities" and step["status"] == "ok" for step in result.get("trace", []))
        lines.append(f"| {row['label']} | {row['status']} | {usage['requests']} | {usage['input_tokens']} | {usage['output_tokens']} | {row['elapsed_ms']/1000:.1f}s | {len(result.get('candidates', []))} | {lookups} |")
    if report.get("error"):
        lines.extend(["", report["error"]])
    for row in report["cases"]:
        failed = [name for name, passed in row.get("checks", {}).items() if not passed]
        if failed:
            lines.extend(["", f"- {row['label']} 확인 필요: {', '.join(failed)}"])
        if row.get("error"):
            lines.extend(["", f"- {row['label']}: {row['error']}"])
    lines.extend(["", "분류·원문 인용·장소 역할·확인 질문·조회 과정의 전체 결과는 results.json에 있습니다.",
                  "장소 검색이 꺼진 실행에서는 실제 위치·주변 시설 조회 품질은 미검증입니다.", ""])
    (output_dir / "summary.md").write_text(redacted("\n".join(lines)), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="유료 OpenAI API 호출을 명시적으로 허용")
    parser.add_argument("--case", choices=("all", *CASE_IDS), default="all")
    parser.add_argument("--with-places", action="store_true", help="Kakao REST 키로 실제 장소 검색도 실행")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "output/message-evaluation")
    args = parser.parse_args(argv)
    if not args.live:
        parser.error("실제 API 평가는 --live를 지정해야 합니다.")
    client = OpenAIResponsesClient.from_environment()
    places = KakaoPlaceSearch.from_environment() if args.with_places else KakaoPlaceSearch("")
    report = {"report_version": 1, "evaluated_at": dt.datetime.now(KST).isoformat(),
              "model": client.model, "reasoning_effort": client.reasoning_effort,
              "status": "error", "cases": [], "human_review_required": True,
              "place_search_mode": "live" if args.with_places else "disabled"}
    if not client.configured:
        report["error"] = "GitHub Repository secret OPENAI_API_KEY가 설정되지 않았습니다."
    elif args.with_places and not places.configured:
        report["error"] = "장소 검색을 요청했지만 KAKAO_REST_API_KEY가 없습니다."
    else:
        try:
            examples = json.loads((ROOT / "field_web/src/messageExamples.json").read_text(encoding="utf-8"))
            selected = select_examples(examples, args.case)
            facilities = CsvFacilityRepository(ROOT / "facilities_info.csv").list_monitored()
            service = MessageAnalysisService(client, places, lambda: facilities)
            report["cases"] = evaluate(selected, service, client, with_places=args.with_places)
            report["status"] = "pass" if len(report["cases"]) == len(selected) and all(row["status"] == "pass" for row in report["cases"]) else "needs_review"
        except Exception:
            report["error"] = "평가 준비 오류. 원본 예외·설정값은 기록하지 않았습니다."
    write_report(report, args.output_dir, tuple(os.getenv(key, "") for key in ("OPENAI_API_KEY", "KAKAO_REST_API_KEY")))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
