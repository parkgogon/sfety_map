export function loadKakaoMaps(appKey: string): Promise<any> {
  if (!appKey) return Promise.reject(new Error("카카오 지도 JavaScript 키가 없습니다."));
  if (window.kakao?.maps) {
    return new Promise((resolve) => window.kakao!.maps.load(() => resolve(window.kakao)));
  }
  if (window.__kakaoMapPromise) return window.__kakaoMapPromise;

  window.__kakaoMapPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>("script[data-kakao-map]");
    const script = existing ?? document.createElement("script");
    const complete = () => {
      if (!window.kakao?.maps) {
        reject(new Error("카카오 지도 SDK를 초기화하지 못했습니다."));
        return;
      }
      window.kakao.maps.load(() => resolve(window.kakao));
    };
    script.addEventListener("load", complete, { once: true });
    script.addEventListener("error", () => reject(new Error("카카오 지도 SDK를 불러오지 못했습니다.")), { once: true });
    if (!existing) {
      script.dataset.kakaoMap = "true";
      script.async = true;
      script.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${encodeURIComponent(appKey)}&autoload=false&libraries=clusterer`;
      document.head.appendChild(script);
    }
  });
  return window.__kakaoMapPromise;
}
