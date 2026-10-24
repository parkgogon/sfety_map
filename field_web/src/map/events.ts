import type { KakaoEventArgs, KakaoSDK } from "../kakaoTypes";

/** 한 번 그린 레이어가 등록한 이벤트만 해제한다. */
export function mapEvents(sdk: KakaoSDK) {
  const cleanup: Array<() => void> = [];
  return {
    add<E extends keyof KakaoEventArgs>(
      target: object,
      name: E,
      handler: (...args: KakaoEventArgs[E]) => void,
    ) {
      sdk.maps.event.addListener(target, name, handler);
      cleanup.push(() => sdk.maps.event.removeListener(target, name, handler));
    },
    dispose() {
      cleanup.splice(0).forEach((remove) => remove());
    },
  };
}
