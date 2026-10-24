#!/usr/bin/env bash
set -euo pipefail

echo "=================================================="
echo "  K-ECO 스마트 안전관제 전체 무결성 검증 (verify_all)"
echo "=================================================="

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

PYTHON_BIN=".venv/bin/python"
if [ ! -f "$PYTHON_BIN" ]; then
  PYTHON_BIN="python"
fi

echo ""
echo "[1/5] 소관시설 데이터 무결성 검증..."
"$PYTHON_BIN" -m safety_dashboard.api.validate_data

echo ""
echo "[2/5] Python 단위 테스트 전체 실행 (실제 외부 통신 차단)..."
"$PYTHON_BIN" scripts/run_python_tests.py

echo ""
echo "[3/5] Python 구문 컴파일 및 바이트코드 검증..."
"$PYTHON_BIN" -m compileall -q safety_dashboard scripts tests

echo ""
echo "[4/5] React SPA 단위 테스트 (Vitest)..."
(cd field_web && npm test)

echo ""
echo "[5/5] TypeScript 타입 검사 및 프로덕션 번들 빌드..."
(cd field_web && npm run build)

echo ""
echo "=================================================="
echo "  ✅ 모든 검증 및 빌드가 성공적으로 완료되었습니다!"
echo "=================================================="
