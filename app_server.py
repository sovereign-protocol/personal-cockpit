#!/usr/bin/env python3
"""Personal Cockpit launcher with an optional installed S-Kanban source."""

from sovereign.app_server import *  # noqa: F401,F403
from sovereign.app_server import (
    app_default_config as _core_app_default_config,
    load_config as _core_load_config,
    main as _core_main,
)


APPLICATION_ALIASES = {
    "boardofboards": {
        "app_module": "personal_cockpit.application",
        "application_id": "personal-cockpit",
        "applications": [
            {"module": "s_kanban.application"},
            {"module": "personal_cockpit.application"},
        ],
        "asset_package": "personal_cockpit.assets",
        "ui_file": "boardofboards.html",
        "css_file": "boardofboards.css",
    },
}


def app_default_config(app_name: str) -> dict:
    return _core_app_default_config(app_name, APPLICATION_ALIASES)


def load_config(config_path: str | None = None, app_name: str | None = None) -> dict:
    return _core_load_config(config_path, app_name, APPLICATION_ALIASES)


def main(argv: list[str] | None = None) -> None:
    _core_main(argv, APPLICATION_ALIASES)


if __name__ == "__main__":
    main()
