# 기상청 특보구역 스냅샷

`kma_warning_zones.geojson.gz`는 기상청 날씨누리의
[공식 특보구역 GeoJSON](https://www.weather.go.kr/wgis-nuri/js/info/wrnArea.geojson)을
2026-08-02에 내려받아 소관시설 육상 권역 코드
`L107`, `L108`, `L114`, `L115`, `L116`만 보존한 장애 대비 스냅샷입니다.

앱은 기상청 최신본을 하루 단위로 조회하며, 조회 또는 도형 검증에 실패할
때만 이 파일을 사용합니다. 원본의 유효하지 않은 도형은 Shapely
`make_valid`로 복구한 뒤 저장했습니다.
