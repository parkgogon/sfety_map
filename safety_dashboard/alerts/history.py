"""Read-only projection of weather, manual and official-message delivery records."""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
from collections import Counter
from dataclasses import asdict, dataclass

from safety_dashboard.application.message_pipeline import moment, stamp
from safety_dashboard.application.context_info import KST


@dataclass(frozen=True)
class HistoryRow:
    id: str
    processed_at: str
    source: str
    event: str
    status: str
    channel: str
    facility_count: int | None
    message_count: int | None
    detail: str
    record_id: str | None = None
    drill: bool = False
    sms_accepted: int = 0


def weather_row(event, values, processed_at):
    # Earlier versions retained the provider's exact success receipt as text.
    receipt = re.fullmatch(r"(\d+)건을 발송했습니다\.", event.detail.strip())
    count = int(receipt[1]) if receipt and event.status == "SENT" else None
    if event.source == "manual" and event.status == "SENT":
        count = values.get("message_count", count)
    channel = event.channel
    if values.get("telegram_fallback_queued"):
        channel = "SMS · 직원방 Telegram"
    return HistoryRow(event.id, stamp(processed_at), event.source, event.event,
                      event.status, channel, event.facility_count, count, event.detail,
                      drill=event.category == "DRILL" or values.get("mode") == "simulation",
                      sms_accepted=int(values.get("sms_accepted_count") or 0))


def staff_history(store, start, end):
    low, high = "MH|" + stamp(start), "MH|" + stamp(end)
    while True:
        rows = store.scan(low, high, 200)
        for row in rows:
            if row["destination"] != "staff_group":
                continue
            status = row["state"]
            if status == "sent" and not row.get("message_id"):
                status = "unknown"
            yield HistoryRow(row["id"], stamp(moment(row["updated_at"])), "disaster",
                             "재난문자 자동전파", status.upper(), "직원방 Telegram",
                             row.get("facility_count"), 1 if status == "sent" else None,
                             row.get("detail") or "", row.get("record_id"))
        if len(rows) < 200:
            return
        low = rows[-1]["queue_key"] + "\0"


def delivery_history(alert_store, message_store, start, end):
    lower = dt.datetime.combine(start, dt.time.min, tzinfo=KST)
    upper = dt.datetime.combine(end + dt.timedelta(days=1), dt.time.min, tzinfo=KST)
    rows = list(alert_store.history_rows(lower, upper))
    # A retry can move its history key forward between two scans.
    staff_rows = {r.id: r for r in staff_history(message_store, lower, upper)}
    rows.extend(staff_rows.values())
    rows.sort(key=lambda r: (r.processed_at, r.source, r.id), reverse=True)
    sent = Counter(r.source for r in rows if r.status == "SENT" and not r.drill)
    return {"from": start.isoformat(), "to": end.isoformat(),
            "sent": dict(sent), "sms_accepted": sum(r.sms_accepted for r in rows if not r.drill),
            "events": [asdict(r) for r in rows]}


def history_csv(report):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["처리 시각 (한국시간)", "출처", "이벤트", "상태", "채널", "대상 시설 수",
                     "Telegram 메시지 수", "SMS 접수 수", "훈련", "전파 ID"])
    for row in report["events"]:
        writer.writerow([moment(row["processed_at"]).astimezone(KST).isoformat(),
                         row["source"], row["event"], row["status"], row["channel"],
                         row["facility_count"], row["message_count"], row["sms_accepted"],
                         row["drill"], row["id"]])
    return output.getvalue().encode("utf-8-sig")
