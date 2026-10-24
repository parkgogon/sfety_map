/// <reference types="vite/client" />

interface Window {
  kakao?: import("./kakaoTypes").KakaoSDK;
  __kakaoMapPromise?: Promise<import("./kakaoTypes").KakaoSDK>;
}
