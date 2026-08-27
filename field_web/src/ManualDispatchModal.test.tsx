import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { buildManualMessages, ManualDispatchModal } from "./ManualDispatchModal";
import type { Facility } from "./types";

const mockFacilities: Facility[] = [
  {
    id: "F-1",
    name: "구미 환경기술센터",
    address: "경북 구미시 1공단로",
    latitude: 36.1,
    longitude: 128.3,
    type: "기술지원",
    group_id: "tech",
    group_label: "기술지원시설",
    grade: "HIGH",
    grade_label: "위험(상)",
    grade_color: "#d92d20",
    meaning: "즉시 현장점검 및 대비 필요",
    recommended_action: "배수 설비 점검",
    public_contact: "홍길동 대리 (054-000-0000)",
    reasons: [
      {
        warning_id: "W-1",
        type: "호우",
        raw_level: "경보",
        grade: "HIGH",
        region: "구미시",
      },
    ],
  },
  {
    id: "F-2",
    name: "포항 측정소",
    address: "경북 포항시 남구",
    latitude: 36.0,
    longitude: 129.3,
    type: "측정망",
    group_id: "meas",
    group_label: "측정망",
    grade: "LOW",
    grade_label: "위험(하)",
    grade_color: "#8a6d00",
    meaning: "주의 관찰",
    recommended_action: "상황 모니터링",
    public_contact: "이순신 과장 (054-111-1111)",
    reasons: [
      {
        warning_id: "W-2",
        type: "강풍",
        raw_level: "주의보",
        grade: "LOW",
        region: "포항시",
      },
    ],
  },
];

describe("ManualDispatchModal", () => {
  it("builds clear notification message text with facilities and warnings", () => {
    const text = buildManualMessages(
      mockFacilities,
      "REMINDER",
      "비상 대기조 운영 요망",
      "live",
    );

    expect(text).toContain("[K-ECO 상황전파 - 재공지]");
    expect(text).toContain("총 2개소");
    expect(text).toContain("호우 경보");
    expect(text).toContain("비상 대기조 운영 요망");
    expect(text).toContain("구미 환경기술센터");
  });

  it("builds drill notification message text with drill disclaimer in simulation mode", () => {
    const text = buildManualMessages(
      mockFacilities,
      "DRILL",
      "모의훈련 진행",
      "simulation",
    );

    expect(text).toContain("[K-ECO 모의훈련]");
    expect(text).toContain("실제 상황이 아닙니다");
  });

  it("renders modal markup without errors", () => {
    const html = renderToStaticMarkup(
      <ManualDispatchModal
        facilities={mockFacilities}
        adminToken="dummy-token"
        monitoringMode="live"
        onClose={() => {}}
        onSuccess={() => {}}
      />,
    );

    expect(html).toContain("시설담당자 그룹 수동 상황전파");
    expect(html).toContain("선택된 2개 소관시설");
    expect(html).toContain("관리자 메모");
    expect(html).toContain("발송 문안 미리보기");
  });
});
