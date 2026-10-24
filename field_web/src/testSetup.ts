import { afterAll, afterEach, beforeEach, expect } from "vitest";

let requests = 0;
let totalRequests = 0;

function blockedRequest(): never {
  requests += 1;
  totalRequests += 1;
  throw new Error(
    "자동 테스트에서는 실제 HTTP 요청을 허용하지 않습니다. 가짜 API를 사용하세요.",
  );
}

const blockedFetch: typeof fetch = async () => blockedRequest();

function blockRealRequests() {
  // 테스트 사이에도 실제 fetch/XHR로 되돌리지 않는다. 늦게 끝나는 비동기 작업도 차단한다.
  globalThis.fetch = blockedFetch;
  if (typeof XMLHttpRequest !== "undefined") {
    XMLHttpRequest.prototype.send = blockedRequest;
  }
  if (
    typeof navigator !== "undefined" &&
    typeof navigator.sendBeacon === "function"
  ) {
    navigator.sendBeacon = blockedRequest;
  }
}

blockRealRequests();

beforeEach(() => {
  requests = 0;
  blockRealRequests();
});

afterEach(() => {
  // 컴포넌트가 통신 예외를 처리하더라도 가짜 API를 빠뜨린 테스트를 성공시키지 않는다.
  try {
    expect(
      requests,
      "실제 HTTP 요청 시도를 차단했습니다. 테스트에 가짜 API를 주입하세요.",
    ).toBe(0);
  } finally {
    blockRealRequests();
  }
});

afterAll(() => {
  expect(
    totalRequests,
    "테스트 사이의 비동기 작업이 실제 HTTP를 시도했습니다.",
  ).toBe(0);
});
