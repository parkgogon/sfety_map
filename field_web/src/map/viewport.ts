export interface MapPadding {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

export const MAP_EDGE_PADDING = 48;

export const MAP_OVERLAY_GAP = 16;

export function usableOverlayRect(
  overlay: Element,
  mapRect: DOMRect,
): DOMRect | null {
  const rect = overlay.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return null;
  if (
    rect.right <= mapRect.left ||
    rect.left >= mapRect.right ||
    rect.bottom <= mapRect.top ||
    rect.top >= mapRect.bottom
  )
    return null;
  return rect;
}

export function mapViewportPadding(element: HTMLElement): MapPadding {
  const mapRect = element.getBoundingClientRect();
  const width = element.clientWidth || mapRect.width || 1024;
  const height = element.clientHeight || mapRect.height || 600;
  const container = element.closest(".map-stage, .control-map-container");
  const mobile = !!element.closest(".mobile-field-map");
  const padding: MapPadding = {
    top: MAP_EDGE_PADDING,
    right: MAP_EDGE_PADDING,
    bottom: MAP_EDGE_PADDING,
    left: MAP_EDGE_PADDING,
  };
  if (!container) return padding;

  if (mobile) {
    container
      .querySelectorAll(".mobile-map-top-controls, .mobile-picking-guide")
      .forEach((overlay) => {
        const rect = usableOverlayRect(overlay, mapRect);
        if (rect)
          padding.top = Math.max(
            padding.top,
            rect.bottom - mapRect.top + MAP_OVERLAY_GAP,
          );
      });
    container
      .querySelectorAll(
        ".mobile-candidate-panel, .facility-sheet.mobile-compact, .mobile-map-bottom-controls",
      )
      .forEach((overlay) => {
        const rect = usableOverlayRect(overlay, mapRect);
        if (rect)
          padding.bottom = Math.max(
            padding.bottom,
            mapRect.bottom - rect.top + MAP_OVERLAY_GAP,
          );
      });
    padding.top = Math.min(
      padding.top,
      Math.max(MAP_EDGE_PADDING, height - padding.bottom - 96),
    );
    padding.bottom = Math.min(
      padding.bottom,
      Math.max(MAP_EDGE_PADDING, height - padding.top - 96),
    );
    return padding;
  }

  const panel = container
    .querySelector(".map-search-panel, .control-location-panel")
    ?.getBoundingClientRect();
  const sheet = container
    .querySelector(".facility-sheet")
    ?.getBoundingClientRect();
  padding.right =
    sheet && sheet.width < width * 0.7
      ? Math.min(width * 0.5, sheet.width + 40)
      : MAP_EDGE_PADDING;
  padding.bottom =
    sheet && sheet.width >= width * 0.7
      ? Math.min(height * 0.4, sheet.height + 24)
      : MAP_EDGE_PADDING;
  padding.top = Math.max(
    0,
    Math.min(
      height - padding.bottom - 96,
      Math.max(
        MAP_EDGE_PADDING,
        panel ? panel.bottom - mapRect.top + 20 : MAP_EDGE_PADDING,
      ),
    ),
  );
  return padding;
}

export function overlayElements(element: HTMLElement): Element[] {
  const container = element.closest(".map-stage, .control-map-container");
  if (!container) return [];
  return Array.from(
    container.querySelectorAll(
      ".map-search-panel, .control-location-panel, .facility-sheet, .mobile-map-top-controls, .mobile-picking-guide, .mobile-candidate-panel, .mobile-map-bottom-controls",
    ),
  );
}
