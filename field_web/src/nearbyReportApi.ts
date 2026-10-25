import type { ReferencePoint } from "./locationReference";

export async function downloadNearbyReport(point: ReferencePoint, radiusKm: number, expectedIds: string[], signal: AbortSignal) {
  signal.throwIfAborted();
  const requestController = new AbortController();
  const abort = () => requestController.abort();
  signal.addEventListener("abort", abort, { once: true });
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; requestController.abort(); }, 45_000);
  try {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify([...expectedIds].sort())));
  const expectedDigest = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
  signal.throwIfAborted();
  const response = await fetch("/api/v1/reports/nearby.pdf", {
    method: "POST", credentials: "same-origin", signal: requestController.signal,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ latitude: point.latitude, longitude: point.longitude,
      label: point.label, address: point.address, radius_km: radiusKm }),
  });
  if (!response.ok) throw new Error(response.status === 429
    ? "생성 중인 보고서가 많습니다. 잠시 후 다시 시도해 주세요."
    : response.status === 504 ? "보고서 생성 시간이 초과되었습니다. 다시 시도해 주세요."
    : response.status === 503
    ? "시설 자료를 읽지 못했습니다. 잠시 후 다시 시도해 주세요."
    : "보고서를 생성하지 못했습니다. 잠시 후 다시 시도해 주세요.");
  if (!response.headers.get("Content-Type")?.startsWith("application/pdf")) {
    throw new Error("PDF 응답을 확인하지 못했습니다. 다시 시도해 주세요.");
  }
  if (response.headers.get("X-Nearby-Facility-Count") !== String(expectedIds.length)
    || response.headers.get("X-Nearby-Facility-Digest") !== expectedDigest) {
    throw new Error("시설 자료가 변경되었습니다. 화면을 새로고침한 뒤 대상을 다시 확인해 주세요.");
  }
  const blob = await response.blob();
  signal.throwIfAborted();
  requestController.signal.throwIfAborted();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "기준점_주변시설_현황.pdf";
  document.body.append(link);
  link.click();
  link.remove();
  // Give the browser time to start reading the download before releasing it.
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
  return { mapIncluded: !response.headers.has("X-Nearby-Map-Status") || response.headers.get("X-Nearby-Map-Status") === "captured" };
  } catch (error) {
    if (timedOut && !signal.aborted) throw new Error("보고서 생성 시간이 초과되었습니다. 다시 시도해 주세요.");
    throw error;
  } finally {
    clearTimeout(timer);
    signal.removeEventListener("abort", abort);
  }
}
