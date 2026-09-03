import { useEffect, useMemo, useState } from "react";
import { useMonitoringData } from "./api";
import {
  checkAdminSession,
  clearStoredTemporaryPolicy,
  getStoredAdminToken,
  getStoredTemporaryPolicy,
  logoutAdmin,
  setStoredAdminToken,
  setStoredTemporaryPolicy,
  useRiskPolicy,
  verifyAdminPassword,
} from "./controlApi";
import { navigateWithMode } from "./router";
import { GRADE_LABELS } from "./utils";

export const LEVEL_LABELS = {
  ADVISORY: "주의보",
  WARNING: "경보",
  CRITICAL: "중대",
};

export const GRADE_OPTIONS = ["HIGH", "MEDIUM", "LOW", "UNASSESSED", "NONE"] as const;
const POLICY_LEVELS = ["ADVISORY", "WARNING", "CRITICAL"] as const;

interface PolicyMatrixEditorProps {
  warningTypes: readonly string[];
  activeWarningTypes: ReadonlySet<string>;
  editedMatrix: Record<string, Record<string, string>>;
  defaultMatrix: Record<string, Record<string, string>>;
  onCellChange: (warningType: string, level: string, grade: string) => void;
}

export function PolicyMatrixEditor({
  warningTypes,
  activeWarningTypes,
  editedMatrix,
  defaultMatrix,
  onCellChange,
}: PolicyMatrixEditorProps) {
  return (
    <div className="policy-table-wrapper">
      <table className="policy-matrix-table">
        <thead>
          <tr>
            <th className="policy-warning-name-heading">특보 종류</th>
            <th className="policy-warning-status-heading">상태</th>
            {POLICY_LEVELS.map((level) => <th key={level}>{LEVEL_LABELS[level]}</th>)}
          </tr>
        </thead>
        <tbody>
          {warningTypes.map((warningType) => {
            const isActive = activeWarningTypes.has(warningType);
            const levels = editedMatrix[warningType] || {};
            return (
              <tr
                key={warningType}
                className={`policy-warning-row ${isActive ? "row-active-warning" : ""}`}
              >
                <td className="col-warning-name">
                  <strong>{warningType}</strong>
                </td>
                <td className="col-warning-status">
                  {isActive ? (
                    <span className="status-tag active">● 발효 중</span>
                  ) : (
                    <span className="status-tag">평시</span>
                  )}
                </td>
                {POLICY_LEVELS.map((level) => {
                  const currentGrade = levels[level] || "UNASSESSED";
                  const modified = defaultMatrix[warningType]?.[level] !== currentGrade;
                  return (
                    <td
                      key={level}
                      className={`col-grade-cell ${modified ? "cell-modified" : ""}`}
                      data-label={LEVEL_LABELS[level]}
                    >
                      <select
                        className={`policy-grade-select grade-${currentGrade.toLowerCase()}`}
                        value={currentGrade}
                        onChange={(event) => onCellChange(warningType, level, event.target.value)}
                        aria-label={`${warningType} ${LEVEL_LABELS[level]} 위험등급`}
                      >
                        {GRADE_OPTIONS.map((grade) => (
                          <option key={grade} value={grade}>
                            {GRADE_LABELS[grade]}
                          </option>
                        ))}
                      </select>
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function SettingsApp() {
  const [adminToken, setAdminToken] = useState<string>(getStoredAdminToken);
  const [passwordInput, setPasswordInput] = useState("");
  const [authError, setAuthError] = useState<string | null>(null);
  const [authLoading, setAuthLoading] = useState(false);

  // 세션 자동 확인
  useEffect(() => {
    let active = true;
    void checkAdminSession(adminToken).then((status) => {
      if (!active) return;
      if (status.authenticated && !adminToken) {
        setAdminToken("active-session");
      } else if (!status.authenticated && adminToken) {
        setAdminToken("");
        setStoredAdminToken("");
      }
    });
    return () => {
      active = false;
    };
  }, [adminToken]);

  const { data: monitoringData } = useMonitoringData("live");
  const { data: policyData, loading, error, refresh } = useRiskPolicy(adminToken);

  // 편집 중인 매트릭스 상태: { [warning_type]: { [level]: grade } }
  const [editedMatrix, setEditedMatrix] = useState<Record<string, Record<string, string>>>({});
  const [isTemporary, setIsTemporary] = useState(false);
  const [savedSuccess, setSavedSuccess] = useState(false);

  // 정책 데이터 로드 시 초기화
  useEffect(() => {
    if (!policyData) return;
    const stored = getStoredTemporaryPolicy();
    if (stored) {
      setEditedMatrix(stored);
      setIsTemporary(true);
    } else {
      setEditedMatrix(policyData.warning_types);
      setIsTemporary(false);
    }
  }, [policyData]);

  const handleLogin = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!passwordInput.trim()) return;
    setAuthLoading(true);
    setAuthError(null);
    try {
      const token = await verifyAdminPassword(passwordInput.trim());
      setAdminToken(token);
      setPasswordInput("");
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : "인증 실패");
    } finally {
      setAuthLoading(false);
    }
  };

  const handleLogout = () => {
    void logoutAdmin();
    setAdminToken("");
  };


  // 현재 발효 중인 특보 종류 집합
  const activeWarningTypes = useMemo(() => {
    if (!monitoringData) return new Set<string>();
    const types = new Set<string>();
    for (const fac of monitoringData.facilities) {
      for (const r of fac.reasons) {
        types.add(r.type);
      }
    }
    return types;
  }, [monitoringData]);

  // 특보 종류 목록 (발효 중인 특보를 상단으로 정렬)
  const sortedWarningTypes = useMemo(() => {
    if (!policyData) return [];
    const types = Object.keys(policyData.warning_types);
    return types.sort((a, b) => {
      const aActive = activeWarningTypes.has(a);
      const bActive = activeWarningTypes.has(b);
      if (aActive && !bActive) return -1;
      if (!aActive && bActive) return 1;
      return a.localeCompare(b, "ko-KR");
    });
  }, [policyData, activeWarningTypes]);

  // 셀 값 변경 핸들러
  const handleCellChange = (warningType: string, level: string, newGrade: string) => {
    setEditedMatrix((current) => ({
      ...current,
      [warningType]: {
        ...(current[warningType] || {}),
        [level]: newGrade,
      },
    }));
    setSavedSuccess(false);
  };

  // 임시 정책 저장 및 적용
  const handleSaveTemporary = () => {
    setStoredTemporaryPolicy(editedMatrix);
    setIsTemporary(true);
    setSavedSuccess(true);
    setTimeout(() => setSavedSuccess(false), 3000);
  };

  // 기본값으로 복원
  const handleResetDefault = () => {
    if (!policyData) return;
    clearStoredTemporaryPolicy();
    setEditedMatrix(policyData.warning_types);
    setIsTemporary(false);
    setSavedSuccess(false);
  };

  if (!adminToken) {
    return (
      <div className="control-shell">
        <header className="control-header settings-header">
          <div className="control-brand">
            <span className="brand-mark">K-ECO SAFETY MONITORING</span>
            <h1>위험도 정책 설정</h1>
          </div>
          <div className="control-header-actions">
            <button className="secondary-button" type="button" onClick={() => navigateWithMode("/control")}>
              <span className="btn-text-full">중앙 관제 ↗</span><span className="btn-text-short">관제 ↗</span>
            </button>
            <button className="secondary-button" type="button" onClick={() => navigateWithMode("/")}>
              <span className="btn-text-full">현장 지도 ↗</span><span className="btn-text-short">지도 ↗</span>
            </button>
          </div>
        </header>
        <div className="admin-login-wrapper">
          <div className="admin-login-card">
            <h2>관리자 인증이 필요합니다</h2>
            <p>위험도 정책 기준 조회 및 브라우저 세션 편집을 위해 비밀번호를 입력해 주세요.</p>
            <form className="login-form" onSubmit={handleLogin}>
              <input
                type="password"
                placeholder="관리자 비밀번호"
                value={passwordInput}
                onChange={(e) => setPasswordInput(e.target.value)}
                disabled={authLoading}
                aria-label="관리자 비밀번호"
              />
              <button className="primary-button" type="submit" disabled={authLoading}>
                {authLoading ? "확인 중..." : "관리자 로그인"}
              </button>
            </form>
            {authError && <div className="notice error" style={{ marginTop: "12px" }}>{authError}</div>}
          </div>
        </div>
      </div>
    );
  }

  if (loading && !policyData) {
    return (
      <main className="initial-state">
        <div className="brand-mark">K-ECO SAFETY MONITORING</div>
        <div className="loading-ring" aria-label="위험도 정책 불러오는 중" />
        <strong>위험도 정책 정보를 불러오고 있습니다</strong>
      </main>
    );
  }

  if (!policyData) {
    return (
      <main className="initial-state error-state">
        <div className="brand-mark">K-ECO SAFETY MONITORING</div>
        <strong>위험도 정책을 불러오지 못했습니다</strong>
        <span>{error || "네트워크 상태를 확인한 뒤 다시 시도해 주세요."}</span>
        <button className="primary-button" type="button" onClick={() => void refresh()}>
          다시 시도
        </button>
      </main>
    );
  }

  return (
    <div className="control-shell">
      <header className="control-header settings-header">
        <div className="control-brand">
          <span className="brand-mark">K-ECO SAFETY MONITORING</span>
          <h1>위험도 정책 설정</h1>
        </div>
        <div className="control-header-actions">
          <button className="secondary-button" type="button" onClick={() => navigateWithMode("/control")}>
            <span className="btn-text-full">중앙 관제 ↗</span><span className="btn-text-short">관제 ↗</span>
          </button>
          <button className="secondary-button" type="button" onClick={() => navigateWithMode("/")}>
            <span className="btn-text-full">현장 지도 ↗</span><span className="btn-text-short">지도 ↗</span>
          </button>
          <button className="secondary-button" type="button" onClick={handleLogout}>
            <span className="btn-text-full">로그아웃</span><span className="btn-text-short">종료</span>
          </button>
        </div>
      </header>

      <div className="settings-container">
        {/* 상태 및 설명 배너 */}
        <div className={`settings-banner ${isTemporary ? "temporary-active" : ""}`}>
          <div>
            <h2>현재 위험도 정책: <code>{policyData.version}</code></h2>
            <p>{policyData.description}</p>
            {isTemporary ? (
              <span className="temporary-badge">
                ⚠️ 현재 브라우저 세션의 임시 위험도 정책이 적용되어 있습니다.
              </span>
            ) : (
              <span className="default-badge">✓ 기본 정책 매트릭스 적용 중</span>
            )}
          </div>
          <div className="settings-banner-actions">
            <button
              type="button"
              className="secondary-button"
              onClick={handleResetDefault}
              disabled={!isTemporary}
            >
              기본값으로 복원
            </button>
            <button
              type="button"
              className="primary-button"
              onClick={handleSaveTemporary}
            >
              임시 정책 브라우저 적용
            </button>
          </div>
        </div>

        {savedSuccess && (
          <div className="notice success">
            ✓ 임시 위험도 정책이 현재 브라우저에 저장되었습니다.
          </div>
        )}

        {/* 정책 매트릭스 편집 테이블 */}
        <div className="policy-table-card">
          <div className="policy-table-header">
            <div>
              <h3>기상특보별 위험등급 판정 매트릭스</h3>
              <p>특보 종류와 단계가 교차하는 셀의 위험등급(상·중·하·미판정·없음)을 조정할 수 있습니다.</p>
            </div>
            {activeWarningTypes.size > 0 && (
              <span className="active-warning-badge">
                🔴 현재 발효 특보 {activeWarningTypes.size}종 상단 표출 중
              </span>
            )}
          </div>

          <PolicyMatrixEditor
            warningTypes={sortedWarningTypes}
            activeWarningTypes={activeWarningTypes}
            editedMatrix={editedMatrix}
            defaultMatrix={policyData.warning_types}
            onCellChange={handleCellChange}
          />
        </div>

        {/* 하단 저장 및 복원 바 */}
        <div className="settings-bottom-actions">
          <div className="settings-footer-info">
            <small>
              ※ 설정값은 현재 브라우저 세션의 관제 결과 계산에 적용되며, 관리자 화면 및 모의 전파에 반영됩니다.
            </small>
          </div>
          <div className="settings-bottom-buttons">
            <button
              type="button"
              className="secondary-button"
              onClick={handleResetDefault}
              disabled={!isTemporary}
            >
              기본값으로 복원
            </button>
            <button
              type="button"
              className="primary-button"
              onClick={handleSaveTemporary}
            >
              임시 정책 브라우저 적용
            </button>
          </div>
        </div>
      </div>
    </div>

  );
}
