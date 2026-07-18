"""
Board of Boards - portfolio summary view.

Functionality:
  A live channel into all of the user's own kanban boards, not a copy.
  Expanded boards are shown first with their objective, an Active
  band (cards from columns mapped as "active" for that board) and a Next
  band (cards from columns mapped as "next"). Collapsed boards follow as
  compact overview tiles. Card field edits and column
  moves go through the existing kanban API directly (/api/kanban/cards/...)
  - this module only owns per-board display settings, column band mappings,
  and the summary-only "selected" flag (never part of the real board data).

  This is a personal overview, so each band is filtered to cards relevant
  to the local user only: cards they own come first, then cards they're a
  participant on, then nothing else - no cards with neither relation ever
  appear here (though they're untouched on the real board).

Contract:
  Local-only config/state lives in
  session.app_metadata["apps"]["Board of Boards"]:
    board_settings: {
      board_uuid: {expanded: bool, active_column_uuid, next_column_uuid, order}
    }
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
        boards = self.kanban.boards()
        settings_by_board = self._normalized_settings(boards)
        boards_out = [
            self._board_summary(board, settings_by_board.get(board.uuid, {}))
            for board in sorted(
                boards,
                key=lambda board: (
                    not settings_by_board.get(board.uuid, {}).get("expanded", False),
                    int(settings_by_board.get(board.uuid, {}).get("order", 0) or 0),
                    str(board.data.get("name", "")),
                    board.created_at,
                ),
            )
        ]
        relay_manager = self.config.get("_relay_manager")
        if relay_manager:
            for board in boards_out:
                board["relay_target_id"] = relay_manager.target_for_board(board["uuid"])
        return {
            "boards": boards_out,
            # Every peer this session knows about, for the card-edit modal's
            # owner/members picker - not board-scoped (unlike kanban.html's
            # picker, which restricts to current board peers) since Overview
            # spans every board and has no per-board peer topic to filter by.
            "people": list(self._people_by_uuid().values()),
            "users": self.kanban.users(),
            "relay_targets": relay_manager.list_targets() if relay_manager else [],
        }

    def _board_summary(self, board: PRSPNode, settings: dict) -> dict:
        columns = self.kanban.columns(board)
        columns_by_uuid = {column.uuid: column for column in columns}
        people_by_uuid = self._people_by_uuid()
        transition_by_node = self.kanban.transition_by_node(
            self.kanban.transition_events(board.uuid)
        )
        active_uuid = settings.get("active_column_uuid")
        next_uuid = settings.get("next_column_uuid")
        active_uuids = [active_uuid] if active_uuid in columns_by_uuid else []
        next_uuids = [next_uuid] if next_uuid in columns_by_uuid and next_uuid != active_uuid else []
        selected = set(self._metadata().get("selected_card_uuids", []))
        my_id = self.kanban.user_profile().uuid
        card_count = 0
        for column in columns:
            card_count += len(self.kanban.cards(column))
        discussion_count = self._discussion_card_count(board)
        active_cards = []
        for column_uuid in active_uuids:
            for card in self.kanban.cards(columns_by_uuid[column_uuid]):
                relevance = self._relevance(card, my_id)
                if relevance is None:
                    continue
                entry = self._card_summary(
                    card,
                    columns_by_uuid[column_uuid],
                    people_by_uuid,
                    transition_by_node,
                )
                entry["selected"] = card.uuid in selected
                entry["relevance"] = relevance
                active_cards.append(entry)
        next_cards = []
        for column_uuid in next_uuids:
            for card in self.kanban.cards(columns_by_uuid[column_uuid]):
                relevance = self._relevance(card, my_id)
                if relevance is None:
                    continue
                entry = self._card_summary(
                    card,
                    columns_by_uuid[column_uuid],
                    people_by_uuid,
                    transition_by_node,
                )
                entry["relevance"] = relevance
                next_cards.append(entry)
        # Stable sort: owner cards first, then participant cards, each
        # group keeping its existing column/order sequence.
        active_cards.sort(key=lambda entry: entry["relevance"] != "owner")
        next_cards.sort(key=lambda entry: entry["relevance"] != "owner")
        return {
            "uuid": board.uuid,
            "name": board.data.get("name", ""),
            "objective": board.data.get("objective", ""),
            "expanded": bool(settings.get("expanded", False)),
            "order": int(settings.get("order", 0) or 0),
            "card_count": card_count,
            "discussion_count": discussion_count,
            "column_count": len(columns),
            "columns": [
                {"uuid": column.uuid, "name": column.data.get("name", "")}
                for column in columns
            ],
            "active_column_uuids": active_uuids,
            "next_column_uuids": next_uuids,
            "active_column_uuid": active_uuids[0] if active_uuids else "",
            "next_column_uuid": next_uuids[0] if next_uuids else "",
            "active_cards": active_cards,
            "next_cards": next_cards,
        }

    @staticmethod
    def _relevance(card: PRSPNode, my_id: str) -> str | None:
        if card.data.get("owner") == my_id:
            return "owner"
        if my_id in (card.data.get("participants") or []):
            return "participant"
        return None

    def _discussion_card_count(self, board: PRSPNode) -> int:
        card_uuids = set()
        for event in self.kanban.transition_events(board.uuid):
            if event.get("type") in ("in_agreement", "in_transition"):
                continue
            node_uuid = event.get("node_uuid")
            if not node_uuid:
                continue
            local_node = self.session.protocol.index.get(node_uuid)
            peer_node = self.session.get_cached_peer_subtree(
                event.get("peer_addr"), node_uuid,
            )
            node = local_node or peer_node
            if node and node.data.get("type") == "kanban_card":
                card_uuids.add(node_uuid)
        return len(card_uuids)

    def _people_by_uuid(self) -> dict[str, dict]:
        people = {}
        for user in self.kanban.users():
            user_id = user.get("profile_uuid") or user.get("id")
            if not user_id:
                continue
            name = user.get("name") or ""
            if name == "?":
                name = "Me" if user_id == self.kanban.user_profile().uuid else ""
            people[user_id] = {
                "id": user_id,
                "name": name or self._short_id(user_id),
                "picture": user.get("picture") or "",
            }
        return people

    @staticmethod
    def _short_id(user_id: str | None) -> str:
        if not user_id:
            return ""
        return str(user_id)[:8]

    def _person(self, user_id: str | None, people_by_uuid: dict[str, dict]) -> dict:
        if not user_id:
            return {"id": "", "name": "", "picture": ""}
        return people_by_uuid.get(user_id, {
            "id": user_id,
            "name": self._short_id(user_id),
            "picture": "",
        })

    def _card_summary(
        self,
        card: PRSPNode,
        column: PRSPNode,
        people_by_uuid: dict[str, dict],
        transition_by_node: dict,
    ) -> dict:
        participants = list(card.data.get("participants", []))
        owner = card.data.get("owner")
        owner_person = self._person(owner, people_by_uuid)
        participant_people = [self._person(user_id, people_by_uuid) for user_id in participants]
        transition = transition_by_node.get(card.uuid)
        return {
            "uuid": card.uuid,
            "name": card.data.get("name", ""),
            "description": card.data.get("description", ""),
            "participants": participants,
            "participant_labels": [person["name"] for person in participant_people],
            "participant_people": participant_people,
            "owner": owner,
            "owner_label": owner_person["name"] if owner else "",
            "owner_person": owner_person if owner else None,
            "transition": transition,
            "perspectives": self._card_perspectives(card, transition),
            "column_uuid": column.uuid,
            "column_name": column.data.get("name", ""),
        }

    def _card_perspectives(self, card: PRSPNode, transition: dict | None) -> list[dict]:
        """Return complete peer card versions represented by active differences."""
        if not transition:
            return []
        perspectives = []
        seen = set()
        for event in transition.get("events") or [transition]:
            if not event or event.get("type") == "in_agreement":
                continue
            peer_addr = event.get("peer_addr")
            revision = event.get("peer_revision") or event.get("peer_state_hash")
            signature = revision or f"{peer_addr}:missing"
            if signature in seen:
                continue
            seen.add(signature)
            peer_card = self.session.get_cached_peer_subtree(peer_addr, card.uuid)
            absent = not peer_card or peer_card.deleted
            peer_column = None
            if peer_card and peer_card.parent_uuid:
                peer_column = self.session.get_cached_peer_subtree(
                    peer_addr, peer_card.parent_uuid,
                )
            data = peer_card.data if peer_card and not absent else {}
            perspectives.append({
                "peer_addr": peer_addr,
                "origin_identity": event.get("origin_identity"),
                "revision": revision,
                "absent": absent,
                "name": data.get("name", ""),
                "description": data.get("description", ""),
                "participants": list(data.get("participants", [])),
                "owner": data.get("owner"),
                "column_uuid": peer_card.parent_uuid if peer_card and not absent else "",
                "column_name": (
                    peer_column.data.get("name", "")
                    if peer_column and not peer_column.deleted else ""
                ),
            })
        return perspectives

    def update_board_settings(self, board_uuid: str,
                              expanded: bool | None = None,
                              active_column_uuid: str | None = None,
                              next_column_uuid: str | None = None) -> SessionResult:
        board = self.session.protocol.index.get(board_uuid)
        if not board or board.data.get("type") != "kanban_board":
            return SessionResult("error", reason="board not found")
        valid_column_uuids = {column.uuid for column in self.kanban.columns(board)}
        metadata = self._metadata()
        settings = metadata.setdefault("board_settings", {})
        current = dict(settings.get(board_uuid, {}))
        if "order" not in current:
            current["order"] = self._next_order()
        if expanded is not None:
            current["expanded"] = bool(expanded)
        if active_column_uuid is not None:
            active_uuid = active_column_uuid or ""
            current["active_column_uuid"] = active_uuid if active_uuid in valid_column_uuids else ""
        if next_column_uuid is not None:
            next_uuid = next_column_uuid or ""
            current["next_column_uuid"] = next_uuid if next_uuid in valid_column_uuids else ""
        if current.get("next_column_uuid") == current.get("active_column_uuid"):
            current["next_column_uuid"] = ""
        settings[board_uuid] = current
        return SessionResult("ok", value=board_uuid)

    def reorder_boards(self, board_uuids: list[str]) -> SessionResult:
        # Expanded and collapsed boards each have their own left/right
        # ordering in the UI, so reordering only ever touches the group
        # the moved board already belongs to - the caller always passes
        # the full uuid list for that one group, never a mix of both.
        metadata = self._metadata()
        settings = metadata.setdefault("board_settings", {})
        valid_uuids = {board.uuid for board in self.kanban.boards()}
        mentioned = [uuid for uuid in board_uuids if uuid in valid_uuids]
        if not mentioned:
            return SessionResult("ok", value=[])
        expanded_flag = bool(settings.get(mentioned[0], {}).get("expanded", False))
        same_group = {
            board.uuid for board in self.kanban.boards()
            if bool(settings.get(board.uuid, {}).get("expanded", False)) == expanded_flag
        }
        ordered = [uuid for uuid in mentioned if uuid in same_group]
        ordered.extend(uuid for uuid in sorted(same_group) if uuid not in ordered)
        for order, board_uuid in enumerate(ordered):
            item = dict(settings.get(board_uuid, {}))
            item["order"] = order
            settings[board_uuid] = item
        return SessionResult("ok", value=ordered)

    def pick_board(self, board_uuid: str,
                   active_column_uuids: list[str] | None = None,
                   next_column_uuids: list[str] | None = None) -> SessionResult:
        return self.update_board_settings(
            board_uuid,
            expanded=True,
            active_column_uuid=(active_column_uuids or [""])[0],
            next_column_uuid=(next_column_uuids or [""])[0],
        )

    def unpick_board(self, board_uuid: str) -> SessionResult:
        return self.update_board_settings(board_uuid, expanded=False)

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

    def _normalized_settings(self, boards: list[PRSPNode]) -> dict[str, dict]:
        metadata = self._metadata()
        settings = metadata.setdefault("board_settings", {})
        self._migrate_old_metadata(settings)
        valid_uuids = {board.uuid for board in boards}
        for stale_uuid in list(settings):
            if stale_uuid not in valid_uuids:
                settings.pop(stale_uuid, None)
        for board in boards:
            item = dict(settings.get(board.uuid, {}))
            item.setdefault("expanded", False)
            if "order" not in item:
                item["order"] = self._next_order()
            settings[board.uuid] = item
        return settings

    def _migrate_old_metadata(self, settings: dict) -> None:
        metadata = self._metadata()
        picked = metadata.pop("picked_boards", [])
        bindings = metadata.pop("board_bindings", {})
        for order, board_uuid in enumerate(picked):
            binding = bindings.get(board_uuid, {})
            item = dict(settings.get(board_uuid, {}))
            item["expanded"] = True
            item["order"] = order
            item["active_column_uuid"] = (binding.get("active_column_uuids") or [""])[0]
            item["next_column_uuid"] = (binding.get("next_column_uuids") or [""])[0]
            settings[board_uuid] = item

    def _next_order(self) -> int:
        settings = self._metadata().setdefault("board_settings", {})
        orders = [
            int(item.get("order", -1) or 0)
            for item in settings.values()
            if isinstance(item, dict)
        ]
        return (max(orders) + 1) if orders else 0


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
        return await _json_result(runtime, logic.reorder_boards(data.get("board_uuids", [])))

    async def api_toggle_selected(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.toggle_selected(data["card_uuid"]))

    return [
        Route("/summary", serve_ui),
        Route("/summary.css", serve_css),
        Route("/api/boardofboards/summary", api_summary),
        Route("/api/boardofboards/boards/settings", api_update_board_settings, methods=["POST"]),
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
