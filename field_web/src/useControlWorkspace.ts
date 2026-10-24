import { useAdminSession } from "./useAdminSession";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMonitoringData } from "./api";
import {
  downloadReportPdf,
  useAlertEvents,
  useAlertMetrics,
  useControlOverview,
} from "./controlApi";

import { useLocationReference } from "./useLocationReference";

import { useWeatherLayer } from "./weatherLayerApi";

import type {
  Facility,
  MapFocusRequest,
  MonitoringMode,
  MonitoringResponse,
  RiskGrade,
  WeatherLayerKind,
} from "./types";
import {
  filterFacilities,
  GRADE_DISPLAY_ORDER,
  GRADE_PRIORITY_ORDER,
  recommendedWeatherLayer,
  requestedMonitoringMode,
} from "./utils";
import {
  monitoringOutputsAvailable,
  resolveSelectedFacilityScope,
} from "./controlModel";

type ControlWorkspace = "overview" | "analysis" | "history";

export function useControlWorkspace() {
  const {
    adminToken,
    passwordInput,
    setPasswordInput,
    authError,
    authLoading,
    handleLogin,
    handleLogout,
  } = useAdminSession(() => setLoginModalOpen(false));

  const [workspace, setWorkspace] = useState<ControlWorkspace>("overview");
  const reference = useLocationReference();
  const [locationOpen, setLocationOpen] = useState(false);
  const [monitoringMode, setMonitoringMode] = useState<MonitoringMode>(() =>
    requestedMonitoringMode(
      typeof window !== "undefined" ? window.location.search : "",
    ),
  );
  const [weatherLayerKind, setWeatherLayerKind] =
    useState<WeatherLayerKind | null>(null);
  const autoSelectedSimulationRef = useRef(false);
  const userSelectedLayerRef = useRef(false);
  const { data, loading, refreshing, error, refresh } =
    useMonitoringData(monitoringMode);

  // 관리자 인증

  // 세션 자동 확인

  // 대상 분석 다중 선택
  const [selectedFacilityIds, setSelectedFacilityIds] = useState<Set<string>>(
    new Set(),
  );
  const [focusedFacilityId, setFocusedFacilityId] = useState("");
  const [focusRequest, setFocusRequest] = useState<MapFocusRequest | null>(
    null,
  );
  const [dispatchModalOpen, setDispatchModalOpen] = useState(false);
  const [dispatchSuccessId, setDispatchSuccessId] = useState<string | null>(
    null,
  );

  // 우선순위 목록 필터/검색
  const [search, setSearch] = useState("");
  const [selectedGrade, setSelectedGrade] = useState<string>("ALL");
  const [selectedGroup, setSelectedGroup] = useState<string>("ALL");

  // 실적/이력 기간
  const [dateRange, setDateRange] = useState<"today" | "7d" | "30d">("today");
  const fromDate = useMemo(() => {
    if (dateRange === "today") return todayYMD();
    if (dateRange === "7d") return daysAgoYMD(7);
    return daysAgoYMD(30);
  }, [dateRange]);
  const toDate = useMemo(() => todayYMD(), []);

  const overview = useControlOverview(adminToken);
  const metrics = useAlertMetrics(adminToken, fromDate, toDate);
  const events = useAlertEvents(adminToken, fromDate, toDate);
  const weatherLayer = useWeatherLayer(weatherLayerKind, monitoringMode);

  // 초기 특보 영향 시설 자동 선택
  useEffect(() => {
    if (!data) return;
    const affected = data.facilities
      .filter(
        (f) => f.grade === "HIGH" || f.grade === "MEDIUM" || f.grade === "LOW",
      )
      .map((f) => f.id);
    setSelectedFacilityIds(
      new Set(
        affected.length > 0 ? affected : data.facilities.map((f) => f.id),
      ),
    );
  }, [data]);

  const [loginModalOpen, setLoginModalOpen] = useState(false);

  // 모의훈련 snapshot 도착 시 특보 기반 추천 레이어 1회 자동 선택
  useEffect(() => {
    if (monitoringMode !== "simulation") {
      autoSelectedSimulationRef.current = false;
      userSelectedLayerRef.current = false;
      return;
    }
    if (!data || data.status.health !== "SIMULATION") return;
    if (!autoSelectedSimulationRef.current && !userSelectedLayerRef.current) {
      autoSelectedSimulationRef.current = true;
      const recommended = recommendedWeatherLayer(data.warnings) ?? "wind";
      setWeatherLayerKind(recommended);
    }
  }, [data, monitoringMode]);

  const handleSelectWeatherLayer = useCallback(
    (kind: WeatherLayerKind | null) => {
      userSelectedLayerRef.current = true;
      setWeatherLayerKind(kind);
    },
    [],
  );

  const changeMonitoringMode = (mode: MonitoringMode) => {
    setModeQuery(mode);
    setMonitoringMode(mode);
    reference.clear();
    if (mode === "live") {
      setWeatherLayerKind(null);
      autoSelectedSimulationRef.current = false;
      userSelectedLayerRef.current = false;
    } else {
      autoSelectedSimulationRef.current = false;
      userSelectedLayerRef.current = false;
    }
  };

  // 우선순위 정렬된 시설 목록
  const prioritySortedFacilities = useMemo(() => {
    if (!data) return [];
    const gradeRankMap = new Map(
      GRADE_PRIORITY_ORDER.map((grade, index) => [grade, index]),
    );
    const list = [...data.facilities];
    list.sort((a, b) => {
      const rankA = gradeRankMap.get(a.grade) ?? 99;
      const rankB = gradeRankMap.get(b.grade) ?? 99;
      if (rankA !== rankB) return rankA - rankB;
      // 발효 특보 개수 많은 순
      if (b.reasons.length !== a.reasons.length)
        return b.reasons.length - a.reasons.length;
      return a.name.localeCompare(b.name, "ko-KR");
    });
    return list;
  }, [data]);

  // 필터링된 시설 목록
  const filteredPriorityFacilities = useMemo(() => {
    if (!data) return [];
    const groupSet =
      selectedGroup === "ALL"
        ? new Set(data.groups.map((g) => g.id))
        : new Set([selectedGroup]);
    const gradeSet =
      selectedGrade === "ALL"
        ? new Set(GRADE_DISPLAY_ORDER)
        : new Set([selectedGrade as RiskGrade]);
    return filterFacilities(
      prioritySortedFacilities,
      groupSet,
      gradeSet,
      search,
    );
  }, [data, prioritySortedFacilities, selectedGroup, selectedGrade, search]);

  // 다중 선택 헬퍼
  const toggleFacilitySelection = (id: string) => {
    setSelectedFacilityIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAllFacilities = () => {
    if (!data) return;
    setSelectedFacilityIds(new Set(data.facilities.map((f) => f.id)));
  };

  const selectAffectedFacilities = () => {
    if (!data) return;
    const affected = data.facilities
      .filter(
        (f) => f.grade === "HIGH" || f.grade === "MEDIUM" || f.grade === "LOW",
      )
      .map((f) => f.id);
    setSelectedFacilityIds(new Set(affected));
  };

  const clearFacilitySelection = () => {
    setSelectedFacilityIds(new Set());
  };

  // 수동 상황전파가 사용하는 확정 선택 범위
  const selectedFacilityScope = useMemo(() => {
    if (!data) return { ids: [], facilities: [] };
    return resolveSelectedFacilityScope(data.facilities, selectedFacilityIds);
  }, [data, selectedFacilityIds]);

  const handleMapFacilitySelect = useCallback(
    (facility: Facility) => {
      setFocusedFacilityId(facility.id);
      setFocusRequest({
        latitude: facility.latitude,
        longitude: facility.longitude,
        zoom: true,
        revision: Date.now(),
      });
      reference.selectNearby(facility);
    },
    [reference.selectNearby],
  );

  // PDF 다운로드 실행 (기본 전체 소관시설 103개소 종합보고서)
  const [pdfLoading, setPdfLoading] = useState(false);
  const handlePdfDownload = async () => {
    if (!data || pdfLoading) return;
    if (!monitoringOutputsAvailable(data.status.health)) {
      alert(
        "KMA 실시간 자료가 정상이 아닌 상태에서는 새 PDF 보고서를 생성할 수 없습니다.",
      );
      return;
    }
    setPdfLoading(true);
    try {
      // 헤더의 초동보고서는 전체 103개 소관시설 기준 종합 보고서로 발행
      await downloadReportPdf(adminToken, monitoringMode, [], "전체 소관시설");
    } catch (err) {
      alert(
        err instanceof Error ? err.message : "PDF 다운로드에 실패했습니다.",
      );
    } finally {
      setPdfLoading(false);
    }
  };

  // 위험등급별 집계
  const gradeCounts = useMemo(() => {
    const counts: Record<RiskGrade, number> = {
      HIGH: 0,
      MEDIUM: 0,
      LOW: 0,
      NONE: 0,
      UNASSESSED: 0,
      UNAVAILABLE: 0,
    };
    if (!data) return counts;
    for (const f of data.facilities) {
      if (counts[f.grade] !== undefined) {
        counts[f.grade] += 1;
      }
    }
    return counts;
  }, [data]);

  const activeWarningCount =
    gradeCounts.HIGH + gradeCounts.MEDIUM + gradeCounts.LOW;

  const simulation = data?.status.health === "SIMULATION";
  const live = data?.status.health === "LIVE";
  const stale = data?.status.health === "STALE";
  const actionsBlocked =
    !data || !monitoringOutputsAvailable(data.status.health);
  return {
    adminToken,
    passwordInput,
    setPasswordInput,
    authError,
    authLoading,
    handleLogin,
    handleLogout,
    workspace,
    setWorkspace,
    reference,
    locationOpen,
    setLocationOpen,
    monitoringMode,
    weatherLayerKind,
    data,
    loading,
    refreshing,
    error,
    refresh,
    selectedFacilityIds,
    focusedFacilityId,
    focusRequest,
    dispatchModalOpen,
    setDispatchModalOpen,
    dispatchSuccessId,
    setDispatchSuccessId,
    search,
    setSearch,
    selectedGrade,
    setSelectedGrade,
    selectedGroup,
    setSelectedGroup,
    dateRange,
    setDateRange,
    fromDate,
    toDate,
    overview,
    metrics,
    events,
    weatherLayer,
    loginModalOpen,
    setLoginModalOpen,
    handleSelectWeatherLayer,
    changeMonitoringMode,
    prioritySortedFacilities,
    filteredPriorityFacilities,
    toggleFacilitySelection,
    selectAllFacilities,
    selectAffectedFacilities,
    clearFacilitySelection,
    selectedFacilityScope,
    handleMapFacilitySelect,
    pdfLoading,
    handlePdfDownload,
    gradeCounts,
    activeWarningCount,
    simulation,
    live,
    stale,
    actionsBlocked,
  };
}

export type ReadyControlWorkspace = Omit<
  ReturnType<typeof useControlWorkspace>,
  "data"
> & { data: MonitoringResponse };

function todayYMD(): string {
  const now = new Date();
  return now.toISOString().slice(0, 10);
}

function daysAgoYMD(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return date.toISOString().slice(0, 10);
}

function setModeQuery(mode: MonitoringMode) {
  const url = new URL(window.location.href);
  if (mode === "simulation") url.searchParams.set("mode", "simulation");
  else url.searchParams.delete("mode");
  window.history.replaceState({}, "", url);
}
