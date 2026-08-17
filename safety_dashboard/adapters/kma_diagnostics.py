"""KMA 실패 시 비밀값 없이 외부 통신 경로를 점검한다."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import requests

from safety_dashboard.domain.enums import KmaFailureCategory
from safety_dashboard.domain.models import KmaFailureDiagnostic


_CONTROL_URLS = {
    "kma_home": "https://apihub.kma.go.kr/",
    "weather_site": "https://www.weather.go.kr/w/special-report/overall.do",
    "internet": "https://www.gstatic.com/generate_204",
}


class KmaFailureDiagnoser:
    """직접 HTTP 분류가 불가능한 연결 오류에만 짧은 병렬 제어 점검을 수행한다."""

    def __init__(self, timeout: float = 3) -> None:
        self.timeout = timeout

    def diagnose(self, initial: KmaFailureDiagnostic) -> KmaFailureDiagnostic:
        if initial.category is not KmaFailureCategory.UNKNOWN:
            return initial
        with ThreadPoolExecutor(max_workers=len(_CONTROL_URLS)) as executor:
            futures = {
                name: executor.submit(self._probe, url)
                for name, url in _CONTROL_URLS.items()
            }
            results = {name: future.result() for name, future in futures.items()}

        internet_ok = results["internet"]
        kma_sites_ok = results["kma_home"] or results["weather_site"]
        evidence = " · ".join(
            f"{name} {'정상' if ok else '실패'}"
            for name, ok in results.items()
        )
        if not internet_ok and not kma_sites_ok:
            return replace(
                initial,
                category=KmaFailureCategory.CLOUD_EGRESS,
                summary="Cloud Run의 일반 외부 통신도 함께 실패함",
                evidence=evidence,
            )
        if internet_ok and kma_sites_ok:
            return replace(
                initial,
                category=KmaFailureCategory.KMA_ROUTE,
                summary="일반 외부통신은 정상이나 KMA 특보 API 연결만 실패함",
                evidence=evidence,
            )
        return replace(initial, evidence=evidence)

    def _probe(self, url: str) -> bool:
        try:
            response = requests.get(url, timeout=self.timeout)
            return response.status_code < 500
        except requests.RequestException:
            return False
