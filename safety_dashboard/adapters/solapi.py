"""SOLAPI 문자 발송 어댑터."""

from __future__ import annotations

from typing import Any

from safety_dashboard.alerts.domain import (
    OutgoingSmsMessage,
    SmsDeliveryResult,
    SmsDeliveryStatus,
)


class SolapiNotifier:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        sender_number: str,
        *,
        service: Any | None = None,
    ) -> None:
        self.api_key = api_key.strip()
        self.api_secret = api_secret.strip()
        self.sender_number = "".join(filter(str.isdigit, sender_number))
        self._service = service
        self._request_type = getattr(service, "request_type", None)
        self._request_config_type = getattr(
            service,
            "request_config_type",
            None,
        )

    def send(self, message: OutgoingSmsMessage) -> SmsDeliveryResult:
        return self.send_many((message,))[0]

    def send_many(
        self,
        messages: tuple[OutgoingSmsMessage, ...],
    ) -> tuple[SmsDeliveryResult, ...]:
        if not messages:
            return ()
        if not self.api_key or not self.api_secret or not self.sender_number:
            result = SmsDeliveryResult(
                SmsDeliveryStatus.FAILED,
                detail="SOLAPI 설정값이 없습니다.",
            )
            return tuple(result for _ in messages)
        try:
            service, request_type, request_config_type = self._client()
            requests = [
                request_type(
                    from_=self.sender_number,
                    to=item.phone,
                    text=item.text,
                    customFields={
                        "deliveryId": item.id,
                        "batchId": item.batch_id,
                    },
                )
                for item in messages
            ]
            payload = requests[0] if len(requests) == 1 else requests
            if request_config_type is None:
                response = service.send(payload)
            else:
                # SOLAPI는 이 옵션이 없으면 정상 접수여도 messageList를
                # 생략한다. 메시지 ID가 있어야 웹훅 결과를 내부 발송 건과
                # 안전하게 연결할 수 있다.
                response = service.send(
                    payload,
                    request_config_type(show_message_list=True),
                )
        except Exception as exc:
            if type(exc).__name__ == "MessageNotReceivedError":
                failed_messages = getattr(exc, "failed_messages", ()) or ()
                return _registration_failures(messages, failed_messages)
            # 요청이 플랫폼에 도달한 뒤 응답만 유실됐을 수 있으므로 자동 재시도하지 않는다.
            result = SmsDeliveryResult(
                SmsDeliveryStatus.UNKNOWN,
                detail=f"SOLAPI 응답 확인 불가 ({type(exc).__name__})",
            )
            return tuple(result for _ in messages)

        group = _value(response, "group_info", "groupInfo")
        group_id = str(_value(group, "group_id", "groupId") or "")
        message_list = _value(response, "message_list", "messageList") or []
        failed_list = _value(response, "failed_message_list", "failedMessageList") or []
        results: dict[str, SmsDeliveryResult] = {}
        for item in message_list:
            delivery_id = _delivery_id(item)
            if not delivery_id and len(messages) == 1:
                delivery_id = messages[0].id
            if delivery_id:
                results[delivery_id] = SmsDeliveryResult(
                    SmsDeliveryStatus.ACCEPTED,
                    provider_message_id=str(
                        _value(item, "message_id", "messageId") or ""
                    ),
                    provider_group_id=group_id,
                    detail="SOLAPI 정상 접수",
                )
        for item in failed_list:
            delivery_id = _delivery_id(item)
            if not delivery_id and len(messages) == 1:
                delivery_id = messages[0].id
            if delivery_id:
                results[delivery_id] = SmsDeliveryResult(
                    SmsDeliveryStatus.FAILED,
                    provider_message_id=str(
                        _value(item, "message_id", "messageId") or ""
                    ),
                    provider_group_id=group_id,
                    detail="SOLAPI 접수 거부",
                )
        unknown = SmsDeliveryResult(
            SmsDeliveryStatus.UNKNOWN,
            provider_group_id=group_id,
            detail="SOLAPI 응답에 메시지 결과가 없습니다.",
        )
        return tuple(results.get(item.id, unknown) for item in messages)

    def _client(self) -> tuple[Any, Any, Any]:
        if self._service is not None:
            return (
                self._service,
                self._request_type or _FallbackRequestMessage,
                self._request_config_type,
            )
        from solapi import SolapiMessageService
        from solapi.model import RequestMessage, SendRequestConfig

        self._service = SolapiMessageService(
            api_key=self.api_key,
            api_secret=self.api_secret,
        )
        self._request_type = RequestMessage
        self._request_config_type = SendRequestConfig
        return self._service, self._request_type, self._request_config_type


class _FallbackRequestMessage:
    def __init__(self, **values: object) -> None:
        self.values = values


def _value(value: Any, *names: str) -> Any:
    if value is None:
        return None
    for name in names:
        if isinstance(value, dict) and name in value:
            return value[name]
        if hasattr(value, name):
            return getattr(value, name)
    return None


def _delivery_id(value: Any) -> str:
    fields = _value(value, "custom_fields", "customFields") or {}
    return str(_value(fields, "deliveryId", "delivery_id") or "")


def _registration_failures(
    messages: tuple[OutgoingSmsMessage, ...],
    failed_messages: Any,
) -> tuple[SmsDeliveryResult, ...]:
    results: dict[str, SmsDeliveryResult] = {}
    failed_values = list(failed_messages)
    for index, item in enumerate(failed_values):
        delivery_id = _delivery_id(item)
        if not delivery_id and index < len(messages):
            delivery_id = messages[index].id
        results[delivery_id] = SmsDeliveryResult(
            SmsDeliveryStatus.FAILED,
            provider_message_id=str(
                _value(item, "message_id", "messageId") or ""
            ),
            detail="SOLAPI 접수 거부",
        )
    fallback = SmsDeliveryResult(
        SmsDeliveryStatus.FAILED,
        detail="SOLAPI 접수 거부",
    )
    return tuple(results.get(item.id, fallback) for item in messages)
