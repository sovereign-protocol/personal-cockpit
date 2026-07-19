"""Personal Cockpit manifest and host wiring."""

from sovereign.application import (
    ApplicationInstance, ApplicationManifest, ApplicationServices,
)

from .controller import build_routes
from .logic import BoardOfBoardsLogic


APPLICATION_MANIFEST = ApplicationManifest(
    application_id="personal-cockpit",
    display_name="Personal Cockpit",
    data_schema_version=1,
    asset_package="personal_cockpit.assets",
    ui_file="boardofboards.html",
    css_file="boardofboards.css",
)


def create_application(services: ApplicationServices) -> ApplicationInstance:
    logic = BoardOfBoardsLogic(
        services.session,
        dict(services.settings),
        services.channel_manager,
    )
    return ApplicationInstance(
        manifest=APPLICATION_MANIFEST,
        logic=logic,
        registration=None,
        controllers=tuple(build_routes(logic, services, dict(services.settings))),
    )
