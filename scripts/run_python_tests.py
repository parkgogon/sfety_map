"""로컬·CI 공통 진입점. 테스트 수집 전부터 실제 외부 통신을 차단한다."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.test_support import ExternalNetworkBlocked, NetworkGuard


def main():
    with NetworkGuard() as guard:
        suite = unittest.TestSuite()
        for directory in ("tests",):
            loader = unittest.TestLoader()
            suite.addTests(
                loader.discover(
                    str(ROOT / directory), pattern="test_*.py", top_level_dir=str(ROOT)
                )
            )
        result = unittest.TextTestRunner(verbosity=1).run(suite)
        try:
            # 앱이 예외를 처리해 테스트가 통과한 경우에도 실제 통신 시도는 실패로 판정한다.
            guard.assert_unused()
        except ExternalNetworkBlocked as error:
            print(str(error), file=sys.stderr)
            return 1
        print("실제 외부 HTTP·TCP 통신 시도: 0건 (가짜 제공자로 검증)")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
