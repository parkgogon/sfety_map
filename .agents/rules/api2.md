---
trigger: always_on
---


### 3. 동네예보 통보문 조회

동네예보 통보문 조회서비스 API 활용가이드 [참고자료](https://apihub.kma.go.kr/getAttachFile.do?fileName=%EB%8F%99%EB%84%A4%EC%98%88%EB%B3%B4%20%ED%86%B5%EB%B3%B4%EB%AC%B8%20%EC%A1%B0%ED%9A%8C%EC%84%9C%EB%B9%84%EC%8A%A4_API%ED%99%9C%EC%9A%A9%EA%B0%80%EC%9D%B4%EB%93%9C_241128.docx)

동네예보 통보문 조회서비스 지점목록 [참고자료](https://apihub.kma.go.kr/getAttachFile.do?fileName=\(20260324\)%EB%8F%99%EB%84%A4%EC%98%88%EB%B3%B4%ED%86%B5%EB%B3%B4%EB%AC%B8%EC%A1%B0%ED%9A%8C%EC%84%9C%EB%B9%84%EC%8A%A4_API%ED%99%9C%EC%9A%A9%EA%B0%80%EC%9D%B4%EB%93%9C_%EC%A7%80%EC%A0%90%EB%AA%A9%EB%A1%9D.xlsx)

#### 3.1 기상개황조회

[https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstMsgService/getWthrSituation?pageNo=1&numOfRows=10&dataType=XML&stnId=108&authKey=YOUR_KMA_API_KEY](https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstMsgService/getWthrSituation?pageNo=1&numOfRows=10&dataType=XML&stnId=108&authKey=YOUR_KMA_API_KEY)

##### 요청인자

  
|인자명|의미|설명|
|---|---|---|
|pageNo|페이지 번호|페이지번호|
|numOfRows|한 페이지 결과 수|한 페이지 결과 수|
|dataType|응답자료형식|요청자료형식(XML/JSON)Default: XML|
|stnId|발표관서|108 기상청, 109 수도권(서울)..등 별첨 엑셀자료 참조(‘개황’ 구분 값 참고)|
|authKey|인증키|발급된 API 인증키|

##### 출력결과

   
|변수명|의미(단위)|변수명|의미(단위)|
|---|---|---|---|
|resultCode|결과코드|resultMsg|결과메시지|
|numOfRows|한 페이지 결과 수|pageNo|페이지 번호|
|totalCount|전체 결과 수|dataType|데이터 타입|
|stnId|발표관서|tmFc|발표시간|
|wfSv1|기상개황(종합)|wn|특보사항|
|wr|예비특보|||

#### 3.2 육상예보조회

[https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstMsgService/getLandFcst?pageNo=1&numOfRows=10&dataType=XML®Id=11A00101&authKey=YOUR_KMA_API_KEY](https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstMsgService/getLandFcst?pageNo=1&numOfRows=10&dataType=XML&regId=11A00101&authKey=YOUR_KMA_API_KEY)

##### 요청인자

  
|인자명|의미|설명|
|---|---|---|
|pageNo|페이지 번호|페이지번호|
|numOfRows|한 페이지 결과 수|한 페이지 결과 수|
|dataType|응답자료형식|요청자료형식(XML/JSON) Default: XML|
|regId|예보구역코드|11A00101(백령도), 11B10101 (서울), 11B20201(인천) 등... 별첨 엑셀자료 참조(‘육상’ 구분 값 참고)|
|authKey|인증키|발급된 API 인증키|

##### 출력결과

   
|변수명|의미(단위)|변수명|의미(단위)|
|---|---|---|---|
|resultCode|결과코드|resultMsg|결과메시지|
|numOfRows|한 페이지 결과 수|pageNo|페이지 번호|
|totalCount|전체 결과 수|dataType|데이터 타입|
|regId|예보구역코드|announceTime|발표시간|
|numEf|발효번호(발표시간기준)|wd1|풍향(1)|
|wdTnd|풍향연결코드|wd2|풍향(2)|
|wsIt|풍속 강도코드|ta|예상기온(℃)|
|rnSt|강수확률|wf|날씨|
|wfCd|날씨코드(하늘상태)|rnYn|강수형태|

#### 3.3 해상예보조회

[https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstMsgService/getSeaFcst?pageNo=1&numOfRows=10&dataType=XML®Id=12A20100&authKey=YOUR_KMA_API_KEY](https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstMsgService/getSeaFcst?pageNo=1&numOfRows=10&dataType=XML&regId=12A20100&authKey=YOUR_KMA_API_KEY)

##### 요청인자

  
|인자명|의미|설명|
|---|---|---|
|pageNo|페이지 번호|페이지번호|
|numOfRows|한 페이지 결과 수|한 페이지 결과 수|
|dataType|응답자료형식|요청자료형식(XML/JSON)Default: XML|
|regId|예보구역코드|12A20100 (서해중부앞바다), 12B20100(남해동부앞바다) 등... 별첨 엑셀자료 참조(‘해상’ 구분 값 참고)|
|authKey|인증키|발급된 API 인증키|

##### 출력결과

   
|변수명|의미(단위)|변수명|의미(단위)|
|---|---|---|---|
|resultCode|결과코드|resultMsg|결과메시지|
|numOfRows|한 페이지 결과 수|pageNo|페이지 번호|
|totalCount|전체 결과 수|dataType|데이터 타입|
|regId|예보구역코드|tmFc|발표시간|
|numEf|발효번호|wd1|풍향1|
|wdTnd|풍향연결코드|wd2|풍향(2)|
|ws1|풍속1(m/s)|ws2|풍속2(m/s)|
|wh1|파고1(m)|wh2|파고2(m)|
|wf|날씨|wfCd|날씨예보코드|
|rnYn|강수형태|||

### 4. 동네예보(초단기실황·초단기예보·단기예보) 조회

동네예보 지점 좌표(위경도) [참고자료](https://apihub.kma.go.kr/getAttachFile.do?fileName=%EB%8F%99%EB%84%A4%EC%98%88%EB%B3%B4%EC%A7%80%EC%A0%90%EC%A2%8C%ED%91%9C\(%EC%9C%84%EA%B2%BD%EB%8F%84\)_202601.xlsx)

API 활용가이드 [참고자료](https://apihub.kma.go.kr/getAttachFile.do?fileName=%EB%8B%A8%EA%B8%B0%EC%98%88%EB%B3%B4%20%EC%A1%B0%ED%9A%8C%EC%84%9C%EB%B9%84%EC%8A%A4_API%ED%99%9C%EC%9A%A9%EA%B0%80%EC%9D%B4%EB%93%9C_241128.docx)

#### 4.1 초단기실황조회

[https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getUltraSrtNcst?pageNo=1&numOfRows=1000&dataType=XML&base_date=20210628&base_time=0600&nx=55&ny=127&authKey=YOUR_KMA_API_KEY](https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getUltraSrtNcst?pageNo=1&numOfRows=1000&dataType=XML&base_date=20210628&base_time=0600&nx=55&ny=127&authKey=YOUR_KMA_API_KEY)

##### 요청인자

  
|인자명|의미|설명|
|---|---|---|
|pageNo|페이지 번호|페이지번호|
|numOfRows|한 페이지 결과 수|한 페이지 결과 수|
|dataType|응답자료형식|요청자료형식(XML/JSON) Default: XML|
|base_date|발표일자|‘21년 6월 28일 발표|
|base_time|발표시각|06시 발표(정시단위)|
|nx|예보지점 X 좌표|예보지점의 X 좌표값|
|ny|예보지점 Y 좌표|예보지점의 Y 좌표값|
|authKey|인증키|발급된 API 인증키|

##### 출력결과

   
|변수명|의미(단위)|변수명|의미(단위)|
|---|---|---|---|
|resultCode|결과코드|resultMsg|결과메시지|
|numOfRows|한 페이지 결과 수|pageNo|페이지 번호|
|totalCount|전체 결과 수|dataType|데이터 타입|
|baseDate|발표일자|baseTime|발표시각|
|nx|예보지점 X 좌표|ny|예보지점 Y 좌표|
|category|자료구분코드|obsrValue|실황 값|

#### 4.2 초단기예보조회

[https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getUltraSrtFcst?pageNo=1&numOfRows=1000&dataType=XML&base_date=20210628&base_time=0630&nx=55&ny=127&authKey=YOUR_KMA_API_KEY](https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getUltraSrtFcst?pageNo=1&numOfRows=1000&dataType=XML&base_date=20210628&base_time=0630&nx=55&ny=127&authKey=YOUR_KMA_API_KEY)

##### 요청인자

  
|인자명|의미|설명|
|---|---|---|
|pageNo|페이지 번호|페이지번호|
|numOfRows|한 페이지 결과 수|한 페이지 결과 수|
|dataType|응답자료형식|요청자료형식(XML/JSON) Default: XML|
|base_date|발표일자|‘21년 6월 28일 발표|
|base_time|발표시각|06시30분 발표(30분 단위)|
|nx|예보지점 X 좌표|예보지점 X 좌표값|
|ny|예보지점 Y 좌표|예보지점 Y 좌표값|
|authKey|인증키|발급된 API 인증키|

##### 출력결과

   
|변수명|의미(단위)|변수명|의미(단위)|
|---|---|---|---|
|resultCode|결과코드|resultMsg|결과메시지|
|numOfRows|한 페이지 결과 수|pageNo|페이지 번호|
|totalCount|전체 결과 수|dataType|데이터 타입|
|baseDate|발표일자|baseTime|발표시각|
|nx|예보지점 X 좌표|ny|예보지점 Y 좌표|
|category|자료구분코드|fcstDate|예측일자|
|fcstTime|예측시간|fcstValue|예보 값|

#### 4.3 단기예보조회

[https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getVilageFcst?pageNo=1&numOfRows=1000&dataType=XML&base_date=20210628&base_time=0500&nx=55&ny=127&authKey=YOUR_KMA_API_KEY](https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getVilageFcst?pageNo=1&numOfRows=1000&dataType=XML&base_date=20210628&base_time=0500&nx=55&ny=127&authKey=YOUR_KMA_API_KEY)

##### 요청인자

  
|인자명|의미|설명|
|---|---|---|
|pageNo|페이지 번호|페이지번호|
|numOfRows|한 페이지 결과 수|한 페이지 결과 수|
|dataType|응답자료형식|요청자료형식(XML/JSON) Default: XML|
|base_date|발표일자|‘21년 6월 28일발표|
|base_time|발표시각|05시 발표|
|nx|예보지점 X 좌표|예보지점의 X 좌표값|
|ny|예보지점 Y 좌표|예보지점의 Y 좌표값|
|authKey|인증키|발급된 API 인증키|

##### 출력결과

   
|변수명|의미(단위)|변수명|의미(단위)|
|---|---|---|---|
|resultCode|결과코드|resultMsg|결과메시지|
|numOfRows|한 페이지 결과 수|pageNo|페이지 번호|
|totalCount|전체 결과 수|dataType|데이터 타입|
|baseDate|발표일자|baseTime|발표시각|
|fcstDate|예보일자|fcstTime|예보시각|
|category|자료구분문자|fcstValue|예보 값|
|nx|예보지점 X 좌표|ny|예보지점 Y 좌표|

#### 4.4 예보버전조회

[https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getFcstVersion?pageNo=1&numOfRows=1000&dataType=XML&ftype=ODAM&basedatetime=202106280800&authKey=YOUR_KMA_API_KEY](https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getFcstVersion?pageNo=1&numOfRows=1000&dataType=XML&ftype=ODAM&basedatetime=202106280800&authKey=YOUR_KMA_API_KEY)

##### 요청인자

  
|인자명|의미|설명|
|---|---|---|
|pageNo|페이지 번호|페이지번호|
|numOfRows|한 페이지 결과 수|한 페이지 결과 수|
|dataType|응답자료형식|요청자료형식(XML/JSON) Default: XML|
|ftype|파일구분|파일구분 -ODAM: 동네예보실황 -VSRT: 동네예보초단기 -SHRT: 동네예보단기|
|basedatetime|발표일시분|각각의 base_time 로 검색|
|authKey|인증키|발급된 API 인증키|

##### 출력결과

   
| 변수명        | 의미(단위)     | 변수명       | 의미(단위) |
| ---------- | ---------- | --------- | ------ |
| resultCode | 결과코드       | resultMsg | 결과메시지  |
| numOfRows  | 한 페이지 결과 수 | pageNo    | 페이지 번호 |
| totalCount | 전체 결과 수    | dataType  | 데이터 타입 |
| version    | 파일버전       | filetype  | 파일구분   |

### 5. (그래픽) 동네예보 분포도

[https://apihub.kma.go.kr/api/typ03/cgi/dfs/nph-dfs_shrt_ana_5d_test?data0=GEMD&data1=PTY&tm_ef=202212260000&tm_fc=202212221400&dtm=H0&map=G1&mask=M&color=E&size=600&effect=NTL&overlay=S&zoom_rate=2&zoom_level=0&zoom_x=0000000&zoom_y=0000000&auto_man=m&mode=I&interval=1&rand=1412&authKey=YOUR_KMA_API_KEY](https://apihub.kma.go.kr/api/typ03/cgi/dfs/nph-dfs_shrt_ana_5d_test?data0=GEMD&data1=PTY&tm_ef=202212260000&tm_fc=202212221400&dtm=H0&map=G1&mask=M&color=E&size=600&effect=NTL&overlay=S&zoom_rate=2&zoom_level=0&zoom_x=0000000&zoom_y=0000000&auto_man=m&mode=I&interval=1&rand=1412&authKey=YOUR_KMA_API_KEY)

##### 요청인자

  
|인자명|의미|설명|
|---|---|---|
|data0|자료 종류||
|data1|변수 종류||
|tm_ef|기준시간2||
|tm_fc|기준시간1||
|dtm|시간이동단위 및 이동값||
|map|지도 종류||
|mask|이미지 내륙구분||
|color|이미지 색상표||
|size|이미지 크기||
|effect|이미지 효과||
|overlay|이미지 중첩||
|zoom_rate|확대율||
|auto_man|자동(a), 수동(m)||
|mode|표출양식|html(H), image(I), auto(A), file(F)|
|interval|1시간 간격 표출||
|rand|난수: 이미지 재생성 시간간격(분)||
|authKey|인증키|발급된 API 인증키|

### 6. (그래픽) 초단기예보 분포도

[https://apihub.kma.go.kr/api/typ03/cgi/dfs/nph-dfs_vsrt_ana2?data0=GEMD&tm_fc=202212221420&data1=SKY&tm_ef=202212221500&dtm=H0&map=G1&mask=M&color=E&size=600&effect=GTL&overlay=S&zoom_rate=2&zoom_level=0&zoom_x=0000000&zoom_y=0000000&auto_man=m&mode=I&rand=2937&authKey=YOUR_KMA_API_KEY](https://apihub.kma.go.kr/api/typ03/cgi/dfs/nph-dfs_vsrt_ana2?data0=GEMD&tm_fc=202212221420&data1=SKY&tm_ef=202212221500&dtm=H0&map=G1&mask=M&color=E&size=600&effect=GTL&overlay=S&zoom_rate=2&zoom_level=0&zoom_x=0000000&zoom_y=0000000&auto_man=m&mode=I&rand=2937&authKey=YOUR_KMA_API_KEY)

##### 요청인자

  
|인자명|의미|설명|
|---|---|---|
|tm_fc|기준시간1||
|data0|자료 종류||
|data1|변수 종류||
|tm_ef|기준시간2||
|dtm|시간이동단위 및 이동값||
|map|지도 종류||
|mask|이미지 내륙구분||
|color|이미지 색상표||
|size|이미지 크기||
|effect|이미지 효과||
|overlay|이미지 중첩||
|auto_man|자동(a), 수동(m)||
|mode|표출양식||
|rand|난수: 이미지 재생성 시간간격(분)||
|authKey|인증키|발급된 API 인증키|

### 7. 동네예보 격자데이터 위경도 조회

#### 7.1 동네예보 격자데이터 위경도 조회

[https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-dfs_latlon_api?fct=SHRT&latlon=lon&disp=A&authKey=YOUR_KMA_API_KEY](https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-dfs_latlon_api?fct=SHRT&latlon=lon&disp=A&authKey=YOUR_KMA_API_KEY)

##### 요청인자

  
|인자명|의미|설명|
|---|---|---|
|fct|예보종류|SHRT(단기예보), VSRT(초단기예보, 실황)|
|latlon|위도경도 선택|lon(경도), lat(위도)  <br>※ lon 입력시 좌하단에서 우상단으로 이동하며 격자별 위도값 표출  <br>lat 입력시 좌하단에서 우상단으로 이동하며 격자별 경도값 표출|
|disp|표출방식|A(ASCII) - 격자점수 + 자료 출력  <br>B(BINARY) - 격자갯수((short)nx * (short)ny)가 정수로 조회(4byte) + 자료가 실수로 조회  <br>자료 순서는 격자자료가 저장된 순서되로 출력됨|
|authKey|인증키|발급된 API 인증키|

##### 출력결과

   
|변수명|의미(단위)|변수명|의미(단위)|
|---|---|---|---|
|lat|좌하단에서 우상단으로 이동하며 격자별 위도값 표출|lon|좌하단에서 우상단으로 이동하며 격자별 경도값 표출|

#### 7.2 동네예보 격자데이터 위경도 파일(NetCDF) 다운로드

[https://apihub.kma.go.kr/api/typ01/url/dfs_latlon_file_down.php?fct=SHRT&authKey=YOUR_KMA_API_KEY](https://apihub.kma.go.kr/api/typ01/url/dfs_latlon_file_down.php?fct=SHRT&authKey=YOUR_KMA_API_KEY)

##### 요청인자

  
|인자명|의미|설명|
|---|---|---|
|fct|예보종류|SHRT(단기예보) VSRT(초단기예보. 실황)|

Copyright(c) KMA. All Rights Reserved. 연락처 : kmadatahub@korea.kr [**개인정보 처리방침**](https://apihub.kma.go.kr/personalInfo.do)

[![공공누리 공공저작물 자유이용허 - 출처표시](https://apihub.kma.go.kr/static/images/awp/mark_copy.png)](http://www.kogl.or.kr/info/license.do)