import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import {
  clampMapInformationCardPosition,
  MapInformationCard,
  type MapInformationCardContent,
} from "./MapInformationCard";

const content: MapInformationCardContent = {
  eyebrow: "선택 지점 보간값",
  title: "바람",
  value: "10.0m/s",
  lines: ["동 90.0° 방향으로 흐름"],
  meta: ["자료 기준 08. 30. 10:10", "훈련 가정값 · 실제 관측 아님"],
  tone: "simulation",
};

describe("MapInformationCard", () => {
  it("터치점 옆을 우선하고 오른쪽·아래쪽 경계에서는 카드 전체를 안쪽으로 옮긴다", () => {
    expect(clampMapInformationCardPosition(
      { x: 10, y: 20 },
      { width: 400, height: 400 },
      { width: 240, height: 120 },
    )).toEqual({ x: 22, y: 32 });
    expect(clampMapInformationCardPosition(
      { x: 350, y: 750 },
      { width: 360, height: 800 },
      { width: 240, height: 120 },
    )).toEqual({ x: 98, y: 618 });
  });

  it("값·방향·기준·훈련 구분과 접근 가능한 닫기 버튼을 표시한다", () => {
    const markup = renderToStaticMarkup(
      <MapInformationCard
        anchor={{ x: 10, y: 20 }}
        viewport={{ width: 400, height: 400 }}
        content={content}
        onClose={() => undefined}
      />,
    );
    expect(markup).toContain('role="dialog"');
    expect(markup).toContain('aria-label="바람 지도 정보"');
    expect(markup).toContain('aria-label="지도 정보 닫기"');
    expect(markup).toContain("선택 지점 보간값");
    expect(markup).toContain("10.0m/s");
    expect(markup).toContain("동 90.0° 방향으로 흐름");
    expect(markup).toContain("훈련 가정값 · 실제 관측 아님");
    expect(markup).toContain("map-information-card simulation");
  });
});
