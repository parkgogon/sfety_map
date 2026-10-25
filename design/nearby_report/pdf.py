"""운영 렌더러와 같은 디자인을 사용하는 개발 전용 시안 표시."""
from safety_dashboard.adapters.enhanced_nearby_pdf import EnhancedNearbyPdfRenderer, validate_map


class NearbyPreviewRenderer(EnhancedNearbyPdfRenderer):
    def render(self, report, map_png, metadata):
        return super().render(report, map_png, metadata, preview=True)


__all__ = ["NearbyPreviewRenderer", "validate_map"]
