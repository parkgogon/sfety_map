import json
import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FrontendDeliveryConfigTests(unittest.TestCase):
    def test_frontend_dependencies_use_exact_versions(self) -> None:
        package = json.loads(
            (PROJECT_ROOT / "field_web" / "package.json").read_text(
                encoding="utf-8"
            )
        )

        for section in ("dependencies", "devDependencies"):
            for name, version in package[section].items():
                with self.subTest(package=name):
                    self.assertRegex(version, re.compile(r"^\d+\.\d+\.\d+$"))

    def test_spa_entry_routes_disable_html_caching(self) -> None:
        config = json.loads(
            (PROJECT_ROOT / "firebase.json").read_text(encoding="utf-8")
        )
        rules = {
            rule["source"]: {
                header["key"]: header["value"]
                for header in rule["headers"]
            }
            for rule in config["hosting"]["headers"]
        }

        for source in (
            "/index.html",
            "/",
            "/control{,/**}",
            "/settings{,/**}",
        ):
            with self.subTest(source=source):
                cache_control = rules[source]["Cache-Control"]
                self.assertIn("no-cache", cache_control)
                self.assertIn("no-store", cache_control)

        self.assertIn("immutable", rules["/assets/**"]["Cache-Control"])


if __name__ == "__main__":
    unittest.main()
