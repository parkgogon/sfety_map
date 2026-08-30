import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { KakaoMap } from "./KakaoMap";

describe("KakaoMap 기상 canvas 계층", () => {
  it("정적 기상 색면과 바람 파티클을 독립 canvas로 렌더링한다", () => {
    const markup = renderToStaticMarkup(
      <KakaoMap
        facilities={[]}
        warningZones={[]}
        selectedFacilityId=""
        cctvs={[]}
        selectedCctvId=""
        focusRequest={null}
        weatherLayer={null}
        onSelect={() => undefined}
        onSelectGroup={() => undefined}
        onSelectCctv={() => undefined}
      />,
    );
    expect(markup.match(/<canvas/g)).toHaveLength(2);
    expect(markup).toContain("weather-map-canvas weather-map-surface");
    expect(markup).toContain("weather-map-canvas wind-particle-canvas");
    expect(markup.match(/aria-hidden="true"/g)).toHaveLength(2);
  });

  it("특보 및 모의훈련 props가 제공되어도 에러 없이 렌더링된다", () => {
    const markup = renderToStaticMarkup(
      <KakaoMap
        facilities={[]}
        warningZones={[]}
        warnings={[
          {
            id: "w1",
            region_code: "L1020100",
            region: "대구광역시",
            type: "호우",
            raw_level: "경보",
          },
        ]}
        isSimulation={true}
        selectedFacilityId=""
        cctvs={[]}
        selectedCctvId=""
        focusRequest={null}
        weatherLayer={null}
        onSelect={() => undefined}
        onSelectGroup={() => undefined}
        onSelectCctv={() => undefined}
      />,
    );
    expect(markup).toContain("map-canvas");
  });
});
