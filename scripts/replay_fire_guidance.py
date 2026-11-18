"""Compare one candidate policy against saved official records in a private verifier."""
from __future__ import annotations

import datetime as dt
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import logging
import os
from pathlib import Path

from google.cloud import firestore
from safety_dashboard.adapters.facility_csv import CsvFacilityRepository
from safety_dashboard.adapters.kakao_places import KakaoPlaceSearch
from safety_dashboard.application.message_address import message_parcel
from safety_dashboard.application.message_fire import fire_guidance
from safety_dashboard.application.nearby_report import NearbyReport
from safety_dashboard.domain.models import GeoPoint

KST = dt.timezone(dt.timedelta(hours=9))


def replay(baseline, candidate):
    client = firestore.Client(project="keco-safety-map")
    snapshots = list(client.collection("disaster_message_reviews")
                     .order_by("sort_key", direction=firestore.Query.DESCENDING).limit(100).stream(timeout=15))
    catalog = CsvFacilityRepository(Path("/app/facilities_info.csv")).snapshot()
    report = {"status": "passed", "scanned": len(snapshots), "scan_limit_reached": len(snapshots) == 100,
              "official_records": 0, "fire_records": 0, "fire_records_with_analysis": 0,
              "old_policy": {}, "candidate_policy": {}, "changes": [],
              "documents_written": 0, "model_calls": 0, "messages_sent": 0, "kakao_calls": 0,
              "checked_at": dt.datetime.now(KST).isoformat()}
    for snap in snapshots:
        record = snap.to_dict()
        if record.get("origin") != "official":
            continue
        report["official_records"] += 1
        source = record["message"]
        text = source["text"]
        if "화재" not in text and "산불" not in text:
            continue
        report["fire_records"] += 1
        case = "beommul_fire" if "범물동 613" in text else "other_fire"
        issued = dt.datetime.fromisoformat(source["issued_at"]).astimezone(KST)
        if record.get("analysis_state") != "completed":
            continue
        report["fire_records_with_analysis"] += 1
        evaluated_at = issued + dt.timedelta(minutes=10)
        before, after = (fn(record, catalog, now=evaluated_at) for fn in (baseline, candidate))
        for key, result in (("old_policy", before), ("candidate_policy", after)):
            decision = result["decision"]
            report[key][decision] = report[key].get(decision, 0) + 1
        if before["decision"] != after["decision"]:
            attempted = record.get("analysis_attempted_at")
            at_processing = candidate(record, catalog, now=dt.datetime.fromisoformat(attempted)) if attempted else {}
            guidance = fire_guidance(text)
            report["changes"].append({"case": case, "issued": issued.isoformat(), "area": guidance.location if guidance else None,
                                      "old_decision": before["decision"], "candidate_decision": after["decision"],
                                      "candidate_at_processing": at_processing.get("decision"),
                                      "distance_fields": len(after["facilities"])})
        if case == "beommul_fire" and report["kakao_calls"] == 0:
            parcel = message_parcel(text)
            if not parcel:
                report["beommul_address"] = "source_parcel_unavailable"
                continue
            report["kakao_calls"] = 1
            try:
                places = KakaoPlaceSearch.from_environment().search_address(parcel.query, 6)
            except Exception:
                report["beommul_address"] = "lookup_unavailable"
                continue
            exact = {(p["latitude"], p["longitude"]): p for p in places if parcel.matches(p["address"])}
            if len(exact) != 1:
                report["beommul_address"] = "unconfirmed"
                continue
            report["beommul_address"] = "exact_match"
            coordinates, place = next(iter(exact.items()))
            nearby = NearbyReport.build(GeoPoint(*coordinates), place["name"], place["address"], 3,
                                        (f for f in catalog[1] if f.is_monitored))
            report["beommul_nearby_count"] = len(nearby.facilities)
            report["beommul_nearest_distance_m"] = round(nearby.facilities[0].meters) if nearby.facilities else None
    return report


def serve(baseline, candidate):
    class Handler(BaseHTTPRequestHandler):
        result = None

        def log_message(self, *_args):
            pass

        def do_POST(self):
            if self.path != "/verify" or self.headers.get("Content-Length", "0") != "0":
                self.send_error(400)
                return
            if type(self).result is None:
                try:
                    type(self).result = replay(baseline, candidate)
                except Exception as error:
                    type(self).result = {"status": "blocked", "error": type(error).__name__}
            data = json.dumps(self.result, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    logging.disable(logging.CRITICAL)
    HTTPServer(("0.0.0.0", int(os.getenv("PORT", "8080"))), Handler).serve_forever()
