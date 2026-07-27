"""Starlette controller for Personal Cockpit."""

from __future__ import annotations

import asyncio

from sovereign import application_result_view, json_value
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


def build_routes(logic, runtime, config: dict) -> list[Route]:
    async def api_summary(request: Request):
        return JSONResponse(json_value(logic.summary_payload()))

    async def api_pick_board(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.pick_board(
            data["board_uuid"],
            data.get("active_column_uuids"),
            data.get("next_column_uuids"),
        ))

    async def api_update_board_settings(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.update_board_settings(
            data["board_uuid"],
            data.get("expanded") if "expanded" in data else None,
            data.get("active_column_uuid"),
            data.get("next_column_uuid"),
        ))

    async def api_unpick_board(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.unpick_board(data["board_uuid"]))

    async def api_reorder_boards(request: Request):
        data = await request.json()
        return await _json_result(
            runtime, logic.reorder_boards(data.get("board_uuids", [])),
        )

    async def api_toggle_selected(request: Request):
        data = await request.json()
        return await _json_result(
            runtime, logic.toggle_selected(data["card_uuid"]),
        )

    async def api_reorder_agreements(request: Request):
        data = await request.json()
        return await _json_result(
            runtime, logic.reorder_agreements(data.get("agreement_uuids", [])),
        )

    async def api_agreement_settings(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.set_agreement_expanded(
            data["agreement_uuid"], bool(data.get("expanded")),
        ))

    async def api_select_topic(request: Request):
        data = await request.json()
        return await _json_result(
            runtime, logic.select_topic(data["topic_uuid"]),
        )

    return [
        Route("/api/personal-cockpit/summary", api_summary),
        Route("/api/personal-cockpit/boards/settings", api_update_board_settings,
              methods=["POST"]),
        Route("/api/personal-cockpit/boards/pick", api_pick_board, methods=["POST"]),
        Route("/api/personal-cockpit/boards/unpick", api_unpick_board, methods=["POST"]),
        Route("/api/personal-cockpit/boards/reorder", api_reorder_boards, methods=["POST"]),
        Route("/api/personal-cockpit/agreements/reorder", api_reorder_agreements,
              methods=["POST"]),
        Route("/api/personal-cockpit/agreements/settings", api_agreement_settings,
              methods=["POST"]),
        Route("/api/personal-cockpit/topics/select", api_select_topic,
              methods=["POST"]),
        Route("/api/personal-cockpit/cards/toggle_selected", api_toggle_selected,
              methods=["POST"]),
    ]


async def _json_result(runtime, result) -> JSONResponse:
    deliveries = []
    if result.status == "ok":
        deliveries = await asyncio.to_thread(
            runtime.deliver_effects, result.effects,
        )
        runtime.notify_change()
    view = application_result_view(result, deliveries)
    return JSONResponse(view.payload, status_code=200 if view.ok else 409)
