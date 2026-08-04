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


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str, timeout: float = 10) -> None:
        self.bot_token = bot_token.strip()
        self.chat_id = chat_id.strip()
        self.timeout = timeout

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
