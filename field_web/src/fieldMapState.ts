import { useCallback, useEffect, useRef, useState } from "react";
import type {
  Facility,
  MapFocusRequest,
  MonitoringResponse,
  RiskGrade,
} from "./types";
import type {
  MobilePanel,
  MobileSearchTab,
  MobileSettingsTab,
} from "./useMobileLayout";
import type { useLocationReference } from "./useLocationReference";
import {
  GRADE_DISPLAY_ORDER,
  reconcileFacilityGroupSelection,
  requestedFacilityId,
  shouldZoomForSelection,
  type FacilitySelectionSource,
} from "./utils";

export function useFieldMapPanels(isMobile: boolean) {
  const [mobilePanel, setMobilePanel] = useState<MobilePanel>("none");
  const [mobileSearchTab, setMobileSearchTab] =
    useState<MobileSearchTab>("facilities");
  const [mobileSettingsTab, setMobileSettingsTab] =
    useState<MobileSettingsTab>("facilities");
  const mobileModalPanelOpen =
    isMobile &&
    [
      "status",
      "more",
      "map-settings",
      "search",
      "nearby",
      "same-location",
    ].includes(mobilePanel);
  const [desktopFilterOpen, setDesktopFilterOpen] = useState(false);
  const [sameLocation, setSameLocation] = useState<Facility[]>([]);
  const [desktopWeatherLayerOpen, setDesktopWeatherLayerOpen] = useState(false);
  const filterOpen = isMobile
    ? mobilePanel === "map-settings" && mobileSettingsTab === "facilities"
    : desktopFilterOpen;
  const weatherLayerOpen = isMobile
    ? mobilePanel === "map-settings" && mobileSettingsTab === "weather"
    : desktopWeatherLayerOpen;
  const setFilterOpen = useCallback(
    (open: boolean) => {
      if (isMobile) {
        if (open) setMobileSettingsTab("facilities");
        setMobilePanel(open ? "map-settings" : "none");
      } else setDesktopFilterOpen(open);
    },
    [isMobile],
  );
  const setWeatherLayerOpen = useCallback(
    (open: boolean) => {
      if (isMobile) {
        if (open) setMobileSettingsTab("weather");
        setMobilePanel(open ? "map-settings" : "none");
      } else setDesktopWeatherLayerOpen(open);
    },
    [isMobile],
  );
  const selectSameLocation = useCallback(
    (facilities: Facility[]) => {
      setSameLocation(facilities);
      if (isMobile) setMobilePanel("same-location");
    },
    [isMobile],
  );
  useEffect(() => {
    // Close transient dialogs at breakpoints, preserving the map and domain state.
    setMobilePanel("none");
    setDesktopFilterOpen(false);
    setDesktopWeatherLayerOpen(false);
    setSameLocation([]);
  }, [isMobile]);
  return {
    mobilePanel,
    setMobilePanel,
    mobileSearchTab,
    setMobileSearchTab,
    mobileSettingsTab,
    setMobileSettingsTab,
    mobileModalPanelOpen,
    sameLocation,
    setSameLocation,
    filterOpen,
    weatherLayerOpen,
    setFilterOpen,
    setWeatherLayerOpen,
    selectSameLocation,
  };
}

export function useFacilityFilters(data: MonitoringResponse | null) {
  const [selectedGroups, setSelectedGroups] = useState<Set<string>>(new Set());
  const [selectedGrades, setSelectedGrades] = useState<Set<RiskGrade>>(
    new Set(GRADE_DISPLAY_ORDER),
  );
  const initializedGroups = useRef(false);
  const previousGroupIds = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (!data) return;
    const available = new Set(data.groups.map((group) => group.id));
    if (!initializedGroups.current) {
      setSelectedGroups(available);
      previousGroupIds.current = available;
      initializedGroups.current = true;
      return;
    }
    setSelectedGroups((current) =>
      reconcileFacilityGroupSelection(
        current,
        previousGroupIds.current,
        available,
      ),
    );
    previousGroupIds.current = available;
  }, [data?.groups]);
  return {
    selectedGroups,
    setSelectedGroups,
    selectedGrades,
    setSelectedGrades,
  };
}

type SelectionInputs = {
  data: MonitoringResponse | null;
  isMobile: boolean;
  reference: ReturnType<typeof useLocationReference>;
  panels: ReturnType<typeof useFieldMapPanels>;
  filters: ReturnType<typeof useFacilityFilters>;
};

export function useFieldFacilitySelection({
  data,
  isMobile,
  reference,
  panels,
  filters,
}: SelectionInputs) {
  const { setSameLocation, setMobilePanel } = panels;
  const { setSelectedGroups, setSelectedGrades } = filters;
  const [selectedId, setSelectedId] = useState("");
  const [search, setSearch] = useState("");
  const [deepLinkNotice, setDeepLinkNotice] = useState("");
  const [focusRequest, setFocusRequest] = useState<MapFocusRequest | null>(
    null,
  );
  const [selectedCctvId, setSelectedCctvId] = useState("");
  const handledDeepLink = useRef(false);
  const focusRevision = useRef(0);
  const selectFacility = useCallback(
    (facility: Facility, source: FacilitySelectionSource = "marker") => {
      if (source === "search" || source === "deep_link") {
        setSelectedGroups((current) =>
          current.has(facility.group_id)
            ? current
            : new Set([...current, facility.group_id]),
        );
        setSelectedGrades((current) =>
          current.has(facility.grade)
            ? current
            : new Set([...current, facility.grade]),
        );
      }
      setSelectedId(facility.id);
      setSearch("");
      setSameLocation([]);
      setSelectedCctvId("");
      setFacilityQuery(facility.id);
      focusRevision.current += 1;
      setFocusRequest({
        latitude: facility.latitude,
        longitude: facility.longitude,
        zoom: shouldZoomForSelection(source),
        revision: focusRevision.current,
      });
      reference.selectNearby(facility);
      if (isMobile) setMobilePanel("facility");
    },
    [reference.selectNearby, isMobile],
  );
  useEffect(() => {
    if (!data || handledDeepLink.current) return;
    handledDeepLink.current = true;
    const requested = requestedFacilityId(window.location.search);
    if (!requested) return;
    const facility = data.facilities.find((item) => item.id === requested);
    if (!facility) {
      setDeepLinkNotice("요청한 시설을 찾을 수 없어 전체 지도를 표시합니다.");
      setFacilityQuery("");
      return;
    }
    selectFacility(facility, "deep_link");
  }, [data, selectFacility]);
  return {
    selectedId,
    setSelectedId,
    search,
    setSearch,
    deepLinkNotice,
    focusRequest,
    setFocusRequest,
    selectedCctvId,
    setSelectedCctvId,
    selectFacility,
  };
}

export function setFacilityQuery(facilityId: string) {
  const url = new URL(window.location.href);
  if (facilityId) url.searchParams.set("facility_id", facilityId);
  else url.searchParams.delete("facility_id");
  window.history.replaceState({}, "", url);
}
