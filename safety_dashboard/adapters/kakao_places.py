"""Small server-side place search; a JavaScript Maps key cannot replace the REST key."""

import math
import requests

from safety_dashboard.application.message_analysis import AnalysisUnavailable
from safety_dashboard.config.environment import env_text


class KakaoPlaceSearch:
    def __init__(self, rest_key: str, *, session=None):
        self._key = rest_key
        self.configured = bool(rest_key)
        self._session = session or requests.Session()

    @classmethod
    def from_environment(cls):
        return cls(env_text("KAKAO_REST_API_KEY"))

    def _documents(self, kind, query, timeout):
        if not self.configured:
            raise AnalysisUnavailable("장소 검색이 설정되지 않았습니다.")
        response = self._session.get(
            f"https://dapi.kakao.com/v2/local/search/{kind}.json",
            params={"query": query, "size": 5}, headers={"Authorization": f"KakaoAK {self._key}"},
            timeout=(min(3, timeout / 2), max(1, timeout - min(3, timeout / 2))), allow_redirects=False,
        )
        if response.status_code != 200:
            raise AnalysisUnavailable("장소 검색에 실패했습니다.")
        return response.json()["documents"][:5]

    @staticmethod
    def _point(row):
        lat, lon = float(row["y"]), float(row["x"])
        if math.isfinite(lat) and math.isfinite(lon) and 33 <= lat <= 39.5 and 124 <= lon <= 132:
            return {"latitude": lat, "longitude": lon}
        return None

    def search(self, query: str, timeout: float) -> list[dict]:
        try:
            result = []
            for row in self._documents("keyword", query, timeout):
                point = self._point(row)
                if not point:
                    continue
                result.append({"name": str(row["place_name"])[:160],
                               "address": str(row.get("road_address_name") or row.get("address_name", ""))[:240],
                               **point, "provider": "Kakao Local",
                               "category_name": str(row.get("category_name", ""))[:160],
                               "category_group_code": str(row.get("category_group_code", ""))[:20]})
            return result
        except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError):
            raise AnalysisUnavailable("장소 검색에 실패했습니다.") from None

    def search_address(self, query: str, timeout: float) -> list[dict]:
        try:
            result = []
            for row in self._documents("address", query, timeout):
                address = row.get("address")  # The structured parcel, even if a road address also exists.
                if not address or not address.get("address_name"):
                    continue
                point = self._point(address)
                if point:
                    name = str(address["address_name"])
                    result.append({"name": name[:160], "address": name[:240], **point, "provider": "Kakao Local"})
            return result
        except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError):
            raise AnalysisUnavailable("주소 조회에 실패했습니다.") from None
