/**
 * 웹 번들 빌드 메타데이터(Git SHA 및 배포 시각) 포맷터
 */

/** ISO 시각 문자열을 'MM.DD HH:mm' 포맷으로 변환합니다. */
export function formatBuildTime(rawIsoTime?: string | null): string {
  if (!rawIsoTime) return "";
  try {
    const date = new Date(rawIsoTime);
    if (Number.isNaN(date.getTime())) return "";
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    const hours = String(date.getHours()).padStart(2, "0");
    const minutes = String(date.getMinutes()).padStart(2, "0");
    return `${month}.${day} ${hours}:${minutes}`;
  } catch {
    return "";
  }
}

/** Git SHA 문자열을 7자리 짧은 SHA로 변환합니다. */
export function formatShortSha(rawSha?: string | null): string {
  if (!rawSha) return "";
  const cleaned = rawSha.trim();
  return cleaned.length > 7 ? cleaned.slice(0, 7) : cleaned;
}

/**
 * Git SHA와 배포 시각을 받아 사용자에게 표시할 간결한 빌드 레이블을 반환합니다.
 * 환경변수가 없을 때는 '개발 빌드'로 안전하게 fallback합니다.
 */
export function formatBuildLabel(
  rawVersion?: string | null,
  rawBuildTime?: string | null,
): string {
  const shortSha = formatShortSha(rawVersion);
  const timeStr = formatBuildTime(rawBuildTime);

  if (shortSha && timeStr) {
    return `v${shortSha} · ${timeStr} 배포`;
  }
  if (shortSha) {
    return `v${shortSha}`;
  }
  if (timeStr) {
    return `${timeStr} 배포`;
  }
  return "개발 빌드";
}

/** 현재 실행 중인 웹 번들의 빌드 메타데이터 레이블을 반환합니다. */
export function getBuildLabel(): string {
  const rawVersion = import.meta.env.VITE_APP_VERSION ?? "";
  const rawBuildTime = import.meta.env.VITE_BUILD_TIME ?? "";
  return formatBuildLabel(rawVersion, rawBuildTime);
}
