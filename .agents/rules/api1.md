---
trigger: always_on
---



|      |                                                                                                                                                                                                  |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 개요   | 단기예보란 예보기간과 구역을 시 · 공간적으로 세분화하여 발표하는 예보입니다. 지역별, 시간별 차이로 인한 수요자의 불편을 최소화하기 위해 전국을 5km * 5km 간격의 격자(동서 149(745km) × 남북 253(1.265km)), 총 37,697개로 나누어, 3시간 마다 읍, 면, 동 단위의 행정구역 중심으로 상세한 날씨를 제공합니다. |
| 요 소  | 3시간 기온, 낮 최고기온, 아침 최저기온, 풍향, 풍속, 동서바람성분, 남북바람성분, 하늘상태, 강수형태, 강수확률, 6시간 강수량, 6시간 신적설, 습도, 파고                                                                                                      |
| 지 점  | 동사무소를 중심으로 하는 행정구역                                                                                                                                                                               |
| 보유기간 | 2008년 10월 30일 17:00KST(시행일 기준) ~ 현재                                                                                                                                                              |
| 생산주기 | 2시부터 3시간 간격(일 8회)                                                                                                                                                                                |

### 1. 단기예보자료(2001년 2월 이후) 조회

#### 1.1 단기 예보구역

[https://apihub.kma.go.kr/api/typ01/url/fct_shrt_reg.php?tmfc=0&authKey=YOUR_KMA_API_KEY](https://apihub.kma.go.kr/api/typ01/url/fct_shrt_reg.php?tmfc=0&authKey=YOUR_KMA_API_KEY)

##### 요청인자

  
|인자명|의미|설명|
|---|---|---|
|stn|발표관서번호|없으면 전체|
|reg|예보구역코드|없으면 전체|
|tmfc|발표시간|예보구역조회에서 사용(기준시각의미, 년월일시(KST))  <br>없으면, 전체 / 0이면, 가장 최근|
|tmfc1|발표시간  <br>(기간)|기간: [tmfc1 ~ tmfc2] : 년월일시(KST)  <br>없으면, 가장 최근 발표시간자료|
|tmfc2|발표시간  <br>(기간)|기간: [tmfc1 ~ tmfc2] : 년월일시(KST)  <br>없으면, 가장 최근 발표시간자료|
|tmef1|발효시간  <br>(기간)|기간: [tmef1 ~ tmef2] : 년월일시(KST)  <br>없으면, 해당 발표시간에 예보된 기간 전체|
|tmef2|발효시간  <br>(기간)|기간: [tmef1 ~ tmef2] : 년월일시(KST)  <br>없으면, 해당 발표시간에 예보된 기간 전체|
|disp|표출형태|0 : 변수별로 일정한 길이 유지, 포트란에 적합 (default)  <br>1 : 구분자(,)로 구분, 엑셀에 적합|
|help|도움말|1(도움말 정보 표시)|
|authKey|인증키|발급된 API 인증키|

##### 출력결과

   
|변수명|의미(단위)|변수명|의미(단위)|
|---|---|---|---|
|REG_ID|예보구역코드|TM_ST|시작시각(년월일시분,KST)|
|TM_ED|종료시각(년월일시분,KST)|REG_SP|특성|
|REG_NAME|예보구역명|STN_ID|발표관서|
|TM_FC|발표시각(KST)|TM_IN|입력시각(KST)|
|CNT|참조번호|MAN_FC|예보관명|
|TM_EF|발효시각(년월일시분,KST)|MOD|구간 (A01(24시간),A02(12시간))|
|NE|발효번호|STN|발표관서|
|C|발표코드|MAN_ID|예보관ID|
|W1|풍향1(16방위) (범위 시작값)|T|풍향경향|
|W2|풍향2(16방위) (범위 종료값)|TA|기온|
|ST|강수확률(%)|SKY|하늘상태코드 (DB01(맑음),DB02(구름조금),DB03(구름많음),DB04(흐림))|
|PREP|강수유무코드 (1(비),2(비/눈),4(눈/비),3(눈))|WF|예보|

#### 1.2 단기 개황, disp=1(JSON)

[https://apihub.kma.go.kr/api/typ01/url/fct_afs_ds.php?stn=&tmfc1=2013121106&tmfc2=2013121118&disp=0&help=1&authKey=YOUR_KMA_API_KEY](https://apihub.kma.go.kr/api/typ01/url/fct_afs_ds.php?stn=&tmfc1=2013121106&tmfc2=2013121118&disp=0&help=1&authKey=YOUR_KMA_API_KEY)

##### 요청인자

  
|인자명|의미|설명|
|---|---|---|
|stn|발표관서번호|없으면 전체|
|reg|예보구역코드|없으면 전체|
|tmfc|발표시간|예보구역조회에서 사용(기준시각의미, 년월일시(KST))  <br>없으면, 전체 / 0이면, 가장 최근|
|tmfc1|발표시간  <br>(기간)|기간: [tmfc1 ~ tmfc2] : 년월일시(KST)  <br>없으면, 가장 최근 발표시간자료|
|tmfc2|발표시간  <br>(기간)|기간: [tmfc1 ~ tmfc2] : 년월일시(KST)  <br>없으면, 가장 최근 발표시간자료|
|tmef1|발효시간  <br>(기간)|기간: [tmef1 ~ tmef2] : 년월일시(KST)  <br>없으면, 해당 발표시간에 예보된 기간 전체|
|tmef2|발효시간  <br>(기간)|기간: [tmef1 ~ tmef2] : 년월일시(KST)  <br>없으면, 해당 발표시간에 예보된 기간 전체|
|disp|표출형태|0 : 변수별로 일정한 길이 유지, 포트란에 적합 (default)  <br>1 : 구분자(,)로 구분, 엑셀에 적합|
|help|도움말|1(도움말 정보 표시)|
|authKey|인증키|발급된 API 인증키|

##### 출력결과

   
|변수명|의미(단위)|변수명|의미(단위)|
|---|---|---|---|
|REG_ID|예보구역코드|TM_ST|시작시각(년월일시분,KST)|
|TM_ED|종료시각(년월일시분,KST)|REG_SP|특성|
|REG_NAME|예보구역명|STN_ID|발표관서|
|TM_FC|발표시각(KST)|TM_IN|입력시각(KST)|
|CNT|참조번호|MAN_FC|예보관명|
|TM_EF|발효시각(년월일시분,KST)|MOD|구간 (A01(24시간),A02(12시간))|
|NE|발효번호|STN|발표관서|
|C|발표코드|MAN_ID|예보관ID|
|W1|풍향1(16방위) (범위 시작값)|T|풍향경향|
|W2|풍향2(16방위) (범위 종료값)|TA|기온|
|ST|강수확률(%)|SKY|하늘상태코드 (DB01(맑음),DB02(구름조금),DB03(구름많음),DB04(흐림))|
|PREP|강수유무코드 (1(비),2(비/눈),4(눈/비),3(눈))|WF|예보|

#### 1.3 단기 육상예보

[https://apihub.kma.go.kr/api/typ01/url/fct_afs_dl.php?reg=&tmfc1=2013121106&tmfc2=2013121118&disp=0&help=1&authKey=YOUR_KMA_API_KEY](https://apihub.kma.go.kr/api/typ01/url/fct_afs_dl.php?reg=&tmfc1=2013121106&tmfc2=2013121118&disp=0&help=1&authKey=YOUR_KMA_API_KEY)

##### 요청인자

  
|인자명|의미|설명|
|---|---|---|
|stn|발표관서번호|없으면 전체|
|reg|예보구역코드|없으면 전체|
|tmfc|발표시간|예보구역조회에서 사용(기준시각의미, 년월일시(KST))  <br>없으면, 전체 / 0이면, 가장 최근|
|tmfc1|발표시간  <br>(기간)|기간: [tmfc1 ~ tmfc2] : 년월일시(KST)  <br>없으면, 가장 최근 발표시간자료|
|tmfc2|발표시간  <br>(기간)|기간: [tmfc1 ~ tmfc2] : 년월일시(KST)  <br>없으면, 가장 최근 발표시간자료|
|tmef1|발효시간  <br>(기간)|기간: [tmef1 ~ tmef2] : 년월일시(KST)  <br>없으면, 해당 발표시간에 예보된 기간 전체|
|tmef2|발효시간  <br>(기간)|기간: [tmef1 ~ tmef2] : 년월일시(KST)  <br>없으면, 해당 발표시간에 예보된 기간 전체|
|disp|표출형태|0 : 변수별로 일정한 길이 유지, 포트란에 적합 (default)  <br>1 : 구분자(,)로 구분, 엑셀에 적합|
|help|도움말|1(도움말 정보 표시)|
|authKey|인증키|발급된 API 인증키|

##### 출력결과

   
|변수명|의미(단위)|변수명|의미(단위)|
|---|---|---|---|
|REG_ID|예보구역코드|TM_ST|시작시각(년월일시분,KST)|
|TM_ED|종료시각(년월일시분,KST)|REG_SP|특성|
|REG_NAME|예보구역명|STN_ID|발표관서|
|TM_FC|발표시각(KST)|TM_IN|입력시각(KST)|
|CNT|참조번호|MAN_FC|예보관명|
|TM_EF|발효시각(년월일시분,KST)|MOD|구간 (A01(24시간),A02(12시간))|
|NE|발효번호|STN|발표관서|
|C|발표코드|MAN_ID|예보관ID|
|W1|풍향1(16방위) (범위 시작값)|T|풍향경향|
|W2|풍향2(16방위) (범위 종료값)|TA|기온|
|ST|강수확률(%)|SKY|하늘상태코드 (DB01(맑음),DB02(구름조금),DB03(구름많음),DB04(흐림))|
|PREP|강수유무코드 (1(비),2(비/눈),4(눈/비),3(눈))|WF|예보|

[https://apihub.kma.go.kr/api/typ01/url/fct_afs_dl2.php?reg=&tmfc1=2020052505&tmfc2=2020052517&disp=0&help=1&authKey=YOUR_KMA_API_KEY](https://apihub.kma.go.kr/api/typ01/url/fct_afs_dl2.php?reg=&tmfc1=2020052505&tmfc2=2020052517&disp=0&help=1&authKey=YOUR_KMA_API_KEY)

##### 요청인자

  
|인자명|의미|설명|
|---|---|---|
|stn|발표관서번호|없으면 전체|
|reg|예보구역코드|없으면 전체|
|tmfc|발표시간|예보구역조회에서 사용(기준시각의미, 년월일시(KST))  <br>없으면, 전체 / 0이면, 가장 최근|
|tmfc1|발표시간  <br>(기간)|기간: [tmfc1 ~ tmfc2] : 년월일시(KST)  <br>없으면, 가장 최근 발표시간자료|
|tmfc2|발표시간  <br>(기간)|기간: [tmfc1 ~ tmfc2] : 년월일시(KST)  <br>없으면, 가장 최근 발표시간자료|
|tmef1|발효시간  <br>(기간)|기간: [tmef1 ~ tmef2] : 년월일시(KST)  <br>없으면, 해당 발표시간에 예보된 기간 전체|
|tmef2|발효시간  <br>(기간)|기간: [tmef1 ~ tmef2] : 년월일시(KST)  <br>없으면, 해당 발표시간에 예보된 기간 전체|
|disp|표출형태|0 : 변수별로 일정한 길이 유지, 포트란에 적합 (default)  <br>1 : 구분자(,)로 구분, 엑셀에 적합|
|help|도움말|1(도움말 정보 표시)|
|authKey|인증키|발급된 API 인증키|

##### 출력결과

   
|변수명|의미(단위)|변수명|의미(단위)|
|---|---|---|---|
|REG_ID|예보구역코드|TM_ST|시작시각(년월일시분,KST)|
|TM_ED|종료시각(년월일시분,KST)|REG_SP|특성|
|REG_NAME|예보구역명|STN_ID|발표관서|
|TM_FC|발표시각(KST)|TM_IN|입력시각(KST)|
|CNT|참조번호|MAN_FC|예보관명|
|TM_EF|발효시각(년월일시분,KST)|MOD|구간 (A01(24시간),A02(12시간))|
|NE|발효번호|STN|발표관서|
|C|발표코드|MAN_ID|예보관ID|
|W1|풍향1(16방위) (범위 시작값)|T|풍향경향|
|W2|풍향2(16방위) (범위 종료값)|TA|기온|
|ST|강수확률(%)|SKY|하늘상태코드 (DB01(맑음),DB02(구름조금),DB03(구름많음),DB04(흐림))|
|PREP|강수유무코드 (1(비),2(비/눈),4(눈/비),3(눈))|WF|예보|

#### 1.5 단기 해상예보

[https://apihub.kma.go.kr/api/typ01/url/fct_afs_do.php?reg=&tmfc1=2013121106&tmfc2=2013121118&disp=0&help=1&authKey=YOUR_KMA_API_KEY](https://apihub.kma.go.kr/api/typ01/url/fct_afs_do.php?reg=&tmfc1=2013121106&tmfc2=2013121118&disp=0&help=1&authKey=YOUR_KMA_API_KEY)

##### 요청인자

  
|인자명|의미|설명|
|---|---|---|
|stn|발표관서번호|없으면 전체|
|reg|예보구역코드|없으면 전체|
|tmfc|발표시간|예보구역조회에서 사용(기준시각의미, 년월일시(KST))  <br>없으면, 전체 / 0이면, 가장 최근|
|tmfc1|발표시간  <br>(기간)|기간: [tmfc1 ~ tmfc2] : 년월일시(KST)  <br>없으면, 가장 최근 발표시간자료|
|tmfc2|발표시간  <br>(기간)|기간: [tmfc1 ~ tmfc2] : 년월일시(KST)  <br>없으면, 가장 최근 발표시간자료|
|tmef1|발효시간  <br>(기간)|기간: [tmef1 ~ tmef2] : 년월일시(KST)  <br>없으면, 해당 발표시간에 예보된 기간 전체|
|tmef2|발효시간  <br>(기간)|기간: [tmef1 ~ tmef2] : 년월일시(KST)  <br>없으면, 해당 발표시간에 예보된 기간 전체|
|disp|표출형태|0 : 변수별로 일정한 길이 유지, 포트란에 적합 (default)  <br>1 : 구분자(,)로 구분, 엑셀에 적합|
|help|도움말|1(도움말 정보 표시)|
|authKey|인증키|발급된 API 인증키|

##### 출력결과

   
|변수명|의미(단위)|변수명|의미(단위)|
|---|---|---|---|
|REG_ID|예보구역코드|TM_ST|시작시각(년월일시분,KST)|
|TM_ED|종료시각(년월일시분,KST)|REG_SP|특성|
|REG_NAME|예보구역명|STN_ID|발표관서|
|TM_FC|발표시각(KST)|TM_IN|입력시각(KST)|
|CNT|참조번호|MAN_FC|예보관명|
|TM_EF|발효시각(년월일시분,KST)|MOD|구간 (A01(24시간),A02(12시간))|
|NE|발효번호|STN|발표관서|
|C|발표코드|MAN_ID|예보관ID|
|W1|풍향1(16방위) (범위 시작값)|T|풍향경향|
|W2|풍향2(16방위) (범위 종료값)|TA|기온|
|ST|강수확률(%)|SKY|하늘상태코드 (DB01(맑음),DB02(구름조금),DB03(구름많음),DB04(흐림))|
|PREP|강수유무코드 (1(비),2(비/눈),4(눈/비),3(눈))|WF|예보|
|S1|풍속1 (범위 시작값)|S2|풍속2 (범위 종료값)|
|WH1|파고1 (범위 시작값)|WH2|파고2 (범위 종료값)|

### 2. 동네예보(단기예보, 초단기예보, 실황) 격자자료

동네예보 격자영역 정보 [참고자료](https://apihub.kma.go.kr/getAttachFile.do?fileName=\(20240305\)%EB%8F%99%EB%84%A4%EC%98%88%EB%B3%B4%20%EA%B2%A9%EC%9E%90%EC%98%81%EC%97%AD%20%EC%A0%95%EB%B3%B4.pdf)

단기예보 예보기간 확대에 따른 변경사항 [참고자료](https://apihub.kma.go.kr/getAttachFile.do?fileName=\(20241128\)%EB%8B%A8%EA%B8%B0%EC%98%88%EB%B3%B4%20%EC%84%9C%EB%B9%84%EC%8A%A4%20%EA%B0%9C%EC%84%A0%EC%97%90%20%EB%94%B0%EB%A5%B8%20API%20%EB%B3%80%EA%B2%BD%EC%82%AC%ED%95%AD.pdf)

#### 2.1 단기예보

[https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-dfs_shrt_grd?tmfc=2024022505&tmef=2024022506&vars=TMP&authKey=YOUR_KMA_API_KEY](https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-dfs_shrt_grd?tmfc=2024022505&tmef=2024022506&vars=TMP&authKey=YOUR_KMA_API_KEY)

##### 요청인자

  
|인자명|의미|설명|
|---|---|---|
|tmfc|발표시간|연월일시(KST)  <br>- 3시간 간격 생산(매일 2시, 5시, 8시, 11시, 14시, 17시, 20시, 23시 발표)|
|tmef|발효시간|년월일시(KST)  <br>- (2024.11.28. 14시 이전) 1시간 간격으로 제공(2, 5, 8, 11, 14시는 모레 자정까지, 17, 20, 23시는 글피 자정까지 제공)  <br>- (2024.11.28. 14시 이후) 1시간 간격으로 제공(2, 5, 8, 11, 14시는 글피 자정까지, 17, 20, 23시는 그글피 자정까지 제공)|
|vars|예보변수|TMP(기온), TMX(최고기온), TMN(최저기온), UUU(동서바람성분), VVV(남북바람성분), VEC(풍향), WSD(풍속), SKY(하늘상태), PTY(강수형태), POP(강수유무), PCP(1시간 강수량), SNO(1시간 신적설), REH(상대습도), WAV(파고)|
|authKey|인증키|발급된 API 인증키|

#### 2.2 초단기예보

[https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-dfs_vsrt_grd?tmfc=202403011010&tmef=2024030111&vars=T1H&authKey=YOUR_KMA_API_KEY](https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-dfs_vsrt_grd?tmfc=202403011010&tmef=2024030111&vars=T1H&authKey=YOUR_KMA_API_KEY)

##### 요청인자

  
|인자명|의미|설명|
|---|---|---|
|tmfc|발표시간|연월일시분(KST)  <br>- 10분 간격 발표|
|tmef|발효시간|년월일시(KST)  <br>- 발표시간 기준 6시간 까지 1시간 간격으로 제공|
|vars|예보변수|T1H(기온), UUU(동서바람성분), VVV(남북바람성분), VEC(풍향), WSD(풍속), SKY(하늘상태), LGT(낙뢰), PTY(강수형태), RN1(1시간 강수량), REH(상대습도)|
|authKey|인증키|발급된 API 인증키|

#### 2.3 실황

[https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-dfs_odam_grd?tmfc=202403051010&vars=T1H&authKey=YOUR_KMA_API_KEY](https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-dfs_odam_grd?tmfc=202403051010&vars=T1H&authKey=YOUR_KMA_API_KEY)

##### 요청인자

  
|인자명|의미|설명|
|---|---|---|
|tmfc|발표시간|연월일시분(KST)  <br>- (2024.3.4. 오전 10시 이후) 10분 간격 발표  <br>- (2024.3.4. 오전 10시 이전) 1시간(매 정시) 간격 발표|
|vars|변수|T1H(기온), UUU(동서바람성분), VVV(남북바람성분), VEC(풍향), WSD(풍속), PTY(강수형태), RN1(1시간 강수량), REH(상대습도)|
|authKey|인증키|발급된 API 인증키|

#### 2.4.1 동네예보 격자 번호 → 위·경도 변환

[https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-dfs_xy_lonlat?x=60&y=127&help=1&authKey=YOUR_KMA_API_KEY](https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-dfs_xy_lonlat?x=60&y=127&help=1&authKey=YOUR_KMA_API_KEY)

#### 2.4.2 임의 위·경도 → 인근 동네예보 격자 번호 변환

[https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-dfs_xy_lonlat?lon=127.5&lat=36.5&help=0&authKey=YOUR_KMA_API_KEY](https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-dfs_xy_lonlat?lon=127.5&lat=36.5&help=0&authKey=YOUR_KMA_API_KEY)

##### 요청인자

  
|인자명|의미|설명|
|---|---|---|
|x|동네예보 격자 번호(동서방향)|범위: 1 ~ 149|
|y|동네예보 격자 번호(남북방향)|범위: 1 ~ 253|
|lon|임의 경도|범위: 123.310165 ~ 132.774963|
|lat|임의 위도|범위: 31.651814 ~ 43.393490|
|help|도움말|0(도움말 정보 표시 안됨), 1(도움말 정보 표시)|
|authKey|인증키|발급된 API 인증키|

##### 출력결과

   
| 변수명 | 의미(단위)           | 변수명 | 의미(단위)           |
| --- | ---------------- | --- | ---------------- |
| lon | 격자 경도            | lat | 격자 위도            |
| x   | 동네예보 격자 번호(동서방향) | y   | 동네예보 격자 번호(남북방향) |
