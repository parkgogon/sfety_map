import type { ReferencePoint } from "./locationReference";

export async function downloadNearbyReport(point: ReferencePoint, radiusKm: number, expectedCount: number, signal: AbortSignal) {
  const response = await fetch("/api/v1/reports/nearby.pdf", {
    method: "POST", credentials: "same-origin", signal,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ latitude: point.latitude, longitude: point.longitude,
      label: point.label, address: point.address, radius_km: radiusKm }),
  });
  if (!response.ok) throw new Error(response.status === 503
    ? "시설 자료를 읽지 못했습니다. 잠시 후 다시 시도해 주세요."
    : "보고서를 생성하지 못했습니다. 잠시 후 다시 시도해 주세요.");
  if (!response.headers.get("Content-Type")?.startsWith("application/pdf")) {
    throw new Error("PDF 응답을 확인하지 못했습니다. 다시 시도해 주세요.");
  }
  if (response.headers.get("X-Nearby-Facility-Count") !== String(expectedCount)) {
    throw new Error("시설 자료가 변경되었습니다. 화면을 새로고침한 뒤 대상을 다시 확인해 주세요.");
  }
  const blob = await response.blob();
  signal.throwIfAborted();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "기준점_주변시설_현황.pdf";
  document.body.append(link);
  link.click();
  link.remove();
  // Give the browser time to start reading the download before releasing it.
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
