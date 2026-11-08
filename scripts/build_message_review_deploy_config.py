"""Prepare opt-in Cloud Run bindings without reading keys or contacting any service."""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
from pathlib import Path


def build_config(env):
    def enabled(name):
        value = env.get(name, "false").strip()
        if value not in {"true", "false"}:
            raise ValueError(f"{name}: true 또는 false를 설정해 주세요.")
        return value == "true"

    def version(name):
        value = env.get(name, "").strip()
        if not re.fullmatch(r"[1-9][0-9]{0,18}", value):
            raise ValueError(f"{name}: 승인한 Secret Manager 버전 번호가 필요합니다.")
        return value

    bindings = []
    collection = enabled("MESSAGE_COLLECTION_ENABLED")
    verified = enabled("MESSAGE_COLLECTION_CONTRACT_VERIFIED")
    settings = ["MESSAGE_REVIEW_STORE=firestore", f"MESSAGE_COLLECTION_ENABLED={str(collection).lower()}",
                f"MESSAGE_COLLECTION_CONTRACT_VERIFIED={str(verified).lower()}"]
    for name, default, lower, upper in (("MESSAGE_ANALYSIS_DAILY_LIMIT", 20, 1, 100),
                                       ("MESSAGE_COLLECTION_MAX_PAGES", 20, 1, 50),
                                       ("MESSAGE_COLLECTION_CATCHUP_DAYS", 7, 2, 30)):
        value = env.get(name, str(default)).strip() or str(default)
        if not re.fullmatch(r"[0-9]+", value) or not lower <= int(value) <= upper:
            raise ValueError(f"{name}: 허용 범위의 정수가 필요합니다.")
        settings.append(f"{name}={int(value)}")
    raw_start = env.get("MESSAGE_COLLECTION_START_AT", "").strip()
    if raw_start:
        try:
            start = dt.datetime.fromisoformat(raw_start)
            if start.tzinfo is None:
                raise ValueError()
        except ValueError:
            raise ValueError("MESSAGE_COLLECTION_START_AT: 시간대가 있는 ISO 시각이 필요합니다.") from None
        settings.append("MESSAGE_COLLECTION_START_AT=" + start.isoformat())
    if collection and not (verified and enabled("MESSAGE_REVIEW_AI_ENABLED") and enabled("MESSAGE_REVIEW_FEED_ENABLED")):
        raise ValueError("MESSAGE_COLLECTION_ENABLED: API 계약 확인과 AI·공식 피드 연결이 모두 필요합니다.")
    if enabled("MESSAGE_REVIEW_AI_ENABLED"):
        bindings += ["OPENAI_API_KEY=OPENAI_API_KEY:" + version("MESSAGE_REVIEW_OPENAI_VERSION"),
                     "KAKAO_REST_API_KEY=KAKAO_REST_API_KEY:" + version("MESSAGE_REVIEW_KAKAO_VERSION")]
        settings += ["OPENAI_MODEL=gpt-5.4-mini-2026-03-17", "OPENAI_REASONING_EFFORT=low"]
    if enabled("MESSAGE_REVIEW_FEED_ENABLED"):
        bindings += ["SAFETY_DATA_API_KEY=SAFETY_DATA_API_KEY:" + version("MESSAGE_REVIEW_FEED_VERSION")]
    return {"MESSAGE_REVIEW_SECRET_BINDINGS": ",".join(bindings), "MESSAGE_REVIEW_ENV_VARS": ",".join(settings)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--github-env", type=Path)
    args = parser.parse_args(argv)
    try:
        config = build_config(os.environ)
    except ValueError as error:
        # Authored error contains a fixed variable name, never the rejected value.
        print(str(error))
        return 2
    text = "".join(f"{key}={value}\n" for key, value in config.items())
    if args.github_env:
        with args.github_env.open("a") as stream:
            stream.write(text)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
