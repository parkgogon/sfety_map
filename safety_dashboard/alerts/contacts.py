"""Google Sheet 연락처 행의 검증과 정규화."""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence

from safety_dashboard.alerts.domain import ContactDirectory, FacilityRecipient


class ContactDataError(ValueError):
    pass


REQUIRED_COLUMNS = ("facility_id", "recipient_name", "phone", "active")
_TRUE = {"1", "true", "yes", "y", "on", "활성", "사용"}
_FALSE = {"0", "false", "no", "n", "off", "비활성", "미사용", ""}


def build_contact_directory(
    rows: Iterable[Mapping[str, object]],
    valid_facility_ids: Sequence[str],
    fetched_at: dt.datetime,
) -> ContactDirectory:
    valid_ids = set(valid_facility_ids)
    recipients: list[FacilityRecipient] = []
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    for index, raw in enumerate(rows, start=2):
        row = {str(key).strip(): str(value or "").strip() for key, value in raw.items()}
        missing = [key for key in REQUIRED_COLUMNS if key not in row]
        if missing:
            raise ContactDataError("연락처 표 필수 열이 없습니다: " + ", ".join(missing))
        try:
            active = parse_active(row["active"])
        except ContactDataError as exc:
            errors.append(f"{index}행 {exc}")
            continue
        if not active:
            continue
        facility_id = row["facility_id"].removesuffix(".0")
        recipient_name = row["recipient_name"]
        if facility_id not in valid_ids:
            errors.append(f"{index}행 등록되지 않은 시설코드")
            continue
        if not recipient_name:
            errors.append(f"{index}행 담당자 식별명 누락")
            continue
        try:
            phone = normalize_mobile_phone(row["phone"])
        except ContactDataError as exc:
            errors.append(f"{index}행 {exc}")
            continue
        dedupe_key = (facility_id, phone)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        recipients.append(
            FacilityRecipient(
                facility_id=facility_id,
                recipient_name=recipient_name,
                phone=phone,
                note=row.get("note", ""),
            )
        )
    if errors:
        preview = "; ".join(errors[:5])
        suffix = f" 외 {len(errors) - 5}건" if len(errors) > 5 else ""
        raise ContactDataError(f"연락처 표 검증 실패: {preview}{suffix}")
    if not recipients:
        raise ContactDataError("활성 연락처가 없습니다.")
    recipients.sort(key=lambda item: (item.facility_id, item.phone))
    revision_source = "\n".join(
        f"{item.facility_id}|{item.recipient_name}|{item.phone}|{item.note}"
        for item in recipients
    )
    return ContactDirectory(
        recipients=tuple(recipients),
        revision=hashlib.sha256(revision_source.encode("utf-8")).hexdigest()[:16],
        fetched_at=fetched_at,
    )


def normalize_mobile_phone(value: object) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if digits.startswith("82"):
        digits = "0" + digits[2:]
    if not re.fullmatch(r"01[016789]\d{7,8}", digits):
        raise ContactDataError("국내 휴대전화 번호 형식 오류")
    return digits


def parse_active(value: object) -> bool:
    normalized = str(value or "").strip().casefold()
    if normalized in _TRUE:
        return True
    if normalized in _FALSE:
        return False
    raise ContactDataError("active 값은 TRUE 또는 FALSE여야 합니다.")
