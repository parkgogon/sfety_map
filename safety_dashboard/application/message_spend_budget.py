"""Durable pre-HTTP reservations. Integer nanodollars; no credentials or message text."""
from __future__ import annotations

import datetime as dt
import uuid

UTC = dt.timezone.utc
KST = dt.timezone(dt.timedelta(hours=9))
MODEL = "gpt-5.4-mini-2026-03-17"
RATE_VERSION = "openai-standard-2026-11-09-mini-v1"
NANO = 1_000_000_000
INPUT_RATE, CACHED_RATE, OUTPUT_RATE = 750, 75, 4500
MAX_INPUT, MAX_OUTPUT = 400_000, 4000
RESERVATION = MAX_INPUT*INPUT_RATE + MAX_OUTPUT*OUTPUT_RATE
CONTRACT_KEY = "message-spend-contract"


def stamp(value):
    return value.astimezone(UTC).isoformat(timespec="microseconds")


class SpendBudgetLimit(RuntimeError):
    def __init__(self, retry_at):
        super().__init__("문자 AI 비용 한도에 도달했습니다. 원문과 대기 기록은 보존됩니다.")
        self.retry_at = retry_at


class SpendBudgetUnavailable(RuntimeError):
    pass


class MessageSpendBudget:
    """One ledger shared by manual/API/worker. Unknown outcomes retain the full reserve.

    Only the pinned model, default service tier, text input and local function tools
    are priced. The full model input window plus our output cap is reserved before
    each response, then reconciled using provider usage (including reasoning).
    """
    def __init__(self, store, *, daily_cents=100, monthly_cents=2000, now=lambda: dt.datetime.now(UTC)):
        if not 1 <= daily_cents <= 100_000 or not 1 <= monthly_cents <= 1_000_000:
            raise ValueError("문자 AI 예산 범위를 확인해 주세요.")
        self.store, self.now = store, now
        self.limits = (daily_cents*10_000_000, monthly_cents*10_000_000)

    def _periods(self, now=None):
        now = (now or self.now()).astimezone(KST)
        day_end = (now+dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        month_end = (now.replace(day=28)+dt.timedelta(days=4)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return (("message-spend-day-"+now.date().isoformat(), stamp(day_end)),
                ("message-spend-month-"+now.strftime("%Y-%m"), stamp(month_end)))

    def _check(self, values, periods, model):
        if model != MODEL or (values[CONTRACT_KEY] or {}).get("blocked"):
            raise SpendBudgetUnavailable("AI 비용 계산 기준을 확인하지 못해 호출을 중단했습니다.")
        waits = []
        for (key, reset), limit in zip(periods, self.limits):
            usage = values[key] or {}
            if usage.get("settled_nano", 0)+usage.get("reserved_nano", 0)+RESERVATION > limit:
                waits.append(reset)
        if waits:
            raise SpendBudgetLimit(max(waits))

    def check(self, model=MODEL):
        periods = self._periods()
        keys = [CONTRACT_KEY, *[p[0] for p in periods]]
        try:
            self.store.run(keys, lambda values: (self._check(values, periods, model) or {}, None))
        except (SpendBudgetLimit, SpendBudgetUnavailable):
            raise
        except Exception:
            raise SpendBudgetUnavailable("AI 비용 원장을 확인하지 못해 호출을 시작하지 않았습니다.") from None

    def reserve(self, model, *, source_fingerprint=""):
        now = self.now()
        periods = self._periods(now)
        call_id = "message-spend-call-"+uuid.uuid4().hex
        keys = [CONTRACT_KEY, call_id, *[p[0] for p in periods]]

        def reserve(values):
            self._check(values, periods, model)
            writes = {call_id: {"id": call_id, "state": "reserved", "model": model, "rate_version": RATE_VERSION,
                      "reserved_nano": RESERVATION, "period_keys": [p[0] for p in periods], "started_at": stamp(now),
                      "source_fingerprint": source_fingerprint}}
            for key, _ in periods:
                usage = dict(values[key] or {})
                usage.update(reserved_nano=usage.get("reserved_nano", 0)+RESERVATION,
                             calls=usage.get("calls", 0)+1, unsettled_calls=usage.get("unsettled_calls", 0)+1)
                writes[key] = usage
            return writes, call_id

        try:
            return self.store.run(keys, reserve)
        except (SpendBudgetLimit, SpendBudgetUnavailable):
            raise
        except Exception:
            raise SpendBudgetUnavailable("AI 비용을 예약하지 못해 호출을 시작하지 않았습니다.") from None

    def settle(self, call_id, usage):
        """Missing/invalid usage never releases a reservation. Idempotent by call ID."""
        try:
            call = self.store.get(call_id)
            if not call:
                raise ValueError("missing_reservation")
            if not isinstance(usage, dict):
                raise ValueError("missing_usage")
            incoming, outgoing = usage.get("input_tokens"), usage.get("output_tokens")
            details = usage.get("input_tokens_details")
            cached = details.get("cached_tokens", 0) if isinstance(details, dict) else 0
            if any(type(n) is not int for n in (incoming, outgoing, cached)) or not (0 <= cached <= incoming <= MAX_INPUT and 0 <= outgoing <= MAX_OUTPUT):
                # A changed provider contract cannot silently create cheap/zero usage.
                self.store.run([CONTRACT_KEY], lambda values: ({CONTRACT_KEY: {"blocked": True, "reason": "invalid_usage", "at": stamp(self.now())}}, None))
                raise ValueError("usage_contract")
            amount = (incoming-cached)*INPUT_RATE + cached*CACHED_RATE + outgoing*OUTPUT_RATE
            periods = call["period_keys"]

            def settle(values):
                current = values[call_id]
                if current.get("state") == "settled":
                    return {}, None
                writes = {call_id: {**current, "state": "settled", "settled_nano": amount,
                          "input_tokens": incoming, "cached_input_tokens": cached, "output_tokens": outgoing,
                          "settled_at": stamp(self.now())}}
                for key in periods:
                    value = dict(values[key])
                    value.update(reserved_nano=value["reserved_nano"]-current["reserved_nano"],
                                 settled_nano=value.get("settled_nano", 0)+amount,
                                 unsettled_calls=value["unsettled_calls"]-1)
                    for name, tokens in (("input_tokens", incoming), ("cached_input_tokens", cached), ("output_tokens", outgoing)):
                        value[name] = value.get(name, 0)+tokens
                    writes[key] = value
                return writes, None
            self.store.run([call_id, *periods], settle)
        except Exception:
            raise SpendBudgetUnavailable("AI 사용량 정산을 확인하지 못했습니다. 예약 금액을 유지하며 자동 재시도하지 않습니다.") from None

    def status(self):
        periods = self._periods()
        result = {"enabled": True, "currency": "USD", "rate_version": RATE_VERSION, "reservation_usd": RESERVATION/NANO,
                  "model": MODEL, "blocked": bool((self.store.get(CONTRACT_KEY) or {}).get("blocked"))}
        for name, (key, reset), limit in zip(("daily", "monthly"), periods, self.limits):
            value = self.store.get(key) or {}
            spent, reserved = value.get("settled_nano", 0), value.get("reserved_nano", 0)
            result[name] = {"limit_usd": limit/NANO, "settled_usd": spent/NANO, "reserved_usd": reserved/NANO,
                            "remaining_usd": max(0, limit-spent-reserved)/NANO, "unsettled_calls": value.get("unsettled_calls", 0),
                            "calls": value.get("calls", 0), "input_tokens": value.get("input_tokens", 0),
                            "cached_input_tokens": value.get("cached_input_tokens", 0), "output_tokens": value.get("output_tokens", 0),
                            "reset_at": reset}
        result["can_start"] = not result["blocked"] and all(result[n]["remaining_usd"] >= result["reservation_usd"] for n in ("daily", "monthly"))
        return result
