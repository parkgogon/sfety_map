---
trigger: always_on
---



|   |   |
|---|---|
|개요|호우, 대설, 폭풍해일 등 10개 기상현상으로 인해 중대한 재해발생이 예상될 때 해당 지역에 대하여 기상특보의 발표 기준에 따라 주의보 및 경보로 구분하여 발표합니다.  <br>기상특보는 171개 시 · 군 단위와 33개(먼바다 8개, 앞바다 25개) 해역으로 세분화하여 발표하여 국민의 생명과 재산을 지키는데 최선을 다합니다.|
|요 소|강풍, 풍랑, 호우, 대설, 건조, 폭풍해일, 한파, 태풍, 황사, 폭염|
|지 점|전국 171개 시 · 군 단위와 33개 해역|
|보유기간|2004년 6월 30일 ~ 현재|
|생산주기|특보 발표시|

### 1. 특.정보 자료 조회

#### 1.1 특보구역

[https://apihub.kma.go.kr/api/typ01/url/wrn_reg.php?tmfc=0&authKey=a7c780dkQDC3O_NHZOAwuw](https://apihub.kma.go.kr/api/typ01/url/wrn_reg.php?tmfc=0&authKey=a7c780dkQDC3O_NHZOAwuw)

##### 요청인자

  
|인자명|의미|설명|
|---|---|---|
|wrn|특보종류|W: 강풍, R: 호우, C: 한파, D: 건조, O: 해일, N: 지진해일, V:풍랑, T: 태풍, S: 대설, Y: 황사, H: 폭염, F: 안개 (없으면 전체)|
|reg|특보구역|없으면 전체|
|tmfc1|발표시간  <br>(기간)|- 기간: [tmfc1 ~ tmfc2] : 년월일시분(KST)  <br>- tmfc2가 없으면 현재시각으로 처리|
|tmfc2|발표시간  <br>(기간)|- 기간: [tmfc1 ~ tmfc2] : 년월일시분(KST)  <br>- tmfc2가 없으면 현재시각으로 처리|
|subcd|날씨해설  <br>부제목코드|11(초단기), 12(단기), 13(중기), 99(직접입력), 없으면 전체|
|disp|표출단계|0(기본), 1(+특보내용), 2(+입력자)|
|help|도움말|1(도움말 정보 표시)|
|authKey|인증키|발급된 API 인증키|

##### 출력결과

   
|변수명|의미(단위)|변수명|의미(단위)|
|---|---|---|---|
|REG_ID|특보구역코드|TM_ST|시작시각(년월일시분,KST)|
|TM_ED|종료시각(년월일시분,KST)|REG_SP|특성|
|REG_UP|상위 특보구역코드|REG_KO|특보구역명(약어)|
|REG_NAME|특보구역명|TM_FC|발표시각(KST)|
|TM_EF|발효시각(KST)|TM_IN|입력시각(KST)|
|STN|발표관서|WRN|특보종류코드|
|LVL|특보수준|CMD|특보명령|
|GRD|태풍경보시 등급|CNT|작업상태|
|RPT|통보문 발송구분|STN_ID|발표관서|
|TM_SEQ|발표번호|MAN_FC|예보관명|
|MAN_IN|입력자명|||

#### 1.2 특보자료

[https://apihub.kma.go.kr/api/typ01/url/wrn_met_data.php?reg=0&wrn=A&tmfc1=201501010000&tmfc2=201502010000&disp=0&help=1&authKey=a7c780dkQDC3O_NHZOAwuw](https://apihub.kma.go.kr/api/typ01/url/wrn_met_data.php?reg=0&wrn=A&tmfc1=201501010000&tmfc2=201502010000&disp=0&help=1&authKey=a7c780dkQDC3O_NHZOAwuw)

##### 요청인자

  
|인자명|의미|설명|
|---|---|---|
|wrn|특보종류|W: 강풍, R: 호우, C: 한파, D: 건조, O: 해일, N: 지진해일, V:풍랑, T: 태풍, S: 대설, Y: 황사, H: 폭염, F: 안개 (없으면 전체)|
|reg|특보구역|없으면 전체|
|tmfc1|발표시간  <br>(기간)|- 기간: [tmfc1 ~ tmfc2] : 년월일시분(KST)  <br>- tmfc2가 없으면 현재시각으로 처리|
|tmfc2|발표시간  <br>(기간)|- 기간: [tmfc1 ~ tmfc2] : 년월일시분(KST)  <br>- tmfc2가 없으면 현재시각으로 처리|
|subcd|날씨해설  <br>부제목코드|11(초단기), 12(단기), 13(중기), 99(직접입력), 없으면 전체|
|disp|표출단계|0(기본), 1(+특보내용), 2(+입력자)|
|help|도움말|1(도움말 정보 표시)|
|authKey|인증키|발급된 API 인증키|

##### 출력결과

   
|변수명|의미(단위)|변수명|의미(단위)|
|---|---|---|---|
|REG_ID|특보구역코드|TM_ST|시작시각(년월일시분,KST)|
|TM_ED|종료시각(년월일시분,KST)|REG_SP|특성|
|REG_UP|상위 특보구역코드|REG_KO|특보구역명(약어)|
|REG_NAME|특보구역명|TM_FC|발표시각(KST)|
|TM_EF|발효시각(KST)|TM_IN|입력시각(KST)|
|STN|발표관서|WRN|특보종류코드|
|LVL|특보수준|CMD|특보명령|
|GRD|태풍경보시 등급|CNT|작업상태|
|RPT|통보문 발송구분|STN_ID|발표관서|
|TM_SEQ|발표번호|MAN_FC|예보관명|
|MAN_IN|입력자명|||

#### 1.3 기상정보

[https://apihub.kma.go.kr/api/typ01/url/wrn_inf_rpt.php?tmfc1=201505010000&tmfc2=201506010000&stn=0&disp=0&help=1&authKey=a7c780dkQDC3O_NHZOAwuw](https://apihub.kma.go.kr/api/typ01/url/wrn_inf_rpt.php?tmfc1=201505010000&tmfc2=201506010000&stn=0&disp=0&help=1&authKey=a7c780dkQDC3O_NHZOAwuw)

##### 요청인자

  
|인자명|의미|설명|
|---|---|---|
|wrn|특보종류|W: 강풍, R: 호우, C: 한파, D: 건조, O: 해일, N: 지진해일, V:풍랑, T: 태풍, S: 대설, Y: 황사, H: 폭염, F: 안개 (없으면 전체)|
|reg|특보구역|없으면 전체|
|tmfc1|발표시간  <br>(기간)|- 기간: [tmfc1 ~ tmfc2] : 년월일시분(KST)  <br>- tmfc2가 없으면 현재시각으로 처리|
|tmfc2|발표시간  <br>(기간)|- 기간: [tmfc1 ~ tmfc2] : 년월일시분(KST)  <br>- tmfc2가 없으면 현재시각으로 처리|
|subcd|날씨해설  <br>부제목코드|11(초단기), 12(단기), 13(중기), 99(직접입력), 없으면 전체|
|disp|표출단계|0(기본), 1(+특보내용), 2(+입력자)|
|help|도움말|1(도움말 정보 표시)|
|authKey|인증키|발급된 API 인증키|

##### 출력결과

   
|변수명|의미(단위)|변수명|의미(단위)|
|---|---|---|---|
|REG_ID|특보구역코드|TM_ST|시작시각(년월일시분,KST)|
|TM_ED|종료시각(년월일시분,KST)|REG_SP|특성|
|REG_UP|상위 특보구역코드|REG_KO|특보구역명(약어)|
|REG_NAME|특보구역명|TM_FC|발표시각(KST)|
|TM_EF|발효시각(KST)|TM_IN|입력시각(KST)|
|STN|발표관서|WRN|특보종류코드|
|LVL|특보수준|CMD|특보명령|
|GRD|태풍경보시 등급|CNT|작업상태|
|RPT|통보문 발송구분|STN_ID|발표관서|
|TM_SEQ|발표번호|MAN_FC|예보관명|
|MAN_IN|입력자명|||

#### 1.4 날씨해설

[https://apihub.kma.go.kr/api/typ01/url/wthr_cmt_rpt.php?tmfc1=202004130000&tmfc2=202004140000&stn=0&subcd=0&disp=0&help=1&authKey=a7c780dkQDC3O_NHZOAwuw](https://apihub.kma.go.kr/api/typ01/url/wthr_cmt_rpt.php?tmfc1=202004130000&tmfc2=202004140000&stn=0&subcd=0&disp=0&help=1&authKey=a7c780dkQDC3O_NHZOAwuw)

##### 요청인자

  
|인자명|의미|설명|
|---|---|---|
|wrn|특보종류|W: 강풍, R: 호우, C: 한파, D: 건조, O: 해일, N: 지진해일, V:풍랑, T: 태풍, S: 대설, Y: 황사, H: 폭염, F: 안개 (없으면 전체)|
|reg|특보구역|없으면 전체|
|tmfc1|발표시간  <br>(기간)|- 기간: [tmfc1 ~ tmfc2] : 년월일시분(KST)  <br>- tmfc2가 없으면 현재시각으로 처리|
|tmfc2|발표시간  <br>(기간)|- 기간: [tmfc1 ~ tmfc2] : 년월일시분(KST)  <br>- tmfc2가 없으면 현재시각으로 처리|
|subcd|날씨해설  <br>부제목코드|11(초단기), 12(단기), 13(중기), 99(직접입력), 없으면 전체|
|disp|표출단계|0(기본), 1(+특보내용), 2(+입력자)|
|help|도움말|1(도움말 정보 표시)|
|authKey|인증키|발급된 API 인증키|

##### 출력결과

   
|변수명|의미(단위)|변수명|의미(단위)|
|---|---|---|---|
|REG_ID|특보구역코드|TM_ST|시작시각(년월일시분,KST)|
|TM_ED|종료시각(년월일시분,KST)|REG_SP|특성|
|REG_UP|상위 특보구역코드|REG_KO|특보구역명(약어)|
|REG_NAME|특보구역명|TM_FC|발표시각(KST)|
|TM_EF|발효시각(KST)|TM_IN|입력시각(KST)|
|STN|발표관서|WRN|특보종류코드|
|LVL|특보수준|CMD|특보명령|
|GRD|태풍경보시 등급|CNT|작업상태|
|RPT|통보문 발송구분|STN_ID|발표관서|
|TM_SEQ|발표번호|MAN_FC|예보관명|
|MAN_IN|입력자명|||

### 2. 특보현황 조회

[https://apihub.kma.go.kr/api/typ01/url/wrn_now_data.php?fe=f&tm=&disp=0&help=1&authKey=a7c780dkQDC3O_NHZOAwuw](https://apihub.kma.go.kr/api/typ01/url/wrn_now_data.php?fe=f&tm=&disp=0&help=1&authKey=a7c780dkQDC3O_NHZOAwuw)

##### 요청인자

  
|인자명|의미|설명|
|---|---|---|
|fe|기준|f: 발표시간기준(default), e: 발효시간기준|
|tm|기준시각|년월일시분(KST)|
|help|도움말|1(도움말 정보 표시)|
|authKey|인증키|발급된 API 인증키|

##### 출력결과

   
|변수명|의미(단위)|변수명|의미(단위)|
|---|---|---|---|
|REG_UP|상위 특보구역코드|REG_UP_KO|상위 특보구역명|
|REG_ID|특보구역코드|REG_KO|특보구역명|
|TM_FC|발표시각(년월일시분,KST)|TM_EF|발효시각(년월일시분,KST)|
|WRN|특보종류|LVL|특보수준|
|CMD|특보명령|||

[https://apihub.kma.go.kr/api/typ01/url/wrn_now_data_new.php?fe=f&tm=&disp=0&help=1&authKey=a7c780dkQDC3O_NHZOAwuw](https://apihub.kma.go.kr/api/typ01/url/wrn_now_data_new.php?fe=f&tm=&disp=0&help=1&authKey=a7c780dkQDC3O_NHZOAwuw)

##### 요청인자

  
|인자명|의미|설명|
|---|---|---|
|fe|기준|f: 발표시간기준(default), e: 발효시간기준|
|tm|기준시각|년월일시분(KST)|
|help|도움말|1(도움말 정보 표시)|
|authKey|인증키|발급된 API 인증키|

##### 출력결과

   
|변수명|의미(단위)|변수명|의미(단위)|
|---|---|---|---|
|REG_UP|상위 특보구역코드|REG_UP_KO|상위 특보구역명|
|REG_ID|특보구역코드|REG_KO|특보구역명|
|TM_FC|발표시각(년월일시분,KST)|TM_EF|발효시각(년월일시분,KST)|
|WRN|특보종류|LVL|특보수준|
|CMD|특보명령|||

### 3. 특보 발표/발효 현황 이미지 조회

#### 3.1 임의지역 특보이미지

[https://apihub.kma.go.kr/api/typ03/cgi/wrn/nph-wrn7?out=0&tmef=1&city=1&name=0&tm=201611082300&lon=127.7&lat=36.1&range=300&size=685&wrn=W,R,C,D,O,V,T,S,Y,H,&authKey=a7c780dkQDC3O_NHZOAwuw](https://apihub.kma.go.kr/api/typ03/cgi/wrn/nph-wrn7?out=0&tmef=1&city=1&name=0&tm=201611082300&lon=127.7&lat=36.1&range=300&size=685&wrn=W,R,C,D,O,V,T,S,Y,H,&authKey=a7c780dkQDC3O_NHZOAwuw)

##### 요청인자

  
|인자명|의미|설명|
|---|---|---|
|tm|조회시각  <br>(특보 발표시각)|년월일시분(KST)|
|lon|경도|임의지역 특보이미지의 중심 경도|
|lat|위도|임의지역 특보이미지의 중심 위도|
|range|표출반경(km)|특보 이미지의 중심(위경도)으로부터 표출반경|
|size|크기(px)|특보 이미지 크기|
|tmef|발표/발효 구분|발표/발효 구분 (0:발표시각기준, 1:발효시각기준)|
|city|시군경계|시군경계 표시유무 (0:미표시, 1:표시)|
|name|행정동명|행정동명 표시유무 (0:미표시, 1:표시)|
|stn|지방청별 조회|특보이미지 지방청별 조회(기존 통보문 이미지)  <br>- 108: 본청, 133: 대전, 159: 부산, 156: 광주, 184: 제주, 105: 강원|
|wrn|특보종류|특보종류(여러유형 선택시 델리미터(\|)로 구분)  <br>- W: 강풍, R: 호우, C: 한파, D: 건조, O: 해일, N: 지진해일, V:풍랑,  <br>T: 태풍, S: 대설, Y: 황사, H: 폭염, F: 안개|
|authKey|인증키|발급된 API 인증키|

Copyright(c) KMA. All Rights Reserved. 연락처 : kmadatahub@korea.kr [**개인정보 처리방침**](https://apihub.kma.go.kr/personalInfo.do)

[![공공누리 공공저작물 자유이용허 - 출처표시](https://apihub.kma.go.kr/static/images/awp/mark_copy.png)](http://www.kogl.or.kr/info/license.do)