"""
원페이지 보고서 생성기 (Report Generator)

특보 발효 시 시설물 위험도 분석 결과를 원페이지 보고서로 생성합니다.
- HTML 기반 보고서 레이아웃
- fpdf2를 이용한 PDF 변환
"""

import datetime
from typing import Dict, Optional

import pandas as pd

# =============================================
# PDF 보고서 생성 (fpdf2)
# =============================================
try:
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos
    HAS_FPDF = True
except ImportError:
    HAS_FPDF = False


def _setup_korean_font():
    """한글 폰트 TTF 파일 경로를 반환합니다.
    
    프로젝트에 포함된 NotoSansKR (TrueType/glyf) 폰트를 사용합니다.
    NotoSansCJK(.ttc)는 CFF 기반이라 fpdf2에서 글리프가 렌더링되지 않습니다.
    """
    import os

    # 프로젝트 내 폰트 (glyf 기반 TrueType — fpdf2 호환)
    project_dir = os.path.dirname(os.path.abspath(__file__))
    bundled_font = os.path.join(project_dir, "fonts", "NotoSansKR.ttf")
    if os.path.exists(bundled_font):
        return bundled_font, bundled_font  # Variable font로 Regular/Bold 모두 커버

    # 시스템 .ttf 폰트 폴백
    ttf_candidates = [
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/nanum/NanumGothic.ttf",
    ]
    for font_path in ttf_candidates:
        if os.path.exists(font_path):
            return font_path, font_path

    return None, None


def generate_pdf_report(
    warnings_df: pd.DataFrame,
    grade_groups: Dict[str, pd.DataFrame],
    weather_data_map: Optional[Dict[str, Dict]] = None,
) -> Optional[bytes]:
    """
    PDF 보고서를 생성합니다.

    Args:
        warnings_df: 발효 중인 특보 DataFrame
        grade_groups: {"상": DataFrame, "중": DataFrame, "하": DataFrame}
        weather_data_map: {시설명: {기온, 강수량, 풍속}} (선택)

    Returns:
        bytes: PDF 바이너리 데이터 (다운로드용)
    """
    if not HAS_FPDF:
        return None

    # 한글 폰트 준비
    font_regular, font_bold = _setup_korean_font()
    if not font_regular:
        return None

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)

    # 폰트 등록 (uni 파라미터 없이)
    pdf.add_font("KoFont", "", font_regular)
    pdf.add_font("KoFont", "B", font_bold)

    fn = "KoFont"

    pdf.add_page()

    # ─── 헤더 ───
    pdf.set_font(fn, "B", 14)
    pdf.set_text_color(31, 119, 180)
    pdf.cell(0, 10, "한국환경공단 기상재난 시설물 영향 분석 보고서",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.set_font(fn, "", 9)
    pdf.set_text_color(100, 100, 100)
    now_str = datetime.datetime.now().strftime("%Y년 %m월 %d일 %H시 %M분 기준")
    pdf.cell(0, 6, f"대구경북환경본부 | {now_str}",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.line(10, pdf.get_y() + 2, 200, pdf.get_y() + 2)
    pdf.ln(5)

    # ─── 1. 발효 중인 특보 요약 ───
    pdf.set_font(fn, "B", 11)
    pdf.set_fill_color(31, 119, 180)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 8, "  1. 현재 발효 중인 기상특보 현황",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    if warnings_df.empty:
        pdf.set_font(fn, "", 9)
        pdf.cell(0, 6, "현재 대구/경북 지역에 발효 중인 기상 특보가 없습니다.",
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    else:
        # 테이블 헤더
        pdf.set_font(fn, "B", 9)
        pdf.set_fill_color(240, 240, 240)
        col_widths = [50, 40, 30, 30, 40]
        headers = ["지역", "특보 종류", "등급", "위험점수", "데이터 출처"]
        for i, h in enumerate(headers):
            pdf.cell(col_widths[i], 6, h, border=1, fill=True, align="C")
        pdf.ln()

        # 테이블 데이터
        pdf.set_font(fn, "", 9)
        from risk_engine import calculate_warning_score
        for _, row in warnings_df.iterrows():
            score = calculate_warning_score(row.get("type", ""), row.get("level", ""))
            region_text = f"{row.get('region_up', '')} {row.get('region', '')}"
            data = [
                region_text[:12],
                str(row.get("type", "")),
                str(row.get("level", "")),
                f"{score:.1f}점",
                str(row.get("source", "기상청")),
            ]
            for i, d in enumerate(data):
                pdf.cell(col_widths[i], 6, d, border=1, align="C")
            pdf.ln()

    pdf.ln(3)

    # ─── 2. 시설물 위험도 등급 분류 ───
    pdf.set_font(fn, "B", 11)
    pdf.set_fill_color(31, 119, 180)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 8, "  2. 시설물 위험도 등급 분류 (우선점검 순위)",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    grade_colors = {
        "상": (220, 53, 69),
        "중": (255, 165, 0),
        "하": (255, 193, 7),
    }
    grade_labels = {
        "상": "[상] 즉시 점검 필요",
        "중": "[중] 주의 관찰 필요",
        "하": "[하] 경과 관찰",
    }

    total_affected = sum(len(df) for df in grade_groups.values())

    for grade in ["상", "중", "하"]:
        df = grade_groups.get(grade)
        if df is None or df.empty:
            continue

        # 등급 헤더
        r, g, b = grade_colors[grade]
        pdf.set_font(fn, "B", 10)
        pdf.set_fill_color(r, g, b)
        pdf.set_text_color(255, 255, 255)
        label = grade_labels.get(grade, grade)
        pdf.cell(0, 7, f"  {label} ({len(df)}개 시설)",
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
        pdf.set_text_color(0, 0, 0)

        # 시설물 테이블
        pdf.set_font(fn, "B", 8)
        pdf.set_fill_color(245, 245, 245)
        t_col_widths = [8, 45, 25, 42, 35, 35]
        t_headers = ["No.", "시설명", "시설구분", "주소", "해당 특보", "담당자"]
        for i, h in enumerate(t_headers):
            pdf.cell(t_col_widths[i], 5, h, border=1, fill=True, align="C")
        pdf.ln()

        pdf.set_font(fn, "", 8)
        for idx, (_, row) in enumerate(df.iterrows(), 1):
            warnings_text = ""
            matched = row.get("matched_warnings", [])
            if isinstance(matched, list) and matched:
                warnings_text = ", ".join(
                    f"{w['type']}{w['level']}" for w in matched[:2]
                )

            address_short = str(row.get("address", ""))
            if len(address_short) > 14:
                address_short = address_short[:14] + "..."

            name_short = str(row.get("facility_name", ""))
            if len(name_short) > 12:
                name_short = name_short[:12] + "..."

            manager_short = str(row.get("manager", "-"))
            if len(manager_short) > 10:
                manager_short = manager_short[:10] + "..."

            data = [
                str(idx),
                name_short,
                str(row.get("facility_type", "")),
                address_short,
                warnings_text,
                manager_short,
            ]
            for i, d in enumerate(data):
                pdf.cell(t_col_widths[i], 5, d, border=1, align="C")
            pdf.ln()

        pdf.ln(2)

    # ─── 3. 시설별 기상 실황 (선택적) ───
    if weather_data_map:
        pdf.set_font(fn, "B", 11)
        pdf.set_fill_color(31, 119, 180)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(0, 8, "  3. 영향권 시설 현재 기상 실황",
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(2)

        pdf.set_font(fn, "B", 8)
        pdf.set_fill_color(240, 240, 240)
        w_col_widths = [50, 30, 35, 35, 40]
        w_headers = ["시설명", "기온(C)", "강수량(mm)", "풍속(m/s)", "풍향(deg)"]
        for i, h in enumerate(w_headers):
            pdf.cell(w_col_widths[i], 5, h, border=1, fill=True, align="C")
        pdf.ln()

        pdf.set_font(fn, "", 8)
        for name, weather in weather_data_map.items():
            name_short = name[:14] + "..." if len(name) > 14 else name
            data = [
                name_short,
                str(weather.get("기온(℃)", "-")),
                str(weather.get("1시간강수량(mm)", "-")),
                str(weather.get("풍속(m/s)", "-")),
                str(weather.get("풍향(deg)", "-")),
            ]
            for i, d in enumerate(data):
                pdf.cell(w_col_widths[i], 5, d, border=1, align="C")
            pdf.ln()

    # ─── 4. 요약 통계 ───
    pdf.ln(4)
    pdf.set_font(fn, "B", 9)
    pdf.set_draw_color(31, 119, 180)
    pdf.set_fill_color(240, 248, 255)
    summary_text = (
        f"총 영향 시설: {total_affected}개  |  "
        f"상: {len(grade_groups.get('상', []))}개  |  "
        f"중: {len(grade_groups.get('중', []))}개  |  "
        f"하: {len(grade_groups.get('하', []))}개"
    )
    pdf.cell(0, 8, summary_text, border=1, fill=True, align="C",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # 푸터
    pdf.set_y(-15)
    pdf.set_font(fn, "", 8)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 10, f"- {pdf.page_no()} -", align="C")

    # PDF 바이트 반환
    return pdf.output()


# =============================================
# HTML 보고서 (인라인 미리보기용)
# =============================================
def generate_html_report(
    warnings_df: pd.DataFrame,
    grade_groups: Dict[str, pd.DataFrame],
    weather_data_map: Optional[Dict[str, Dict]] = None,
) -> str:
    """대시보드 내 미리보기용 HTML 보고서를 생성합니다."""
    now = datetime.datetime.now().strftime("%Y년 %m월 %d일 %H시 %M분")

    grade_colors = {"상": "#dc3545", "중": "#fd7e14", "하": "#ffc107"}
    grade_emojis = {"상": "🔴", "중": "🟠", "하": "🟡"}

    total_affected = sum(len(df) for df in grade_groups.values())

    html = f"""
    <div style="font-family: 'Nanum Gothic', sans-serif; max-width: 800px; margin: 0 auto;
                border: 2px solid #1f77b4; border-radius: 8px; padding: 20px; background: #fff;">

        <div style="text-align:center; border-bottom: 2px solid #1f77b4; padding-bottom: 10px; margin-bottom: 15px;">
            <h2 style="color: #1f77b4; margin:0;">기상재난 시설물 영향 분석 보고서</h2>
            <p style="color: #666; margin: 5px 0 0 0;">대구경북환경본부 | {now} 기준</p>
        </div>

        <div style="display:flex; gap:10px; margin-bottom:15px;">
            <div style="flex:1; background:#f8f9fa; border-radius:6px; padding:10px; text-align:center;">
                <div style="font-size:24px; font-weight:bold; color:#1f77b4;">{total_affected}</div>
                <div style="font-size:12px; color:#666;">영향 시설 수</div>
            </div>
            <div style="flex:1; background:#fff5f5; border-radius:6px; padding:10px; text-align:center; border:1px solid #dc3545;">
                <div style="font-size:24px; font-weight:bold; color:#dc3545;">{len(grade_groups.get('상', []))}</div>
                <div style="font-size:12px; color:#666;">상급 (즉시점검)</div>
            </div>
            <div style="flex:1; background:#fff8f0; border-radius:6px; padding:10px; text-align:center; border:1px solid #fd7e14;">
                <div style="font-size:24px; font-weight:bold; color:#fd7e14;">{len(grade_groups.get('중', []))}</div>
                <div style="font-size:12px; color:#666;">중급 (주의관찰)</div>
            </div>
            <div style="flex:1; background:#fffef5; border-radius:6px; padding:10px; text-align:center; border:1px solid #ffc107;">
                <div style="font-size:24px; font-weight:bold; color:#ffc107;">{len(grade_groups.get('하', []))}</div>
                <div style="font-size:12px; color:#666;">하급 (경과관찰)</div>
            </div>
        </div>
    """

    # 특보 현황 테이블
    html += """
        <h4 style="color:#1f77b4; border-left:4px solid #1f77b4; padding-left:8px;">
            1. 발효 중인 기상특보 현황
        </h4>
    """
    if warnings_df.empty:
        html += '<p style="color:#28a745;">현재 발효 중인 특보가 없습니다.</p>'
    else:
        html += '<table style="width:100%; border-collapse:collapse; font-size:13px; margin-bottom:15px;">'
        html += '<tr style="background:#1f77b4; color:white;">'
        for h in ["지역", "특보 종류", "등급", "출처"]:
            html += f'<th style="padding:6px; border:1px solid #ddd;">{h}</th>'
        html += "</tr>"
        for _, row in warnings_df.iterrows():
            color = "#dc3545" if row.get("level") == "경보" else "#fd7e14"
            html += "<tr>"
            html += f'<td style="padding:5px; border:1px solid #eee;">{row.get("region_up","")} {row.get("region","")}</td>'
            html += f'<td style="padding:5px; border:1px solid #eee; text-align:center;">{row.get("type","")}</td>'
            html += f'<td style="padding:5px; border:1px solid #eee; text-align:center; color:{color}; font-weight:bold;">{row.get("level","")}</td>'
            html += f'<td style="padding:5px; border:1px solid #eee; text-align:center;">{row.get("source","기상청")}</td>'
            html += "</tr>"
        html += "</table>"

    # 등급별 시설물 목록
    html += """
        <h4 style="color:#1f77b4; border-left:4px solid #1f77b4; padding-left:8px;">
            2. 시설물 위험도 등급 분류 (우선점검 순위)
        </h4>
    """

    for grade in ["상", "중", "하"]:
        df = grade_groups.get(grade)
        if df is None or df.empty:
            continue

        color = grade_colors[grade]
        emoji = grade_emojis[grade]
        html += f"""
        <div style="margin-bottom:10px;">
            <div style="background:{color}; color:white; padding:5px 10px; border-radius:4px 4px 0 0; font-weight:bold;">
                {emoji} [{grade}] {'즉시 점검 필요' if grade == '상' else '주의 관찰 필요' if grade == '중' else '경과 관찰'} ({len(df)}개 시설)
            </div>
            <table style="width:100%; border-collapse:collapse; font-size:12px;">
                <tr style="background:#f8f9fa;">
                    <th style="padding:4px; border:1px solid #ddd;">No.</th>
                    <th style="padding:4px; border:1px solid #ddd;">시설명</th>
                    <th style="padding:4px; border:1px solid #ddd;">시설구분</th>
                    <th style="padding:4px; border:1px solid #ddd;">해당 특보</th>
                    <th style="padding:4px; border:1px solid #ddd;">담당자</th>
                </tr>
        """
        for idx, (_, row) in enumerate(df.iterrows(), 1):
            matched = row.get("matched_warnings", [])
            warnings_text = ""
            if isinstance(matched, list) and matched:
                warnings_text = ", ".join(f"{w['type']}{w['level']}" for w in matched)
            html += f"""
                <tr>
                    <td style="padding:4px; border:1px solid #eee; text-align:center;">{idx}</td>
                    <td style="padding:4px; border:1px solid #eee;">{row.get('facility_name','')}</td>
                    <td style="padding:4px; border:1px solid #eee; text-align:center;">{row.get('facility_type','')}</td>
                    <td style="padding:4px; border:1px solid #eee; text-align:center; color:{color}; font-weight:bold;">{warnings_text}</td>
                    <td style="padding:4px; border:1px solid #eee;">{row.get('manager','-')}</td>
                </tr>
            """
        html += "</table></div>"

    html += "</div>"
    return html
