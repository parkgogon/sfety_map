"""Streamlit Cloud용 고정 진입점.

배포 설정은 ``app.py``를 계속 가리키게 두고, 실제 대시보드는
``app_v3.py``에서 관리한다. ``runpy``를 사용해 Streamlit이 스크립트를
재실행할 때마다 대시보드 본문도 새로 실행되도록 한다.
"""

from pathlib import Path
import runpy


CURRENT_APP = Path(__file__).with_name("app_v3.py")
runpy.run_path(str(CURRENT_APP), run_name="__main__")
