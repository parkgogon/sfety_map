import { useEffect, useState } from "react";
import { recordRequest } from "./messageRecordsApi";
import type { NotificationPreview } from "./messageAnalysisApi";

const LABELS = {
  notify_ready: "요약 전파 추천", notify_source_only: "원문 중심 전파 추천", record_only: "기록 추천",
  attention_required: "판단 확인 필요", analysis_unavailable: "분석 확인 필요", blocked: "최신 근거 확인 필요",
};
const URGENCY = { immediate: "신속 공유", scheduled: "예정 상황", reference: "참고", unknown: "미상" };

export default function MessageNotificationPreview({token, recordId, version}: {
  token: string; recordId: string; version: number;
}) {
  const [preview, setPreview] = useState<NotificationPreview | null>(null);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); setPreview(null); setError("");
    void recordRequest<NotificationPreview>(token, controller.signal,
      `/${recordId}/notification-preview?expected_version=${version}`).then(value => {
      if (controller.signal.aborted) return;
      if (value.record_version !== version || value.phase !== "preview" || value.dispatch_enabled !== false) {
        throw new Error("현재 기록의 미리보기인지 확인하지 못했습니다. 기록을 다시 불러와 주세요.");
      }
      setPreview(value);
    }).catch(e => {
      if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "전파 판단을 확인하지 못했습니다.");
    });
    return () => controller.abort();
  }, [token, recordId, version, reload]);
  return <section className="message-card notification-preview" aria-label="전파 판단 미리보기">
    <div className="quick-heading"><div><span className="message-tag">{preview&&preview.input_kind!=="official"?"미발송 · 판단 미리보기":"판단·문안 미리보기"}</span><h2>전파 판단</h2></div></div>
    {!preview && !error && <p role="status">저장한 분석과 현재 시설 자료의 근거를 확인하고 있습니다…</p>}
    {error && <p role="alert" className="message-error">{error} <button className="secondary-button" onClick={() => setReload(n => n+1)}>판단 다시 확인</button></p>}
    {preview && <>
      <h3>{LABELS[preview.decision]}</h3><p>{preview.reason}</p>
      {preview.assessment && <p className="message-caption">공유 시점: {URGENCY[preview.assessment.urgency]}</p>}
      {preview.preview_text && <><h3>전달 문안 미리보기</h3><pre className="quick-saved-notice" aria-label="전달 문안 미리보기">{preview.preview_text}</pre></>}
      {!!preview.limitations.length && <ul>{preview.limitations.map(text => <li key={text}>{text}</li>)}</ul>}
      {preview.assessment && <details><summary>판단의 원문 근거</summary>{preview.assessment.evidence.map((text, i) => <blockquote key={i}>{text}</blockquote>)}</details>}
    </>}
    <p className="message-caption">저장한 분석으로 준비한 미리보기입니다. 이 화면 조회는 AI 분석·검토 완료·실제 발송을 실행하지 않습니다.</p>
    {preview?.input_kind==="official"&&<a href="/control/messages?view=delivery">실제 전파 이력 확인</a>}
  </section>;
}
