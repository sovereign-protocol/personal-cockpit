"""
Board of Boards - portfolio summary view.

Functionality:
  A live channel into all of the user's own kanban boards, not a copy.
  Expanded boards are shown first with their objective, an Active
  band (cards from columns mapped as "active" for that board) and a Next
  band (cards from columns mapped as "next"). Collapsed boards follow as
  compact overview tiles. Card edits, moves, and reactions go through the
  versioned Kanban facade. This module owns its controller namespace,
  per-board display settings, column band mappings, and the summary-only
  "selected" flag (never part of the real board data).

  This is a personal overview, so each band is filtered to cards relevant
  to the local user only: cards they own come first, then cards they're a
  participant on, then nothing else - no cards with neither relation ever
  appear here (though they're untouched on the real board).

Contract:
  Local-only config/state lives in
  session.application_metadata("Board of Boards"):
    board_settings: {
      board_uuid: {expanded: bool, active_column_uuid, next_column_uuid, order}
    }
    selected_card_uuids: [card_uuid, ...]
  Persisted and restored through Session's metadata envelope.

Used API:
  The optional, versioned Kanban application facade and session.Session.
"""

from __future__ import annotations

from typing import Any, Protocol

from sovereign import ProtocolNode, Session, SessionResult


PERSONAL_COCKPIT_APPLICATION_ID = "personal-cockpit"
APP_METADATA_KEY = PERSONAL_COCKPIT_APPLICATION_ID
KANBAN_APPLICATION_ID = "kanban"
KANBAN_FACADE_API_VERSION = 1
AGREEMENT_APPLICATION_ID = "agreement"
AGREEMENT_FACADE_API_VERSION = 1


class FacadeLookup(Protocol):
    def find(self, application_id: str, facade_api_version: int) -> Any | None: ...


class BoardOfBoardsLogic:
    def __init__(self, session: Session, config: dict | None = None,
                 facades: FacadeLookup | None = None):
        self.session = session
        self.config = config or {}
        self.facades = facades
        self._kanban_facade_error = ""

    def _kanban(self):
        if self.facades is None:
            self._kanban_facade_error = "Kanban application is not active"
            return None
        try:
            facade = self.facades.find(
                KANBAN_APPLICATION_ID, KANBAN_FACADE_API_VERSION,
            )
        except ValueError as exc:
            self._kanban_facade_error = str(exc)
            return None
        self._kanban_facade_error = (
            "" if facade is not None else "Kanban application is not active"
        )
        return facade

    @property
    def kanban(self):
        facade = self._kanban()
        if facade is None:
            raise RuntimeError(self._kanban_facade_error)
        return facade

    def _agreement(self):
        # Optional, like the Kanban facade: the cockpit shows agreement tiles
        # only when the agreement application is active in this host.
        if self.facades is None:
            return None
        try:
            return self.facades.find(
                AGREEMENT_APPLICATION_ID, AGREEMENT_FACADE_API_VERSION,
            )
        except ValueError:
            return None

    def _agreement_summaries(self) -> list[dict]:
        agreement = self._agreement()
        if agreement is None:
            return []
        order = self._agreement_order()
        nodes = agreement.agreements()
        expanded_uuids = self._agreement_expanded()
        live = {node.uuid for node in nodes}
        expanded_uuids[:] = [uuid for uuid in expanded_uuids if uuid in live]
        summaries = []
        for node in nodes:
            events = agreement.transition_events(node.uuid)
            grouped = agreement.transition_by_node(events)
            unsettled = sum(
                1 for value in grouped.values()
                if value.get("type") not in (None, "in_agreement")
            )
            expanded = node.uuid in expanded_uuids
            summaries.append({
                "uuid": node.uuid,
                "title": node.data.get("title", ""),
                "application_id": AGREEMENT_APPLICATION_ID,
                "unsettled_count": unsettled,
                "agenda_count": len(self.session.agenda_items(node.uuid)),
                "expanded": expanded,
                # The whole document, but only for the tile that is showing
                # it - every summary carries this on a 1.5s poll otherwise.
                "sections": (
                    self._agreement_sections(agreement, node) if expanded else []
                ),
                "order": order.get(node.uuid, 0),
            })
        summaries.sort(key=lambda item: (item["order"], item["title"]))
        return summaries

    @staticmethod
    def _agreement_sections(facade, agreement: ProtocolNode) -> list[dict]:
        return [
            {
                "uuid": section.uuid,
                "title": section.data.get("title", ""),
                "clauses": [
                    {"uuid": clause.uuid, "text": clause.data.get("text", "")}
                    for clause in facade.clauses(section)
                ],
            }
            for section in facade.sections(agreement)
        ]

    def _agreement_order(self) -> dict:
        order = self._metadata().setdefault("agreement_order", {})
        if not isinstance(order, dict):
            order = {}
            self._metadata()["agreement_order"] = order
        return order

    def _agreement_expanded(self) -> list:
        expanded = self._metadata().setdefault("expanded_agreement_uuids", [])
        if not isinstance(expanded, list):
            expanded = []
            self._metadata()["expanded_agreement_uuids"] = expanded
        return expanded

    def set_agreement_expanded(self, agreement_uuid: str,
                               expanded: bool) -> SessionResult:
        agreement = self._agreement()
        if agreement is None:
            return SessionResult("error", reason="Agreement application is not active")
        if agreement_uuid not in {node.uuid for node in agreement.agreements()}:
            return SessionResult("error", reason="agreement not found")
        current = self._agreement_expanded()
        if expanded and agreement_uuid not in current:
            current.append(agreement_uuid)
        elif not expanded and agreement_uuid in current:
            current.remove(agreement_uuid)
        return SessionResult("ok", value=agreement_uuid)

    def reorder_agreements(self, agreement_uuids: list[str]) -> SessionResult:
        agreement = self._agreement()
        if agreement is None:
            return SessionResult("error", reason="Agreement application is not active")
        valid = {node.uuid for node in agreement.agreements()}
        order = self._agreement_order()
        for position, uuid in enumerate(
            uuid for uuid in agreement_uuids if uuid in valid
        ):
            order[uuid] = position
        return SessionResult("ok", value=agreement_uuids)

    def select_topic(self, topic_uuid: str) -> SessionResult:
        valid = {
            *(board.uuid for board in (self._kanban().boards() if self._kanban() else [])),
            *(item["uuid"] for item in self._agreement_summaries()),
        }
        if topic_uuid not in valid:
            return SessionResult("error", reason="topic not found")
        self._metadata()["selected_topic_uuid"] = topic_uuid
        return SessionResult("ok", value=topic_uuid)

    def _selected_topic(self, boards: list[dict], agreements: list[dict]) -> dict | None:
        topics = [
            *(
                {
                    "uuid": board["uuid"],
                    "title": board["name"],
                    "application_id": KANBAN_APPLICATION_ID,
                }
                for board in boards
            ),
            *(
                {
                    "uuid": agreement["uuid"],
                    "title": agreement["title"],
                    "application_id": AGREEMENT_APPLICATION_ID,
                }
                for agreement in agreements
            ),
        ]
        selected_uuid = self._metadata().get("selected_topic_uuid")
        selected = next(
            (item for item in topics if item["uuid"] == selected_uuid),
            topics[0] if topics else None,
        )
        if selected:
            self._metadata()["selected_topic_uuid"] = selected["uuid"]
        return selected

    def _collaboration_context(self, selected: dict | None) -> dict:
        if not selected:
            return {
                "agenda_items": [],
                "transition_events": [],
                "transition_by_node": {},
                "known_identities": self.session.known_identities(),
                "identity_uuid": self.session.identity.uuid,
            }
        facade = (
            self._kanban()
            if selected["application_id"] == KANBAN_APPLICATION_ID
            else self._agreement()
        )
        return facade.collaboration_context(selected["uuid"]) if facade else {}

    def summary_payload(self) -> dict:
        metadata = self._metadata()
        kanban = self._kanban()
        # Which topic-creating applications this host can offer in the
        # "+ Add new" menu - the cockpit itself creates neither, it only
        # routes to whichever facade is present.
        creatable = [{"application_id": KANBAN_APPLICATION_ID, "label": "Board"}]
        if self._agreement() is not None:
            creatable.append(
                {"application_id": AGREEMENT_APPLICATION_ID, "label": "Agreement"}
            )
        agreements = self._agreement_summaries()
        if kanban is None:
            selected = self._selected_topic([], agreements)
            return {
                "boards": [],
                "agreements": agreements,
                "creatable": creatable,
                "people": [],
                "users": [],
                "selected_topic": selected,
                **self._collaboration_context(selected),
                "sources": {
                    KANBAN_APPLICATION_ID: {
                        "available": False,
                        "reason": self._kanban_facade_error,
                    },
                },
            }
        boards = kanban.boards()
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
        selected = self._selected_topic(boards_out, agreements)
        for board in boards_out:
            board["selected_topic"] = bool(
                selected and board["uuid"] == selected["uuid"]
            )
        for agreement in agreements:
            agreement["selected_topic"] = bool(
                selected and agreement["uuid"] == selected["uuid"]
            )
        return {
            "boards": boards_out,
            "agreements": agreements,
            "creatable": creatable,
            # Every peer this session knows about, for the card-edit modal's
            # owner/members picker - not board-scoped (unlike kanban.html's
            # picker, which restricts to current board peers) since Overview
            # spans every board and has no per-board peer topic to filter by.
            "people": list(self._people_by_uuid().values()),
            "users": kanban.users(),
            "selected_topic": selected,
            **self._collaboration_context(selected),
            "sources": {KANBAN_APPLICATION_ID: {"available": True}},
        }

    def _board_summary(self, board: ProtocolNode, settings: dict) -> dict:
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
            "application_id": KANBAN_APPLICATION_ID,
            "name": board.data.get("name", ""),
            "objective": board.data.get("objective", ""),
            "expanded": bool(settings.get("expanded", False)),
            "order": int(settings.get("order", 0) or 0),
            "card_count": card_count,
            "discussion_count": discussion_count,
            "agenda_count": len(self.session.agenda_items(board.uuid)),
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
    def _relevance(card: ProtocolNode, my_id: str) -> str | None:
        if card.data.get("owner") == my_id:
            return "owner"
        if my_id in (card.data.get("participants") or []):
            return "participant"
        return None

    def _discussion_card_count(self, board: ProtocolNode) -> int:
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
        card: ProtocolNode,
        column: ProtocolNode,
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

    def _card_perspectives(self, card: ProtocolNode, transition: dict | None) -> list[dict]:
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
        kanban = self._kanban()
        if kanban is None:
            return SessionResult("error", reason=self._kanban_facade_error)
        board = self.session.protocol.index.get(board_uuid)
        if not board or board.data.get("type") != "kanban_board":
            return SessionResult("error", reason="board not found")
        valid_column_uuids = {column.uuid for column in kanban.columns(board)}
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
        kanban = self._kanban()
        if kanban is None:
            return SessionResult("error", reason=self._kanban_facade_error)
        metadata = self._metadata()
        settings = metadata.setdefault("board_settings", {})
        valid_uuids = {board.uuid for board in kanban.boards()}
        mentioned = [uuid for uuid in board_uuids if uuid in valid_uuids]
        if not mentioned:
            return SessionResult("ok", value=[])
        expanded_flag = bool(settings.get(mentioned[0], {}).get("expanded", False))
        same_group = {
            board.uuid for board in kanban.boards()
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

    def set_board_objective(
        self, board_uuid: str, objective: str,
    ) -> SessionResult:
        kanban = self._kanban()
        return (
            kanban.set_board_objective(board_uuid, objective)
            if kanban else SessionResult("error", reason=self._kanban_facade_error)
        )

    def move_card(
        self, card_uuid: str, column_uuid: str, index: int,
    ) -> SessionResult:
        kanban = self._kanban()
        return (
            kanban.move_card(card_uuid, column_uuid, index)
            if kanban else SessionResult("error", reason=self._kanban_facade_error)
        )

    def react_to_kanban_node(
        self, source_addr: str, node_uuid: str, reaction: str,
        absent: bool = False,
    ) -> SessionResult:
        kanban = self._kanban()
        if not kanban:
            return SessionResult("error", reason=self._kanban_facade_error)
        if reaction == "rollback":
            return kanban.rollback_peer_node(
                source_addr, node_uuid, absent,
            )
        return kanban.accept_peer_node(source_addr, node_uuid, absent)

    def delete_board(self, board_uuid: str) -> SessionResult:
        kanban = self._kanban()
        return (
            kanban.delete_board(board_uuid)
            if kanban else SessionResult("error", reason=self._kanban_facade_error)
        )

    def delete_card(self, card_uuid: str) -> SessionResult:
        kanban = self._kanban()
        return (
            kanban.delete_card(card_uuid)
            if kanban else SessionResult("error", reason=self._kanban_facade_error)
        )

    def update_card(
        self, card_uuid: str, name: str, description: str = "",
        participants: list[str] | None = None, owner: str | None = None,
        expected_content_hash: str | None = None,
    ) -> SessionResult:
        kanban = self._kanban()
        if not kanban:
            return SessionResult("error", reason=self._kanban_facade_error)
        return kanban.update_card(
            card_uuid, name, description, list(participants or []), owner,
            expected_content_hash,
        )

    def create_kanban_agenda_item(
        self, board_uuid: str, text: str, priority: str | None = None,
    ) -> SessionResult:
        kanban = self._kanban()
        return (
            kanban.create_agenda_item(text, priority, board_uuid)
            if kanban else SessionResult("error", reason=self._kanban_facade_error)
        )

    def delete_kanban_agenda_item(self, item_uuid: str) -> SessionResult:
        kanban = self._kanban()
        return (
            kanban.delete_agenda_item(item_uuid)
            if kanban else SessionResult("error", reason=self._kanban_facade_error)
        )

    def prioritize_kanban_agenda_item(
        self, item_uuid: str, priority: str | None,
    ) -> SessionResult:
        kanban = self._kanban()
        return (
            kanban.set_agenda_item_priority(item_uuid, priority)
            if kanban else SessionResult("error", reason=self._kanban_facade_error)
        )

    def move_kanban_agenda_item(
        self, item_uuid: str, index: int,
    ) -> SessionResult:
        kanban = self._kanban()
        return (
            kanban.move_agenda_item(item_uuid, index)
            if kanban else SessionResult("error", reason=self._kanban_facade_error)
        )

    def set_kanban_auto_adopt(
        self, board_uuid: str, mode: str,
    ) -> SessionResult:
        kanban = self._kanban()
        return (
            kanban.set_auto_adopt_mode(mode, board_uuid)
            if kanban else SessionResult("error", reason=self._kanban_facade_error)
        )

    def create_board(self, name: str) -> SessionResult:
        kanban = self._kanban()
        return (
            kanban.create_board(name)
            if kanban else SessionResult("error", reason=self._kanban_facade_error)
        )

    def copy_board(self, board_uuid: str) -> SessionResult:
        kanban = self._kanban()
        return (
            kanban.copy_board(board_uuid)
            if kanban else SessionResult("error", reason=self._kanban_facade_error)
        )

    def rename_board(self, board_uuid: str, name: str) -> SessionResult:
        kanban = self._kanban()
        return (
            kanban.rename_board(board_uuid, name)
            if kanban else SessionResult("error", reason=self._kanban_facade_error)
        )

    def create_agreement(self, title: str) -> SessionResult:
        agreement = self._agreement()
        return (
            agreement.create_agreement(title)
            if agreement else SessionResult(
                "error", reason="Agreement application is not active",
            )
        )

    def delete_agreement(self, agreement_uuid: str) -> SessionResult:
        agreement = self._agreement()
        return (
            agreement.delete_agreement(agreement_uuid)
            if agreement else SessionResult(
                "error", reason="Agreement application is not active",
            )
        )

    def create_agreement_agenda_item(
        self, agreement_uuid: str, text: str,
        priority: str | None = None,
    ) -> SessionResult:
        agreement = self._agreement()
        return (
            agreement.create_agenda_item(agreement_uuid, text, priority)
            if agreement else SessionResult(
                "error", reason="Agreement application is not active",
            )
        )

    def delete_agreement_agenda_item(self, item_uuid: str) -> SessionResult:
        agreement = self._agreement()
        return (
            agreement.delete_agenda_item(item_uuid)
            if agreement else SessionResult(
                "error", reason="Agreement application is not active",
            )
        )

    def prioritize_agreement_agenda_item(
        self, item_uuid: str, priority: str | None,
    ) -> SessionResult:
        agreement = self._agreement()
        return (
            agreement.set_agenda_item_priority(item_uuid, priority)
            if agreement else SessionResult(
                "error", reason="Agreement application is not active",
            )
        )

    def _metadata(self) -> dict:
        return self.session.application_metadata(APP_METADATA_KEY)

    def _normalized_settings(self, boards: list[ProtocolNode]) -> dict[str, dict]:
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
