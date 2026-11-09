"""Telegram Bot API 발송 어댑터."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

import requests

from safety_dashboard.domain.models import OutgoingTelegramMessage


@dataclass(frozen=True)
class TelegramResult:
    success: bool
    sent_count: int
    total_count: int
    message: str


@dataclass(frozen=True)
class TelegramChatResult:
    success: bool
    title: str = ""
    message: str = ""


@dataclass(frozen=True)
class TelegramDeliveryResult:
    state: str
    message_id: int | None = None
    retry_after: int | None = None
    detail: str = ""


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str, timeout: float = 10) -> None:
        self.bot_token = bot_token.strip()
        self.chat_id = chat_id.strip()
        self.timeout = timeout

    @property
    def configured(self):
        return bool(self.bot_token and self.chat_id and not self.bot_token.startswith("YOUR_") and not self.chat_id.startswith("YOUR_"))

    def send_once(self, text: str) -> TelegramDeliveryResult:
        """One plain-text request. No retries, redirects, HTML or arbitrary error text.

        The existing weather send_batch contract is deliberately unchanged.
        A missing receipt or ambiguous transport error is never a confirmed failure.
        """
        if not self.configured:
            return TelegramDeliveryResult("rejected", detail="not_configured")
        if not text or len(text) > 3900:
            return TelegramDeliveryResult("rejected", detail="invalid_text")
        try:
            response = requests.post(f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                json={"chat_id": self.chat_id, "text": text, "link_preview_options": {"is_disabled": True}},
                timeout=(3, max(1, self.timeout-3)), allow_redirects=False)
            body = response.json()
            if not isinstance(body, dict):
                return TelegramDeliveryResult("unknown", detail="invalid_receipt")
            if response.status_code == 200 and body.get("ok") is True:
                receipt = body.get("result") or {}
                mid = receipt.get("message_id")
                actual_chat = (receipt.get("chat") or {}).get("id")
                if type(mid) is int and mid > 0 and str(actual_chat) == self.chat_id:
                    return TelegramDeliveryResult("sent", message_id=mid, detail="receipt_confirmed")
                return TelegramDeliveryResult("unknown", detail="invalid_receipt")
            code = body.get("error_code")
            if body.get("ok") is False and code == response.status_code:
                if code == 429:
                    retry = (body.get("parameters") or {}).get("retry_after")
                    if type(retry) is int and 1 <= retry <= 3600:
                        return TelegramDeliveryResult("rate_limited", retry_after=retry, detail="provider_rate_limit")
                if code in {400, 401, 403, 404, 429}:
                    return TelegramDeliveryResult("rejected", detail="provider_rejected")
        except (requests.RequestException, ValueError, TypeError, AttributeError):
            pass
        return TelegramDeliveryResult("unknown", detail="outcome_unknown")

    def check_chat(self) -> TelegramChatResult:
        """메시지를 게시하지 않고 봇의 Telegram 대화방 접근을 확인합니다."""

        if not self.bot_token or not self.chat_id:
            return TelegramChatResult(False, message="Telegram 설정값이 없습니다.")
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{self.bot_token}/getChat",
                json={"chat_id": self.chat_id},
                timeout=self.timeout,
            )
            response.raise_for_status()
            body = response.json()
            if not body.get("ok"):
                raise ValueError("Telegram API가 대화방 조회를 거부했습니다.")
            result = body.get("result") or {}
            return TelegramChatResult(
                True,
                title=str(result.get("title") or result.get("username") or "").strip(),
                message="대화방 접근 가능",
            )
        except (requests.RequestException, ValueError) as exc:
            return TelegramChatResult(
                False,
                message=f"대화방 접근 실패 ({type(exc).__name__})",
            )

    def send_batch(
        self,
        messages: Sequence[OutgoingTelegramMessage | str],
    ) -> TelegramResult:
        if not self.bot_token or not self.chat_id:
            return TelegramResult(False, 0, len(messages), "Telegram 설정값이 없습니다.")
        if self.bot_token == "YOUR_BOT_TOKEN_HERE" or self.chat_id == "YOUR_CHAT_ID_HERE":
            return TelegramResult(False, 0, len(messages), "Telegram 설정값을 실제 값으로 바꿔 주세요.")
        sent = 0
        for raw_message in messages:
            message = (
                raw_message
                if isinstance(raw_message, OutgoingTelegramMessage)
                else OutgoingTelegramMessage(text=str(raw_message))
            )
            request_data: dict[str, object] = {
                "chat_id": self.chat_id,
                "text": message.text,
                "parse_mode": "HTML",
                "disable_notification": message.silent,
                "link_preview_options": {"is_disabled": True},
            }
            if message.action_label and message.action_url:
                request_data["reply_markup"] = {
                    "inline_keyboard": [[{
                        "text": message.action_label,
                        "url": message.action_url,
                    }]]
                }
            try:
                response = requests.post(
                    f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                    json=request_data,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                if not response.json().get("ok"):
                    raise ValueError("Telegram API가 발송을 거부했습니다.")
            except (requests.RequestException, ValueError) as exc:
                return TelegramResult(
                    False, sent, len(messages),
                    f"{sent}/{len(messages)}건 발송 후 실패 ({type(exc).__name__})",
                )
            sent += 1
        return TelegramResult(True, sent, len(messages), f"{sent}건을 발송했습니다.")
