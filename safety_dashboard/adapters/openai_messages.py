"""OpenAI Responses transport. Credentials and raw errors never leave this adapter."""

import os
import requests

from safety_dashboard.application.message_analysis import AnalysisUnavailable
from safety_dashboard.config.environment import env_text

DEFAULT_MODEL = "gpt-5.4-mini-2026-03-17"


class OpenAIConnectionError(AnalysisUnavailable):
    """A transport/configuration error that should stop a paid evaluation batch."""


class OpenAIResponsesClient:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, *, reasoning_effort: str = "low", session=None):
        self._api_key = api_key
        self.model = model
        self.configured = bool(api_key)
        self.reasoning_effort = reasoning_effort if reasoning_effort in {"none", "low"} else "low"
        self._session = session or requests.Session()
        self._usage = dict.fromkeys(("requests", "usage_reports", "input_tokens", "cached_input_tokens", "output_tokens", "total_tokens"), 0)

    def usage_snapshot(self) -> dict[str, int]:
        return dict(self._usage)

    @classmethod
    def from_environment(cls):
        return cls(env_text("OPENAI_API_KEY"), os.getenv("OPENAI_MODEL", "").strip() or DEFAULT_MODEL,
                   reasoning_effort=os.getenv("OPENAI_REASONING_EFFORT", "low"))

    def respond(self, items, tools, instructions, timeout):
        if not self.configured:
            raise AnalysisUnavailable("서버에 OpenAI API 키가 아직 설정되지 않았습니다.")
        try:
            self._usage["requests"] += 1
            response = self._session.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                json={"model": self.model, "instructions": instructions, "input": items, "tools": tools,
                      "tool_choice": "required", "parallel_tool_calls": False, "store": False,
                      "include": ["reasoning.encrypted_content"], "reasoning": {"effort": self.reasoning_effort},
                      "max_output_tokens": 4000},
                timeout=(min(5, timeout / 2), max(1, timeout - min(5, timeout / 2))),
                allow_redirects=False,
            )
            if response.status_code == 429:
                raise OpenAIConnectionError("AI 서비스의 사용 한도에 도달했습니다. 결제·사용량 설정을 확인해 주세요.")
            if response.status_code != 200:
                messages = {
                    400: "AI 요청이 거절되었습니다 (HTTP 400). 모델과 도구 형식의 지원 여부를 확인해 주세요.",
                    401: "AI 인증에 실패했습니다 (HTTP 401). API 키를 확인해 주세요.",
                    403: "AI 사용 권한이 없습니다 (HTTP 403). 프로젝트·모델 권한을 확인해 주세요.",
                    404: "AI 모델 또는 API를 찾지 못했습니다 (HTTP 404). 모델 설정을 확인해 주세요.",
                }
                raise OpenAIConnectionError(messages.get(response.status_code, "AI 서비스 연결에 실패했습니다. 서버의 키·모델 설정을 확인해 주세요."))
            data = response.json()
            usage = data.get("usage")
            if isinstance(usage, dict):
                self._usage["usage_reports"] += 1
                for key in ("input_tokens", "output_tokens", "total_tokens"):
                    value = usage.get(key)
                    if isinstance(value, int) and value >= 0:
                        self._usage[key] += value
                cached = (usage.get("input_tokens_details") or {}).get("cached_tokens")
                if isinstance(cached, int) and cached >= 0:
                    self._usage["cached_input_tokens"] += cached
            if data.get("status") != "completed" or not isinstance(data.get("output"), list):
                raise AnalysisUnavailable("AI 응답을 완료하지 못했습니다. 입력을 줄여 다시 시도해 주세요.")
            return data["output"]
        except (requests.RequestException, ValueError, TypeError, AttributeError):
            raise OpenAIConnectionError("AI 서비스가 응답하지 못했습니다. 잠시 후 다시 시도해 주세요.") from None
