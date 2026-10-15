import { useCallback, useRef, useState } from "react";
import type { Facility } from "./types";
import { referenceBounds, type MapCoordinate, type ReferencePoint, type ReferenceView } from "./locationReference";

export function useLocationReference() {
  const [point, setPoint] = useState<ReferencePoint | null>(null);
  const [candidate, setCandidate] = useState<ReferencePoint | null>(null);
  const [picking, setPicking] = useState(false);
  const [showRings, setShowRings] = useState(true);
  const [targetId, setTargetId] = useState("");
  const [view, setView] = useState<ReferenceView | null>(null);
  const revision = useRef(0);
  const focus = useCallback((points: MapCoordinate[]) => {
    setView({ points, revision: ++revision.current });
  }, []);
  const preview = useCallback((next: ReferencePoint) => {
    setCandidate(next);
    setPicking(false);
    focus([next]);
  }, [focus]);
  const pick = useCallback((coordinate: MapCoordinate) => {
    // Do not recenter after a manual click: preserve the user's map viewport.
    setCandidate({ ...coordinate, label: "사고 확인 지점", address: "", source: "map" });
    setPicking(false);
  }, []);
  const confirm = (label: string) => {
    if (!candidate) return;
    const next = { ...candidate, label: label.trim() || candidate.label };
    setPoint(next);
    setCandidate(null);
    setTargetId("");
    focus(referenceBounds(next));
  };
  const cancel = () => {
    setCandidate(null);
    setPicking(false);
    if (point) focus(referenceBounds(point));
  };
  const clear = () => {
    setPoint(null);
    setCandidate(null);
    setPicking(false);
    setTargetId("");
    setView(null);
  };
  const selectNearby = useCallback((facility: Facility) => {
    if (!point) return;
    setTargetId(facility.id);
    focus([point, facility]);
  }, [point, focus]);
  const clearTarget = useCallback(() => {
    setTargetId("");
    setView(null);
  }, []);
  return {
    point, candidate, picking, showRings, targetId, view,
    preview, pick, confirm, cancel, clear, selectNearby, clearTarget, setShowRings,
    startPicking: () => { setCandidate(null); setPicking(true); },
    recenter: () => { if (point) focus(referenceBounds(point)); },
  };
}

export type LocationReferenceState = ReturnType<typeof useLocationReference>;
