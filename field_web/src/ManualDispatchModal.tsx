import { useMemo, useState } from "react";
import { dispatchManualTelegram, type ManualDispatchPayload } from "./controlApi";
import type { Facility, MonitoringMode } from "./types";
import { uniqueWarningText } from "./utils";

export interface ManualDispatchModalProps {
  facilities: Facility[];
  adminToken: string;
  monitoringMode: MonitoringMode;
  onClose: () => void;
  onSuccess: (dispatchId: string) => void;
}

type CategoryType = "REMINDER" | "CORRECTION" | "ADDITIONAL" | "DRILL";

const CATEGORY_LABELS: Record<CategoryType, string> = {
  REMINDER: "재공지 (기존 특보 재전파)",
  CORRECTION: "정정 (오발송 또는 내용 정정)",
  ADDITIONAL: "추가안내 (현장 유의사항 전달)",
  DRILL: "모의훈련 (훈련 상황 전파)",
};

export function buildManualMessages(
  facilities: Facility[],
  category: CategoryType,
  note: string,
  mode: MonitoringMode,
): string {
  const isDrill = mode === "simulation" || category === "DRILL";
  const header = isDrill
    ? "📢 [K-ECO 모의훈련] 수동 상황전파"
    : `📢 [K-ECO 수동 상황전파 - ${category === "REMINDER" ? "재공지" : category === "CORRECTION" ? "정정" : "추가안내"}]`;

  const affected = facilities.filter((f) => f.grade === "HIGH" || f.grade === "MEDIUM" || f.grade === "LOW");
  const warnings = [...new Set(affected.flatMap((f) => f.reasons.filter((r) => r.grade !== "NONE").map((r) => `${r.type} ${r.raw_level}`)))];


  const lines = [
    header,
    "",
    `■ 전파 대상: 총 ${facilities.length}개소 (특보 영향 ${affected.length}개소)`,
    `■ 발효 특보: ${warnings.length > 0 ? warnings.join(", ") : "발효 특보 없음"}`,
  ];

  if (note.trim()) {
    lines.push(`■ 관리자 안내: ${note.trim()}`);
  }

  if (affected.length > 0) {
    lines.push("", "■ 주요 영향 시설:");
    const topFacilities = affected.slice(0, 5);
    for (const fac of topFacilities) {
      lines.push(` • [${fac.grade_label}] ${fac.name} (${fac.type}) - ${uniqueWarningText(fac)}`);
    }
    if (affected.length > 5) {
      lines.push(` • 외 ${affected.length - 5}개소`);
    }
  }

  lines.push("", "■ 현장 안전점검 수칙을 준수하고 비상연락체계를 유지하시기 바랍니다.");
  if (isDrill) {
    lines.push("", "※ 본 메시지는 모의훈련 메시지이며 실제 재난 상황이 아닙니다.");
  }

  return lines.join("\n");
}


export function ManualDispatchModal({
  facilities,
  adminToken,
  monitoringMode,
  onClose,
  onSuccess,
}: ManualDispatchModalProps) {
  const isSimulation = monitoringMode === "simulation";
  const [category, setCategory] = useState<CategoryType>(
    isSimulation ? "DRILL" : "REMINDER",
  );
  const [note, setNote] = useState("");
  const [silent, setSilent] = useState(true);
  const [confirmed, setConfirmed] = useState(false);
  const [drillConfirmed, setDrillConfirmed] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const previewText = useMemo(
    () => buildManualMessages(facilities, category, note, monitoringMode),
    [facilities, category, note, monitoringMode],
  );

  const noteRequired = category === "CORRECTION" || category === "ADDITIONAL";
  const canSend =
    confirmed &&
    (!isSimulation || drillConfirmed) &&
    (!noteRequired || note.trim().length > 0) &&
    !sending;

  const handleSend = async () => {
    if (!canSend) return;
    setSending(true);
    setError(null);
    try {
      const requestId = `manual-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      const warningKeys = [...new Set(facilities.flatMap((f) => f.reasons.map((r) => r.warning_id)))];
      const payload: ManualDispatchPayload = {
        request_id: requestId,
        category,
        mode: monitoringMode,
        note: note.trim(),
        facility_ids: facilities.map((f) => f.id),
        warning_keys: warningKeys.length > 0 ? warningKeys : ["MANUAL_SCOPE"],
        messages: [{ text: previewText, silent }],
      };
      const res = await dispatchManualTelegram(adminToken, payload);
      onSuccess(res.dispatch_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "발송 실패");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="manual-dispatch-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="manual-dispatch-title"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <div>
            <h2 id="manual-dispatch-title">시설담당자 그룹 수동 상황전파</h2>
            <p>선택된 {facilities.length}개 소관시설에 대해 Telegram 그룹 알림을 전파합니다.</p>
          </div>
          <button className="close-button" type="button" onClick={onClose} aria-label="닫기">
            ×
          </button>
        </div>


        <div className="modal-body">
          {/* 전파 구분 */}
          <div className="form-group">
            <label htmlFor="category-select">전파 구분</label>
            {isSimulation ? (
              <div className="notice warning">
                현재 모의훈련 모드입니다. 메시지에 [모의훈련] 배너가 자동 표기됩니다.
              </div>
            ) : (
              <select
                id="category-select"
                value={category}
                onChange={(e) => setCategory(e.target.value as CategoryType)}
              >
                <option value="REMINDER">{CATEGORY_LABELS.REMINDER}</option>
                <option value="CORRECTION">{CATEGORY_LABELS.CORRECTION}</option>
                <option value="ADDITIONAL">{CATEGORY_LABELS.ADDITIONAL}</option>
              </select>
            )}
          </div>

          {/* 관리자 메모 */}
          <div className="form-group">
            <label htmlFor="admin-note">
              관리자 메모 {noteRequired && <b style={{ color: "var(--color-risk-high)" }}>* (필수)</b>}
            </label>
            <textarea
              id="admin-note"
              placeholder={
                noteRequired
                  ? "정정 내용 또는 현장 추가 안내사항을 입력하세요."
                  : "필요 시 추가 안내사항을 입력하세요 (선택)."
              }
              value={note}
              maxLength={200}
              onChange={(e) => setNote(e.target.value)}
              rows={2}
            />
            <small>{note.length}/200자</small>
          </div>

          {/* 알림 방식 */}
          <div className="form-group-inline">
            <label>
              <input
                type="checkbox"
                checked={silent}
                onChange={(e) => setSilent(e.target.checked)}
              />
              <span>무음 알림 (수신자 방해 최소화)</span>
            </label>
          </div>

          {/* 문안 미리보기 */}
          <div className="form-group">
            <label htmlFor="preview-area">발송 문안 미리보기</label>
            <textarea
              id="preview-area"
              className="preview-textarea"
              value={previewText}
              readOnly
              rows={9}
            />
          </div>

          {/* 최종 확인 */}
          <div className="confirmation-box">
            <label>
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
              />
              <span>
                시설담당자 그룹에 <b>{facilities.length}개소</b>에 대한 상황전파를 발송합니다.
              </span>
            </label>
            {isSimulation && (
              <label>
                <input
                  type="checkbox"
                  checked={drillConfirmed}
                  onChange={(e) => setDrillConfirmed(e.target.checked)}
                />
                <span>모의훈련 상황임을 재확인했습니다.</span>
              </label>
            )}
          </div>

          {error && <div className="notice error">{error}</div>}
        </div>

        <div className="modal-footer">
          <button className="secondary-button" type="button" onClick={onClose} disabled={sending}>
            취소
          </button>
          <button
            className="primary-button"
            type="button"
            onClick={() => void handleSend()}
            disabled={!canSend}
          >
            {sending ? "전파 발송 중..." : "상황전파 발송"}
          </button>
        </div>
      </section>
    </div>
  );
}
