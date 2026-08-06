import unittest
from unittest.mock import patch

from safety_dashboard.ui.workflow import render_metric_grid


class MetricGridTests(unittest.TestCase):
    @patch("safety_dashboard.ui.workflow.st.markdown")
    def test_three_metrics_share_one_responsive_grid(self, markdown):
        render_metric_grid(
            (
                ("영향 특보", 3, "시설에 연결"),
                ("영향 시설", 7, "10개 중"),
                ("상 위험", 1, "즉시 확인"),
            )
        )
        markup = markdown.call_args.args[0]
        self.assertIn('class="metric-grid"', markup)
        self.assertEqual(markup.count('class="metric-card"'), 3)
        self.assertIn("영향 특보", markup)
        markdown.assert_called_once()
        self.assertTrue(markdown.call_args.kwargs["unsafe_allow_html"])

    @patch("safety_dashboard.ui.workflow.st.markdown")
    def test_metric_text_is_html_escaped(self, markdown):
        render_metric_grid((("<위험>", "<3", "A & B"),))
        markup = markdown.call_args.args[0]
        self.assertIn("&lt;위험&gt;", markup)
        self.assertIn("&lt;3", markup)
        self.assertIn("A &amp; B", markup)
        self.assertNotIn("<위험>", markup)


if __name__ == "__main__":
    unittest.main()
