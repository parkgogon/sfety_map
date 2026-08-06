import unittest
from unittest.mock import MagicMock, patch

from safety_dashboard.ui.context_panel import _render_news_link
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


class NewsLinkTests(unittest.TestCase):
    @patch("safety_dashboard.ui.context_panel.st")
    def test_reference_notice_is_shown_only_inside_help_popover(self, streamlit):
        link_column = MagicMock()
        help_column = MagicMock()
        streamlit.columns.return_value = (link_column, help_column)

        _render_news_link("https://news.example/search")

        streamlit.container.assert_called_once_with(key="news-actions")
        link_column.link_button.assert_called_once_with(
            "Google 뉴스에서 최근 기사 확인",
            "https://news.example/search",
            on_click="ignore",
            width="stretch",
        )
        self.assertNotIn("help", link_column.link_button.call_args.kwargs)
        help_column.popover.assert_called_once_with(
            "?",
            help="Google 뉴스 안내",
            width="stretch",
        )
        streamlit.write.assert_called_once_with(
            "시설 관할 지역 · 적용 특보 · 최근 7일"
        )
        streamlit.caption.assert_called_once_with(
            "뉴스는 외부 참고정보이며 위험도·발송·보고서에 반영되지 않습니다."
        )


if __name__ == "__main__":
    unittest.main()
