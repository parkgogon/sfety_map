import unittest
from unittest.mock import patch

from ui.components import render_facility_metadata
from ui.theme import THEME_CSS


class ComponentTests(unittest.TestCase):
    @patch("ui.components.st.html")
    def test_facility_metadata_keeps_full_escaped_values(self, render_html):
        render_facility_metadata(
            "아주 긴 담당자 <이름>&연락처",
            "아주 긴 시설유형 이름",
        )
        markup = render_html.call_args.args[0]
        self.assertIn("아주 긴 담당자 &lt;이름&gt;&amp;연락처", markup)
        self.assertIn("아주 긴 시설유형 이름", markup)
        self.assertNotIn("…", markup)
        self.assertIn("overflow-wrap: anywhere", THEME_CSS)
        self.assertIn("white-space: normal", THEME_CSS)


if __name__ == "__main__":
    unittest.main()
