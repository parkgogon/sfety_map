from __future__ import annotations

import functools
import re
from fastapi import APIRouter, Cookie, Header, HTTPException, Query, Response, Depends

from safety_dashboard.admin.session import AdminSessionManager
from safety_dashboard.adapters.disaster_messages import DisasterMessageDataError
from safety_dashboard.adapters.facility_csv import FacilityDataError
from safety_dashboard.application.message_records import (
    RegisterMessage, AnalyzeRecord, SaveRecordNote, RecordConflict, RecordNotFound,
)
from safety_dashboard.application.message_feed import FeedRequest, ImportOfficial
from safety_dashboard.application.message_spatial import SaveMessageReference, SaveMessageSelection, LocationKey, Digest, SpatialValidationError
from safety_dashboard.application.message_review import CompleteMessageReview, ReopenMessageReview, SaveMessageNotice, CopyMessageNotice, ReviewValidationError
from safety_dashboard.application.message_relations import LinkMessage, UnlinkMessage, RelationValidationError
from safety_dashboard.application.message_preparation import MessagePreparationService, PrepareMessageReview, ApprovePreparedReview
from typing import Literal
from safety_dashboard.application.message_analysis import AnalysisBusy, AnalysisUnavailable

NO_STORE = {"Cache-Control": "private, no-store"}


def build_router(services):
    preparation = MessagePreparationService(services.message_review)
    def authorize(response: Response,
                  token: str = Header("", alias="X-Alert-Admin-Token"),
                  cookie: str = Cookie("", alias=AdminSessionManager.COOKIE_NAME)):
        response.headers.update(NO_STORE)
        if services.admin_access.settings.password:
            for value in (token, cookie):
                if not value:
                    continue
                try:
                    services.session_manager.verify_token(value)
                    return
                except ValueError:
                    continue
        raise HTTPException(403, "관리자 인증이 필요합니다.", headers=NO_STORE)

    router = APIRouter(prefix="/internal/v1/message-records", dependencies=[Depends(authorize)])

    def guarded(fn):
        @functools.wraps(fn)
        def run(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except RecordNotFound:
                raise HTTPException(404, "검토 기록을 찾을 수 없습니다.", headers=NO_STORE) from None
            except RecordConflict as error:
                raise HTTPException(409, str(error), headers=NO_STORE) from None
            except AnalysisBusy as error:
                raise HTTPException(429, str(error), headers={**NO_STORE, "Retry-After": "20"}) from None
            except AnalysisUnavailable as error:
                raise HTTPException(503, str(error), headers=NO_STORE) from None
            except DisasterMessageDataError:
                raise HTTPException(503, "공식 문자 조회에 실패했습니다. 이전 목록과 저장 기록은 유지됩니다.", headers=NO_STORE) from None
            except (SpatialValidationError, ReviewValidationError, RelationValidationError) as error:
                raise HTTPException(422, str(error), headers=NO_STORE) from None
            except FacilityDataError:
                raise HTTPException(503, "시설 자료를 읽지 못했습니다. 이전 기록을 보존합니다.", headers=NO_STORE) from None
            except ValueError:
                # Domain validation errors only; provider errors are kept generic below.
                raise HTTPException(422, "입력 값 또는 공식 문자 확인 정보를 확인해 주세요.", headers=NO_STORE) from None
            except Exception:
                raise HTTPException(503, "조회 또는 저장을 완료하지 못했습니다. 마지막 저장 기록을 다시 확인해 주세요.", headers=NO_STORE) from None
        return run

    def check_id(identifier):
        if not re.fullmatch(r"(?:manual-[a-f0-9]{32}|official-[a-f0-9]{64})", identifier):
            raise RecordNotFound(identifier)
        return identifier

    @router.get("/status")
    def status():
        return {**services.message_records.availability(), "feed_configured": services.message_feed.provider.configured,
                "auto_collection_enabled": False}

    @router.get("")
    @guarded
    def records(before: str | None = Query(None, max_length=160), limit: int = Query(20, ge=1, le=50)):
        return services.message_records.list_page(before, limit)

    @router.post("")
    @guarded
    def register(request: RegisterMessage):
        return services.message_records.register_manual(request)

    @router.post("/feed")
    @guarded
    def feed(request: FeedRequest):
        return services.message_feed.fetch(request)

    @router.post("/import")
    @guarded
    def import_message(request: ImportOfficial):
        message, identifier, fetched_at = services.message_feed.verify(request.import_token)
        return services.message_records.register_official(message, identifier, fetched_at)

    @router.get("/{identifier}")
    @guarded
    def detail(identifier: str):
        return services.message_records.get(check_id(identifier))

    @router.get("/{identifier}/history")
    @guarded
    def history(identifier: str, before: int | None = Query(None, ge=1)):
        services.message_records.get(check_id(identifier))
        rows = services.message_records.store.history(identifier, before, 11)
        return {"versions": rows[:10], "next_cursor": rows[9]["record"]["version"] if len(rows) > 10 else None}

    @router.patch("/{identifier}")
    @guarded
    def save(identifier: str, request: SaveRecordNote):
        return services.message_records.save_note(check_id(identifier), request)

    @router.post("/{identifier}/analyze")
    @guarded
    def analyze(identifier: str, request: AnalyzeRecord):
        return services.message_records.analyze(check_id(identifier), request)

    @router.get("/{identifier}/spatial")
    @guarded
    def spatial(identifier: str):
        return services.message_spatial.detail(check_id(identifier))

    @router.post("/{identifier}/reference")
    @guarded
    def reference(identifier: str, request: SaveMessageReference):
        return services.message_spatial.save_reference(check_id(identifier), request)

    @router.get("/{identifier}/facilities")
    @guarded
    def facilities(identifier: str, location_key: LocationKey, expected_version: int = Query(ge=1),
                   offset: int = Query(0, ge=0, le=10000), limit: int = Query(20, ge=1, le=50),
                   scope: Literal["nearby", "all"] = "nearby", query: str = Query("", max_length=120),
                   catalog_digest: Digest | None = None):
        return services.message_spatial.facilities_page(check_id(identifier), location_key, expected_version,
                   offset=offset, limit=limit, scope=scope, query=query, catalog_digest=catalog_digest)

    @router.post("/{identifier}/selection")
    @guarded
    def selection(identifier: str, request: SaveMessageSelection):
        return services.message_spatial.save_selection(check_id(identifier), request)

    @router.get("/{identifier}/review")
    @guarded
    def review(identifier: str):
        return services.message_review.detail(check_id(identifier))

    @router.post("/{identifier}/prepare")
    @guarded
    def prepare(identifier: str, request: PrepareMessageReview):
        return preparation.prepare(check_id(identifier), request)

    @router.post("/{identifier}/approve")
    @guarded
    def approve(identifier: str, request: ApprovePreparedReview):
        return preparation.approve(check_id(identifier), request)

    @router.post("/{identifier}/hold")
    @guarded
    def hold(identifier: str, request: PrepareMessageReview):
        return preparation.hold(check_id(identifier), request)

    @router.get("/{identifier}/related")
    @guarded
    def related(identifier: str):
        return services.message_relations.detail(check_id(identifier))

    @router.get("/{identifier}/related/candidates")
    @guarded
    def related_candidates(identifier: str, before: str | None = Query(None, max_length=160)):
        return services.message_relations.candidates(check_id(identifier), before)

    @router.get("/{identifier}/related/preview")
    @guarded
    def related_preview(identifier: str, target_id: str):
        return services.message_relations.preview(check_id(identifier), check_id(target_id))

    @router.post("/{identifier}/related")
    @guarded
    def link(identifier: str, request: LinkMessage):
        return services.message_relations.link(check_id(identifier), request)

    @router.post("/{identifier}/related/unlink")
    @guarded
    def unlink(identifier: str, request: UnlinkMessage):
        return services.message_relations.unlink(check_id(identifier), request)

    @router.post("/{identifier}/complete")
    @guarded
    def complete(identifier: str, request: CompleteMessageReview):
        return services.message_review.complete(check_id(identifier), request)

    @router.post("/{identifier}/reopen")
    @guarded
    def reopen(identifier: str, request: ReopenMessageReview):
        return services.message_review.reopen(check_id(identifier), request)

    @router.post("/{identifier}/notice")
    @guarded
    def notice(identifier: str, request: SaveMessageNotice):
        return services.message_review.save_draft(check_id(identifier), request)

    @router.post("/{identifier}/notice-copy")
    @guarded
    def notice_copy(identifier: str, request: CopyMessageNotice):
        return services.message_review.copy_draft(check_id(identifier), request)

    return router
