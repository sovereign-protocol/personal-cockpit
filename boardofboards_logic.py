"""
Board of Boards - portfolio summary view.

Functionality:
  A live channel into a hand-picked subset of the user's own kanban boards,
  not a copy: one column per picked board, showing its objective, an Active
  band (cards from columns mapped as "active" for that board) and a Next
  band (cards from columns mapped as "next"). Card field edits and column
  moves go through the existing kanban API directly (/api/kanban/cards/...)
  - this module only owns picking boards, mapping their columns to bands,
  and the summary-only "selected" flag (never part of the real board data).

Contract:
  Local-only config/state lives in
  session.app_metadata["apps"]["Board of Boards"]:
    picked_boards: [board_uuid, ...]              # display order
    board_bindings: {board_uuid: {active_column_uuids: [...], next_column_uuids: [...]}}
    selected_card_uuids: [card_uuid, ...]
  Already persisted/restored by app_server.py's existing session metadata
  save/load - no changes needed there.

Offered API:
  create_logic(session, config)
  build_routes(logic, runtime, config)

Used API:
  kanban_logic.KanbanLogic (boards/columns/cards queries only) and
  session.Session.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from kanban_logic import KanbanLogic
from protocol import PRSPNode
from session import Session, SessionResult
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route


APP_METADATA_KEY = "Board of Boards"


class BoardOfBoardsLogic:
    def __init__(self, session: Session, config: dict):
        self.session = session
        self.config = config
        self.kanban = KanbanLogic(session, config)

    def summary_payload(self) -> dict:
        metadata = self._metadata()
        picked = list(metadata.get("picked_boards", []))
        bindings = metadata.get("board_bindings", {})
        boards = self.kanban.boards()
        boards_by_uuid = {board.uuid: board for board in boards}
        boards_out = []
        for board_uuid in picked:
            board = boards_by_uuid.get(board_uuid)
            if not board:
                continue
            boards_out.append(self._board_summary(board, bindings.get(board_uuid, {})))
        return {
            "boards": boards_out,
            "available_boards": [
                {
                    "uuid": board.uuid,
                    "name": board.data.get("name", ""),
                    "picked": board.uuid in picked,
                    "columns": [
                        {"uuid": column.uuid, "name": column.data.get("name", "")}
                        for column in self.kanban.columns(board)
                    ],
                    "active_column_uuids": bindings.get(board.uuid, {}).get("active_column_uuids", []),
                    "next_column_uuids": bindings.get(board.uuid, {}).get("next_column_uuids", []),
                }
                for board in boards
            ],
        }

    def _board_summary(self, board: PRSPNode, binding: dict) -> dict:
        columns = self.kanban.columns(board)
        columns_by_uuid = {column.uuid: column for column in columns}
        active_uuids = [
            uuid for uuid in binding.get("active_column_uuids", [])
            if uuid in columns_by_uuid
        ]
        next_uuids = [
            uuid for uuid in binding.get("next_column_uuids", [])
            if uuid in columns_by_uuid
        ]
        selected = set(self._metadata().get("selected_card_uuids", []))
        active_cards = []
        for column_uuid in active_uuids:
            for card in self.kanban.cards(columns_by_uuid[column_uuid]):
                entry = self._card_summary(card, columns_by_uuid[column_uuid])
                entry["selected"] = card.uuid in selected
                active_cards.append(entry)
        next_cards = []
        for column_uuid in next_uuids:
            for card in self.kanban.cards(columns_by_uuid[column_uuid]):
                next_cards.append(self._card_summary(card, columns_by_uuid[column_uuid]))
        return {
            "uuid": board.uuid,
            "name": board.data.get("name", ""),
            "objective": board.data.get("objective", ""),
            "columns": [
                {"uuid": column.uuid, "name": column.data.get("name", "")}
                for column in columns
            ],
            "active_column_uuids": active_uuids,
            "next_column_uuids": next_uuids,
            "active_cards": active_cards,
            "next_cards": next_cards,
        }

    @staticmethod
    def _card_summary(card: PRSPNode, column: PRSPNode) -> dict:
        return {
            "uuid": card.uuid,
            "name": card.data.get("name", ""),
            "description": card.data.get("description", ""),
            "participants": list(card.data.get("participants", [])),
            "owner": card.data.get("owner"),
            "column_uuid": column.uuid,
            "column_name": column.data.get("name", ""),
        }

    def pick_board(self, board_uuid: str,
                   active_column_uuids: list[str] | None = None,
                   next_column_uuids: list[str] | None = None) -> SessionResult:
        board = self.session.protocol.index.get(board_uuid)
        if not board or board.data.get("type") != "kanban_board":
            return SessionResult("error", reason="board not found")
        valid_column_uuids = {column.uuid for column in self.kanban.columns(board)}
        metadata = self._metadata()
        picked = list(metadata.get("picked_boards", []))
        if board_uuid not in picked:
            picked.append(board_uuid)
        bindings = dict(metadata.get("board_bindings", {}))
        bindings[board_uuid] = {
            "active_column_uuids": [
                uuid for uuid in (active_column_uuids or []) if uuid in valid_column_uuids
            ],
            "next_column_uuids": [
                uuid for uuid in (next_column_uuids or []) if uuid in valid_column_uuids
            ],
        }
        metadata["picked_boards"] = picked
        metadata["board_bindings"] = bindings
        return SessionResult("ok", value=board_uuid)

    def unpick_board(self, board_uuid: str) -> SessionResult:
        metadata = self._metadata()
        metadata["picked_boards"] = [
            uuid for uuid in metadata.get("picked_boards", []) if uuid != board_uuid
        ]
        bindings = dict(metadata.get("board_bindings", {}))
        bindings.pop(board_uuid, None)
        metadata["board_bindings"] = bindings
        return SessionResult("ok", value=board_uuid)

    def reorder_boards(self, board_uuids: list[str]) -> SessionResult:
        metadata = self._metadata()
        current = metadata.get("picked_boards", [])
        current_set = set(current)
        ordered = [uuid for uuid in board_uuids if uuid in current_set]
        # Any picked board not mentioned in the new order is kept, appended
        # at the end, rather than silently dropped from the summary.
        ordered.extend(uuid for uuid in current if uuid not in ordered)
        metadata["picked_boards"] = ordered
        return SessionResult("ok", value=ordered)

    def toggle_selected(self, card_uuid: str) -> SessionResult:
        card = self.session.protocol.index.get(card_uuid)
        if not card or card.data.get("type") != "kanban_card":
            return SessionResult("error", reason="card not found")
        metadata = self._metadata()
        selected = set(metadata.get("selected_card_uuids", []))
        if card_uuid in selected:
            selected.discard(card_uuid)
            is_selected = False
        else:
            selected.add(card_uuid)
            is_selected = True
        metadata["selected_card_uuids"] = sorted(selected)
        return SessionResult("ok", value=is_selected)

    def _metadata(self) -> dict:
        apps = self.session.app_metadata.setdefault("apps", {})
        return apps.setdefault(APP_METADATA_KEY, {})


def create_logic(session: Session, config: dict) -> BoardOfBoardsLogic:
    return BoardOfBoardsLogic(session, config)


def build_routes(logic: BoardOfBoardsLogic, runtime, config: dict) -> list[Route]:
    async def serve_ui(request: Request):
        return HTMLResponse(_read_static("boardofboards.html"))

    async def serve_css(request: Request):
        return Response(_read_static("boardofboards.css"), media_type="text/css")

    async def api_summary(request: Request):
        return JSONResponse(logic.summary_payload())

    async def api_pick_board(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.pick_board(
            data["board_uuid"],
            data.get("active_column_uuids"),
            data.get("next_column_uuids"),
        ))

    async def api_unpick_board(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.unpick_board(data["board_uuid"]))

    async def api_reorder_boards(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.reorder_boards(data.get("board_uuids", [])))

    async def api_toggle_selected(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.toggle_selected(data["card_uuid"]))

    return [
        Route("/summary", serve_ui),
        Route("/summary.css", serve_css),
        Route("/api/boardofboards/summary", api_summary),
        Route("/api/boardofboards/boards/pick", api_pick_board, methods=["POST"]),
        Route("/api/boardofboards/boards/unpick", api_unpick_board, methods=["POST"]),
        Route("/api/boardofboards/boards/reorder", api_reorder_boards, methods=["POST"]),
        Route("/api/boardofboards/cards/toggle_selected", api_toggle_selected, methods=["POST"]),
    ]


def _read_static(filename: str) -> str:
    path = Path(__file__).with_name(filename)
    with path.open(encoding="utf-8") as f:
        return f.read()


async def _json_result(runtime, result: SessionResult) -> JSONResponse:
    if result.status != "ok":
        return JSONResponse({"status": "error", "reason": result.reason}, status_code=409)
    deliveries = await asyncio.to_thread(runtime.adapter.execute_effects, result.effects)
    runtime.notify_change()
    payload: dict[str, Any] = {"status": "ok"}
    if hasattr(result.value, "to_dict"):
        payload["value"] = result.value.to_dict()
    elif result.value is not None:
        payload["value"] = result.value
    errors = [item for item in deliveries if not item.ok]
    if errors:
        payload["delivery_errors"] = [
            {"effect_type": item.effect_type, "target": item.target, "reason": item.reason}
            for item in errors
        ]
    return JSONResponse(payload)
