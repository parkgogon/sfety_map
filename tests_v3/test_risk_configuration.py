import unittest
from pathlib import Path

from safety_dashboard.application.risk_configuration import (
    editable_matrix,
    is_session_policy,
    session_policy,
)
from safety_dashboard.domain import RiskGrade, WarningLevel
from safety_dashboard.domain.risk_policy import RiskPolicy, RiskPolicyError


ROOT = Path(__file__).parents[1]
BASE = RiskPolicy.load(ROOT / "safety_dashboard/config/risk_policy.toml")


class SessionRiskConfigurationTests(unittest.TestCase):
    def test_session_policy_changes_grade_without_mutating_base(self):
        values = editable_matrix(BASE)
        values["폭염"][WarningLevel.WARNING.value] = RiskGrade.HIGH.value
        temporary = session_policy(BASE, values)

        self.assertEqual(
            temporary.warning_matrix["폭염"][WarningLevel.WARNING],
            RiskGrade.HIGH,
        )
        self.assertEqual(
            BASE.warning_matrix["폭염"][WarningLevel.WARNING],
            RiskGrade.MEDIUM,
        )
        self.assertTrue(is_session_policy(temporary))
        self.assertTrue(temporary.version.startswith(f"{BASE.version}-session-"))

    def test_same_matrix_has_stable_version_and_change_has_new_version(self):
        first_values = editable_matrix(BASE)
        second_values = editable_matrix(BASE)
        first = session_policy(BASE, first_values)
        second = session_policy(BASE, second_values)
        self.assertEqual(first.version, second.version)

        second_values["호우"][WarningLevel.ADVISORY.value] = RiskGrade.LOW.value
        changed = session_policy(BASE, second_values)
        self.assertNotEqual(first.version, changed.version)

    def test_unknown_active_warning_can_be_added_as_unassessed(self):
        values = editable_matrix(BASE, ("새로운특보",))
        self.assertEqual(
            values["새로운특보"][WarningLevel.WARNING.value],
            RiskGrade.UNASSESSED.value,
        )
        temporary = session_policy(BASE, values)
        self.assertIn("새로운특보", temporary.warning_matrix)

    def test_missing_level_is_rejected(self):
        values = editable_matrix(BASE)
        del values["호우"][WarningLevel.WARNING.value]
        with self.assertRaises(RiskPolicyError):
            session_policy(BASE, values)


if __name__ == "__main__":
    unittest.main()
