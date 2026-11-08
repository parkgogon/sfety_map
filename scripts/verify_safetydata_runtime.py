"""Temporary IAM-private probe. Six requests maximum; no records, model or delivery."""
from __future__ import annotations

import datetime as dt
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os

try:
    from safetydata_probe_support import read_api, summarize, nodes, KST, CheckFailed
except ModuleNotFoundError:
    from scripts.check_safetydata_connection import read_api, summarize, nodes, KST, CheckFailed

PROVINCES = ("서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시", "울산광역시",
             "세종특별자치시", "경기도", "강원특별자치도", "충청북도", "충청남도", "전북특별자치도", "전라남도", "경상북도", "경상남도", "제주특별자치도")


def rows(payload):
    return [r for r in nodes(payload) if ("SN" in r or "sn" in r) and any(k in r for k in ("MSG_CN", "msgCn", "msg_cn"))]


def field(row, *names):
    return next((row[n] for n in names if n in row), None)


def identifier(row):
    return str(field(row, "SN", "sn"))


def issued_date(row):
    raw = str(field(row, "CRT_DT", "crtDt", "crt_dt") or "").replace("/", "-").replace(".", "-")
    try:
        value = dt.datetime.fromisoformat(raw)
    except ValueError:
        try:
            value = dt.datetime.strptime(raw, "%Y%m%d%H%M%S")
        except ValueError:
            return None
    return (value.replace(tzinfo=KST) if value.tzinfo is None else value.astimezone(KST)).date()


def probe(key, *, fetch=read_api, today=None):
    report = {"status": "inconclusive", "probe_origin": "cloud_run_runtime", "secret_version": "1",
              "api_calls": 0, "checks": {}, "requests": [], "records_written": 0, "model_calls": 0, "messages_sent": 0}
    today = today or dt.datetime.now(KST).date()

    def request(day, region=None, page=1):
        report["api_calls"] += 1
        payload = fetch(key, day, region=region, page=page, size=2)
        summary = summarize(payload)
        data = rows(payload)
        report["requests"].append({"date": day.isoformat() if day else None, "region": region, "page": page,
                                   "rows": summary["sample_rows"], "api_result": summary["api_result"]})
        return data

    try:
        if not key or len(key) > 16000 or any(c.isspace() for c in key):
            raise CheckFailed("runtime_secret_unavailable")
        baseline = []
        for offset in range(3):
            day = today-dt.timedelta(days=offset)
            baseline = request(day)
            if baseline:
                break
        if not baseline:
            control = request(None)
            report["reason"] = "no_sample_in_recent_three_days"
            if control:
                observed = [issued_date(r) for r in control]
                report["control_sample_dates"] = sorted({d.isoformat() for d in observed if d})
                report["status"] = "needs_contract_review"
                report["reason"] = "unfiltered_sample_requires_date_review"
            return report
        report["checks"]["date_filter_matches"] = all(issued_date(r) == day for r in baseline)
        other = request(day, page=2)
        report["checks"]["requested_page_size_matches"] = len(baseline) == 2 and len(other) == 2
        report["checks"]["second_page_has_rows"] = bool(other)
        report["checks"]["page_ids_disjoint"] = bool(other) and not ({identifier(r) for r in baseline} & {identifier(r) for r in other})
        report["checks"]["second_page_date_matches"] = bool(other) and all(issued_date(r) == day for r in other)
        recipients = str(field(baseline[0], "RCPTN_RGN_NM", "rcptnRgnNm") or "")
        region = next((p for p in PROVINCES if p in recipients), None)
        if region:
            selected = request(day, region=region)
            report["checks"]["region_filter_matches"] = bool(selected) and all(region in str(field(r, "RCPTN_RGN_NM", "rcptnRgnNm") or "") for r in selected)
        else:
            report["checks"]["region_filter_matches"] = False
        head = request(day)
        report["checks"]["head_stable"] = [identifier(r) for r in head] == [identifier(r) for r in baseline]
        # crtDt is a start date. Exercise the previous-day overlap used by collection.
        # If the baseline already came from an earlier day, it exercised this path.
        prior = request(today-dt.timedelta(days=1)) if day == today else baseline
        prior_start = today-dt.timedelta(days=1) if day == today else day
        observed = [issued_date(r) for r in prior]
        report["checks"]["prior_date_range_matches"] = all(d is not None and prior_start <= d <= today for d in observed)
        report["prior_date_sample_rows"] = len(prior)
        report["status"] = "passed" if all(report["checks"].values()) else "needs_contract_review"
    except CheckFailed as error:
        report.update(status="blocked", reason=str(error))
    except Exception:
        report.update(status="blocked", reason="probe_failed")
    return report


def handler_class(run_probe):
    """HTTPServer serializes requests; even a repeated POST uses the cached result."""
    class Handler(BaseHTTPRequestHandler):
        result = None

        def log_message(self, *_args):
            pass

        def do_GET(self):
            if self.path != "/health":
                self.send_error(404)
                return
            self.reply({"status": "ready"})

        def do_POST(self):
            if self.path != "/verify" or self.headers.get("Content-Length", "0") not in ("", "0"):
                self.send_error(400)
                return
            if type(self).result is None:
                try:
                    type(self).result = run_probe()
                except Exception:
                    type(self).result = {"status": "blocked", "reason": "probe_failed"}
            self.reply(type(self).result)

        def reply(self, value):
            data = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    return Handler


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", int(os.getenv("PORT", "8080"))), handler_class(lambda: probe(os.getenv("SAFETY_DATA_API_KEY", "")))).serve_forever()
