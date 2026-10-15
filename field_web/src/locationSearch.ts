import { loadKakaoMaps } from "./kakao";
import { validCoordinate, type ReferencePoint } from "./locationReference";

interface SearchRow {
  x: string;
  y: string;
  place_name?: string;
  address_name?: string;
  road_address_name?: string;
}

export interface LocationSearchResult {
  points: ReferencePoint[];
  partial: boolean;
}

export async function searchLocations(query: string): Promise<LocationSearchResult> {
  const keyword = query.trim();
  if (!keyword) return { points: [], partial: false };
  let timeout: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      (async () => {
        const kakao = await loadKakaoMaps(import.meta.env.VITE_KAKAO_MAP_APP_KEY?.trim() ?? "");
        const services = kakao.maps.services;
        if (!services) throw new Error("검색 서비스를 사용할 수 없습니다.");
        const request = (source: "place" | "address"): Promise<ReferencePoint[]> => new Promise((resolve, reject) => {
          const callback = (rows: SearchRow[], status: string) => {
            if (status === services.Status.ZERO_RESULT) { resolve([]); return; }
            if (status !== services.Status.OK) { reject(new Error("검색 실패")); return; }
            resolve(rows.filter((row) => row.x?.trim() && row.y?.trim()).map((row) => ({
              latitude: Number(row.y),
              longitude: Number(row.x),
              label: row.place_name || row.address_name || keyword,
              address: row.road_address_name || row.address_name || "",
              source,
            })).filter(validCoordinate));
          };
          if (source === "place") new services.Places().keywordSearch(keyword, callback, { size: 8 });
          else new services.Geocoder().addressSearch(keyword, callback, { size: 8 });
        });
        const responses = await Promise.allSettled([request("place"), request("address")]);
        if (responses.every((result) => result.status === "rejected")) throw new Error("검색 실패");
        const points: ReferencePoint[] = [];
        const seen = new Set<string>();
        responses.forEach((result) => {
          if (result.status !== "fulfilled") return;
          result.value.forEach((point) => {
            const key = `${point.latitude.toFixed(6)}:${point.longitude.toFixed(6)}:${point.label}`;
            if (!seen.has(key)) { seen.add(key); points.push(point); }
          });
        });
        return { points, partial: responses.some((result) => result.status === "rejected") };
      })(),
      new Promise<never>((_, reject) => {
        timeout = setTimeout(() => reject(new Error("검색 시간 초과")), 12000);
      }),
    ]);
  } finally {
    clearTimeout(timeout);
  }
}
