"""The combined desktop entry, including what it does when producers are absent.

A5 makes S-Kanban and S-Agreement optional, late-bound producers. The
executable mounts whichever are installed, so the interesting case is not the
happy one - it is starting with fewer.
"""

import ast
import unittest
from pathlib import Path
from unittest.mock import patch

from personal_cockpit import desktop
from personal_cockpit.application import APPLICATION_MANIFEST


ROOT = Path(__file__).resolve().parents[1]
COCKPIT_MODULE = "personal_cockpit.application"


def _modules(applications):
    return [item["module"] for item in applications]


class InstalledApplicationTests(unittest.TestCase):
    def test_the_cockpit_is_always_mounted_and_always_last(self):
        applications = desktop.installed_applications()

        self.assertEqual(_modules(applications)[-1], COCKPIT_MODULE)

    def test_absent_producers_are_skipped_rather_than_mounted(self):
        # Mounting a module that is not installed fails at start-up, which is
        # exactly the "reduced function" A5 forbids turning into a crash.
        with patch.object(desktop.importlib.util, "find_spec", return_value=None):
            applications = desktop.installed_applications()

        self.assertEqual(_modules(applications), [COCKPIT_MODULE])

    def test_present_producers_are_mounted_before_the_cockpit(self):
        with patch.object(desktop.importlib.util, "find_spec", return_value=object()):
            applications = desktop.installed_applications()

        self.assertEqual(
            _modules(applications),
            ["s_kanban.application", "s_agreement.application", COCKPIT_MODULE],
        )


class AliasTests(unittest.TestCase):
    def test_the_cockpit_is_primary_so_it_owns_the_switching(self):
        alias = desktop.application_aliases()["cockpit"]

        self.assertEqual(
            alias["primary_application_id"], APPLICATION_MANIFEST.application_id,
        )
        self.assertEqual(alias["app_module"], COCKPIT_MODULE)
        self.assertIn(COCKPIT_MODULE, _modules(alias["applications"]))

    def test_the_alias_names_the_cockpit_assets(self):
        alias = desktop.application_aliases()["cockpit"]

        self.assertEqual(alias["ui_file"], APPLICATION_MANIFEST.ui_file)
        self.assertEqual(alias["asset_package"], APPLICATION_MANIFEST.asset_package)


class SpecTests(unittest.TestCase):
    def _collected(self):
        source = (ROOT / "Sovereign.spec").read_text(encoding="utf-8")
        collected = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.For) and isinstance(node.iter, (ast.Tuple, ast.List)):
                collected.update(
                    element.value for element in node.iter.elts
                    if isinstance(element, ast.Constant)
                    and isinstance(element.value, str)
                )
        return collected

    def test_the_spec_collects_every_application_the_entry_can_mount(self):
        # The host imports applications by name at run time, so PyInstaller
        # cannot discover them. A producer the entry point may mount but the
        # spec does not collect yields a binary that fails only once someone
        # opens that application.
        collected = self._collected()
        self.assertTrue(collected, "no collect_all package list found in the spec")

        expected = {package for package, _ in desktop.OPTIONAL_APPLICATIONS}
        expected |= {"sovereign", "personal_cockpit"}
        self.assertLessEqual(expected, collected)

    def test_the_spec_collects_the_window_backend(self):
        # pywebview loads its platform backend dynamically; without it the
        # frozen build starts and then has nothing to draw into.
        self.assertIn("webview", self._collected())


if __name__ == "__main__":
    unittest.main()
