"""Desktop entry point for the whole Sovereign desktop.

The window, the runtime and the shutdown are Core's. This module supplies
which applications to host and what to call the window.

Unlike S-Initiative's single-application entry, this one mounts every application
it can find and makes the Cockpit primary, so the Cockpit does the switching
between topics rather than each application carrying its own navigation. That
is what `all3_config.json` did before the repository split.

The other applications are optional (A5). Each is mounted only if it is
installed, so this still opens with reduced function when one is absent
rather than failing to start.
"""

from __future__ import annotations

import importlib.util

from sovereign import desktop_main

from .application import APPLICATION_MANIFEST


WINDOW_TITLE = "Sovereign"

# Producers the Cockpit aggregates, in the order they should mount. The
# Cockpit goes last so it is built once its sources already exist.
OPTIONAL_APPLICATIONS = (
    ("s_initiative", "s_initiative.application"),
    ("s_team", "s_team.application"),
)


def installed_applications() -> list[dict]:
    """Every optional producer present, plus the Cockpit itself."""
    modules = [
        {"module": module}
        for package, module in OPTIONAL_APPLICATIONS
        if importlib.util.find_spec(package) is not None
    ]
    modules.append({"module": "s_cockpit.application"})
    return modules


def application_aliases() -> dict:
    return {
        "cockpit": {
            "app_module": "s_cockpit.application",
            "application_id": APPLICATION_MANIFEST.application_id,
            "applications": installed_applications(),
            "primary_application_id": APPLICATION_MANIFEST.application_id,
            "asset_package": APPLICATION_MANIFEST.asset_package,
            "ui_file": APPLICATION_MANIFEST.ui_file,
            "css_file": APPLICATION_MANIFEST.css_file,
        },
    }


def main(argv: list[str] | None = None) -> int:
    return desktop_main(argv, "cockpit", WINDOW_TITLE, application_aliases())


if __name__ == "__main__":
    raise SystemExit(main())
