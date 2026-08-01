"""S-Cockpit manifest and host wiring."""

from sovereign import (
    ApplicationInstance, ApplicationManifest, ApplicationServices,
)

from .controller import build_routes
from .logic import BoardOfBoardsLogic


APPLICATION_MANIFEST = ApplicationManifest(
    application_id="cockpit",
    display_name="S-Cockpit",
    data_schema_version=1,
    asset_package="s_cockpit.assets",
    icon=(
        '<rect x="3" y="3" width="7" height="7" rx="1"></rect>'
        '<rect x="14" y="3" width="7" height="7" rx="1"></rect>'
        '<rect x="3" y="14" width="7" height="7" rx="1"></rect>'
        '<rect x="14" y="14" width="7" height="7" rx="1"></rect>'
    ),
    role="aggregator",
    ui_file="boardofboards.html",
    css_file="boardofboards.css",
)


def create_application(services: ApplicationServices) -> ApplicationInstance:
    logic = BoardOfBoardsLogic(
        services.session,
        dict(services.settings),
        services.facades,
    )
    return ApplicationInstance(
        manifest=APPLICATION_MANIFEST,
        logic=logic,
        registration=None,
        controllers=tuple(build_routes(logic, services)),
    )
