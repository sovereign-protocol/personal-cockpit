import tempfile
import unittest
from pathlib import Path

import app_server
from personal_cockpit.logic import BoardOfBoardsLogic
try:
    from s_kanban.facade import KanbanFacade
    from s_kanban.logic import KanbanLogic
except ImportError:  # pragma: no cover - depends on what is installed
    KanbanFacade = KanbanLogic = None
from sovereign.protocol import ProtocolNode


# A5: Personal Cockpit may depend on another application only optionally.
# Its own suite must therefore run with S-Kanban absent, which is also the
# only way CI can install it before S-Kanban exists on an index.
requires_kanban = unittest.skipIf(
    KanbanLogic is None, "S-Kanban is not installed",
)


class _FacadeLookup:
    def __init__(self, kanban):
        self.kanban = kanban

    def find(self, application_id, facade_api_version):
        if application_id == "kanban" and facade_api_version == 1:
            return self.kanban
        return None


def cockpit(runtime):
    return BoardOfBoardsLogic(
        runtime.session,
        runtime.config,
        facades=_FacadeLookup(KanbanFacade(runtime.logic)),
    )


class CockpitWithoutKanbanTests(unittest.TestCase):
    """Runs whether or not S-Kanban is installed - that is the point."""

    def test_without_kanban_facade_is_empty_and_reports_source_unavailable(self):
        directory = tempfile.TemporaryDirectory()
        config = app_server.load_config()
        config.update({
            "applications": [{"module": "personal_cockpit.application"}],
            "primary_application_id": "personal-cockpit",
            "storage_file": str(Path(directory.name) / "cockpit-only.json"),
        })
        runtime = app_server.create_runtime(8499, config)
        runtime._test_tmp = directory
        bob = runtime.logic

        payload = bob.summary_payload()

        self.assertEqual(payload["boards"], [])
        self.assertFalse(payload["sources"]["kanban"]["available"])
        self.assertIn("not active", payload["sources"]["kanban"]["reason"])
        result = bob.reorder_boards([])
        self.assertEqual(result.status, "error")

@requires_kanban
class BoardOfBoardsLogicTests(unittest.TestCase):
    def test_application_host_supplies_live_kanban_facade(self):
        directory = tempfile.TemporaryDirectory()
        config = app_server.load_config(None, "boardofboards")
        config["storage_file"] = str(Path(directory.name) / "cockpit.json")
        runtime = app_server.create_runtime(8498, config)
        runtime._test_tmp = directory
        kanban = runtime.host.instances["kanban"].logic
        kanban.ensure_board()

        self.assertEqual(runtime.host.primary_instance.manifest.application_id,
                         "personal-cockpit")
        self.assertEqual(len(runtime.logic.summary_payload()["boards"]), 1)
        self.assertTrue(
            runtime.logic.summary_payload()["sources"]["kanban"]["available"],
        )

    def test_summary_lists_all_boards_collapsed_by_default(self):
        runtime = self.runtime(8501)
        kanban: KanbanLogic = runtime.logic
        bob = cockpit(runtime)

        board_a = kanban.ensure_board()
        board_b_uuid = kanban.create_board("Board B").value

        payload = bob.summary_payload()
        self.assertEqual({item["uuid"] for item in payload["boards"]}, {board_a.uuid, board_b_uuid})
        self.assertTrue(all(not item["expanded"] for item in payload["boards"]))

        bob.pick_board(board_a.uuid, [], [])
        payload = bob.summary_payload()
        expanded = [item for item in payload["boards"] if item["expanded"]]
        self.assertEqual([b["uuid"] for b in expanded], [board_a.uuid])

    def test_summary_carries_columns_and_settings_for_each_board(self):
        runtime = self.runtime(8511)
        kanban: KanbanLogic = runtime.logic
        bob = cockpit(runtime)
        board = kanban.ensure_board()
        todo, doing, done = kanban.columns(board)

        collapsed = next(
            item for item in bob.summary_payload()["boards"] if item["uuid"] == board.uuid
        )
        self.assertFalse(collapsed["expanded"])
        self.assertEqual(
            {c["uuid"] for c in collapsed["columns"]},
            {todo.uuid, doing.uuid, done.uuid},
        )
        self.assertEqual(collapsed["active_column_uuids"], [])

        bob.pick_board(board.uuid, [doing.uuid], [todo.uuid])

        picked = next(
            item for item in bob.summary_payload()["boards"] if item["uuid"] == board.uuid
        )
        self.assertTrue(picked["expanded"])
        self.assertEqual(picked["active_column_uuids"], [doing.uuid])
        self.assertEqual(picked["next_column_uuids"], [todo.uuid])

    def test_active_and_next_bands_partition_by_mapped_columns(self):
        runtime = self.runtime(8502)
        kanban: KanbanLogic = runtime.logic
        bob = cockpit(runtime)
        board = kanban.ensure_board()
        todo, doing, done = kanban.columns(board)
        my_id = kanban.user_profile().uuid

        next_card = kanban.create_card(todo.uuid, "Next task", "", [my_id]).value
        active_card = kanban.create_card(doing.uuid, "Active task", "", [my_id]).value
        kanban.create_card(done.uuid, "Done task", "", [my_id])

        bob.pick_board(board.uuid, [doing.uuid], [todo.uuid])

        summary = bob.summary_payload()["boards"][0]
        self.assertEqual([c["uuid"] for c in summary["active_cards"]], [active_card.uuid])
        self.assertEqual([c["uuid"] for c in summary["next_cards"]], [next_card.uuid])

    def test_cards_without_owner_or_participant_are_excluded(self):
        runtime = self.runtime(8513)
        kanban: KanbanLogic = runtime.logic
        bob = cockpit(runtime)
        board = kanban.ensure_board()
        todo, doing, done = kanban.columns(board)
        my_id = kanban.user_profile().uuid

        mine = kanban.create_card(doing.uuid, "Mine", "", [my_id]).value
        kanban.create_card(doing.uuid, "Someone else's", "", ["other-user-id"])
        kanban.create_card(doing.uuid, "Unassigned")
        bob.pick_board(board.uuid, [doing.uuid], [])

        summary = bob.summary_payload()["boards"][0]

        self.assertEqual([c["uuid"] for c in summary["active_cards"]], [mine.uuid])

    def test_owner_cards_sort_before_participant_cards(self):
        runtime = self.runtime(8514)
        kanban: KanbanLogic = runtime.logic
        bob = cockpit(runtime)
        board = kanban.ensure_board()
        todo, doing, done = kanban.columns(board)
        my_id = kanban.user_profile().uuid

        # Created in participant-then-owner order, so a correct sort proves
        # it's reordering rather than accidentally preserving creation order.
        participant_card = kanban.create_card(doing.uuid, "I'm just on it", "", [my_id]).value
        owner_card = kanban.create_card(doing.uuid, "I own this", "", [my_id], owner=my_id).value
        bob.pick_board(board.uuid, [doing.uuid], [])

        summary = bob.summary_payload()["boards"][0]

        self.assertEqual(
            [(c["uuid"], c["relevance"]) for c in summary["active_cards"]],
            [(owner_card.uuid, "owner"), (participant_card.uuid, "participant")],
        )

    def test_card_summary_includes_people_labels(self):
        runtime = self.runtime(8524)
        kanban: KanbanLogic = runtime.logic
        bob = cockpit(runtime)
        kanban.session.set_identity("Andrea")
        board = kanban.ensure_board()
        todo, doing, done = kanban.columns(board)
        my_id = kanban.user_profile().uuid
        kanban.create_card(doing.uuid, "Discuss API", "Choose connector shape", [my_id], owner=my_id)
        bob.pick_board(board.uuid, [doing.uuid], [])

        card = bob.summary_payload()["boards"][0]["active_cards"][0]

        self.assertEqual(card["description"], "Choose connector shape")
        self.assertEqual(card["owner_label"], "Andrea")
        self.assertEqual(card["participant_labels"], ["Andrea"])
        self.assertEqual(card["owner_person"]["name"], "Andrea")
        self.assertEqual(card["participant_people"][0]["name"], "Andrea")
        self.assertNotIn("involved_labels", card)
        self.assertNotIn("involved_people", card)

    def test_summary_payload_lists_known_people_for_the_card_picker(self):
        runtime = self.runtime(8527)
        kanban: KanbanLogic = runtime.logic
        bob = cockpit(runtime)
        kanban.session.set_identity("Andrea")
        my_id = kanban.user_profile().uuid

        payload = bob.summary_payload()

        self.assertIn("people", payload)
        self.assertEqual([p["id"] for p in payload["people"]], [my_id])
        self.assertEqual(payload["people"][0]["name"], "Andrea")

    def test_summary_counts_cards_in_discussion(self):
        runtime = self.runtime(8525)
        kanban: KanbanLogic = runtime.logic
        bob = cockpit(runtime)
        board = kanban.ensure_board()
        todo, doing, done = kanban.columns(board)
        my_id = kanban.user_profile().uuid
        card = kanban.create_card(doing.uuid, "Discuss me", "", [my_id], owner=my_id).value
        bob.pick_board(board.uuid, [doing.uuid], [])
        runtime.session.add_peer("http://peer", board.uuid)
        runtime.session.apply_peer_subtree(
            "http://peer",
            ProtocolNode.from_dict(runtime.session.protocol.index[board.uuid].to_dict()),
            runtime.session.protocol.root.uuid,
        )

        kanban.update_card(card.uuid, "Discuss me locally", "", [my_id], owner=my_id)
        runtime.session.record_peer_observations(
            "http://peer",
            runtime.session.node_revision_map(runtime.session.protocol.index[board.uuid]),
        )

        summary = bob.summary_payload()["boards"][0]
        self.assertEqual(summary["discussion_count"], 1)
        self.assertEqual(summary["column_count"], 3)
        transition = summary["active_cards"][0]["transition"]
        self.assertEqual(transition["type"], "divergence")
        self.assertEqual(transition["peer_addr"], "http://peer")
        perspectives = summary["active_cards"][0]["perspectives"]
        self.assertEqual(len(perspectives), 1)
        self.assertEqual(perspectives[0]["peer_addr"], "http://peer")
        self.assertFalse(perspectives[0]["absent"])
        self.assertEqual(perspectives[0]["name"], "Discuss me")
        self.assertEqual(perspectives[0]["column_name"], "Doing")

    def test_card_perspectives_include_multiple_absent_versions_and_dedupe_forwarding(self):
        runtime = self.runtime(8528)
        kanban: KanbanLogic = runtime.logic
        bob = cockpit(runtime)
        board = kanban.ensure_board()
        card = kanban.create_card(kanban.columns(board)[0].uuid, "Task").value
        revision_a = "revision-a"

        perspectives = bob._card_perspectives(card, {"events": [
            {"type": "peer_missing_node", "peer_addr": "http://a", "peer_revision": revision_a},
            # A forwarded copy of A's same revision must not become a third user toggle.
            {"type": "peer_missing_node", "peer_addr": "http://forwarder", "peer_revision": revision_a},
            {"type": "peer_missing_node", "peer_addr": "http://b", "peer_revision": "revision-b"},
        ]})

        self.assertEqual([item["peer_addr"] for item in perspectives], ["http://a", "http://b"])
        self.assertTrue(all(item["absent"] for item in perspectives))

    def test_selected_flag_is_summary_only_and_toggles(self):
        runtime = self.runtime(8503)
        kanban: KanbanLogic = runtime.logic
        bob = cockpit(runtime)
        board = kanban.ensure_board()
        todo, doing, done = kanban.columns(board)
        my_id = kanban.user_profile().uuid
        card = kanban.create_card(doing.uuid, "Task", "", [my_id]).value
        bob.pick_board(board.uuid, [doing.uuid], [])

        before = bob.summary_payload()["boards"][0]["active_cards"][0]
        self.assertFalse(before["selected"])

        result = bob.toggle_selected(card.uuid)
        self.assertEqual(result.status, "ok")
        self.assertTrue(result.value)

        after = bob.summary_payload()["boards"][0]["active_cards"][0]
        self.assertTrue(after["selected"])
        self.assertNotIn("selected", runtime.session.protocol.index[card.uuid].data)

        toggled_off = bob.toggle_selected(card.uuid)
        self.assertFalse(toggled_off.value)

    def test_unpick_board_collapses_and_leaves_the_real_board_untouched(self):
        runtime = self.runtime(8504)
        kanban: KanbanLogic = runtime.logic
        bob = cockpit(runtime)
        board = kanban.ensure_board()
        bob.pick_board(board.uuid, [], [])

        bob.unpick_board(board.uuid)

        summary = bob.summary_payload()["boards"][0]
        self.assertEqual(summary["uuid"], board.uuid)
        self.assertFalse(summary["expanded"])
        self.assertIn(board.uuid, runtime.session.protocol.index)

    def test_reorder_boards_keeps_unmentioned_boards_appended(self):
        runtime = self.runtime(8505)
        kanban: KanbanLogic = runtime.logic
        bob = cockpit(runtime)
        board_a = kanban.ensure_board()
        board_b_uuid = kanban.create_board("Board B").value
        board_c_uuid = kanban.create_board("Board C").value
        bob.pick_board(board_a.uuid, [], [])
        bob.pick_board(board_b_uuid, [], [])
        bob.pick_board(board_c_uuid, [], [])

        bob.reorder_boards([board_c_uuid, board_a.uuid])

        payload = bob.summary_payload()
        self.assertEqual(
            [b["uuid"] for b in payload["boards"]],
            [board_c_uuid, board_a.uuid, board_b_uuid],
        )

    def test_reorder_boards_also_works_on_the_collapsed_group(self):
        # reorder_boards used to only ever touch expanded boards (and force
        # expanded=True on whatever it reordered) - collapsed board tiles
        # had no way to be reordered at all. It should now reorder whichever
        # group the given uuids belong to, and leave expanded/collapsed
        # untouched either way.
        runtime = self.runtime(8526)
        kanban: KanbanLogic = runtime.logic
        bob = cockpit(runtime)
        board_a = kanban.ensure_board()
        board_b_uuid = kanban.create_board("Board B").value
        board_c_uuid = kanban.create_board("Board C").value
        bob.pick_board(board_a.uuid, [], [])  # expanded; must stay unaffected

        bob.reorder_boards([board_c_uuid, board_b_uuid])

        payload = bob.summary_payload()
        by_uuid = {b["uuid"]: b for b in payload["boards"]}
        self.assertTrue(by_uuid[board_a.uuid]["expanded"])
        self.assertFalse(by_uuid[board_c_uuid]["expanded"])
        self.assertFalse(by_uuid[board_b_uuid]["expanded"])
        collapsed_order = [b["uuid"] for b in payload["boards"] if not b["expanded"]]
        self.assertEqual(collapsed_order, [board_c_uuid, board_b_uuid])

    def test_summary_drops_a_picked_board_that_no_longer_exists(self):
        runtime = self.runtime(8506)
        kanban: KanbanLogic = runtime.logic
        bob = cockpit(runtime)
        board_a = kanban.ensure_board()
        board_b_uuid = kanban.create_board("Board B").value
        bob.pick_board(board_a.uuid, [], [])
        bob.pick_board(board_b_uuid, [], [])

        kanban.delete_board(board_b_uuid)

        payload = bob.summary_payload()
        self.assertEqual([b["uuid"] for b in payload["boards"]], [board_a.uuid])

    def test_card_edits_via_kanban_logic_are_reflected_in_next_summary(self):
        runtime = self.runtime(8507)
        kanban: KanbanLogic = runtime.logic
        bob = cockpit(runtime)
        board = kanban.ensure_board()
        todo, doing, done = kanban.columns(board)
        my_id = kanban.user_profile().uuid
        card = kanban.create_card(todo.uuid, "Task", "", [my_id]).value
        bob.pick_board(board.uuid, [doing.uuid], [todo.uuid])

        kanban.update_card(card.uuid, "Renamed", "New desc", [my_id])
        summary = bob.summary_payload()["boards"][0]
        self.assertEqual(summary["next_cards"][0]["name"], "Renamed")

        kanban.move_card(card.uuid, doing.uuid, 0)
        summary = bob.summary_payload()["boards"][0]
        self.assertEqual(summary["next_cards"], [])
        self.assertEqual(summary["active_cards"][0]["uuid"], card.uuid)

    def test_pick_board_ignores_column_uuids_from_a_different_board(self):
        runtime = self.runtime(8508)
        kanban: KanbanLogic = runtime.logic
        bob = cockpit(runtime)
        board_a = kanban.ensure_board()
        board_b_uuid = kanban.create_board("Board B").value
        board_b = runtime.session.protocol.index[board_b_uuid]
        foreign_column = kanban.columns(board_b)[0]

        bob.pick_board(board_a.uuid, [foreign_column.uuid], [])

        summary = bob.summary_payload()["boards"][0]
        self.assertEqual(summary["active_column_uuids"], [])

    def test_pick_board_does_not_allow_same_column_as_active_and_next(self):
        runtime = self.runtime(8512)
        kanban: KanbanLogic = runtime.logic
        bob = cockpit(runtime)
        board = kanban.ensure_board()
        todo = kanban.columns(board)[0]

        bob.pick_board(board.uuid, [todo.uuid], [todo.uuid])

        summary = bob.summary_payload()["boards"][0]
        self.assertEqual(summary["active_column_uuids"], [todo.uuid])
        self.assertEqual(summary["next_column_uuids"], [])

    def test_collapse_keeps_column_mapping(self):
        runtime = self.runtime(8515)
        kanban: KanbanLogic = runtime.logic
        bob = cockpit(runtime)
        board = kanban.ensure_board()
        todo, doing, done = kanban.columns(board)
        bob.update_board_settings(
            board.uuid,
            expanded=True,
            active_column_uuid=doing.uuid,
            next_column_uuid=todo.uuid,
        )

        bob.update_board_settings(board.uuid, expanded=False)

        summary = bob.summary_payload()["boards"][0]
        self.assertFalse(summary["expanded"])
        self.assertEqual(summary["active_column_uuid"], doing.uuid)
        self.assertEqual(summary["next_column_uuid"], todo.uuid)

    def test_toggle_selected_rejects_unknown_card(self):
        runtime = self.runtime(8509)
        bob = cockpit(runtime)

        result = bob.toggle_selected("does-not-exist")

        self.assertEqual(result.status, "error")

    def test_objective_field_defaults_to_empty_and_is_settable(self):
        runtime = self.runtime(8510)
        kanban: KanbanLogic = runtime.logic
        bob = cockpit(runtime)
        board = kanban.ensure_board()
        bob.pick_board(board.uuid, [], [])

        self.assertEqual(bob.summary_payload()["boards"][0]["objective"], "")

        kanban.set_board_objective(board.uuid, "Ship the thing")
        self.assertEqual(
            bob.summary_payload()["boards"][0]["objective"],
            "Ship the thing",
        )

    def test_selected_topic_drives_cockpit_collaboration_context(self):
        runtime = self.runtime(8522)
        kanban: KanbanLogic = runtime.logic
        bob = cockpit(runtime)
        first = kanban.ensure_board()
        second_uuid = kanban.create_board("Second").value

        initial = bob.summary_payload()
        self.assertEqual(initial["selected_topic"]["uuid"], first.uuid)
        self.assertIn("auto_adopt_mode", initial)

        self.assertEqual(bob.select_topic(second_uuid).status, "ok")
        selected = bob.summary_payload()
        self.assertEqual(selected["selected_topic"]["uuid"], second_uuid)
        self.assertTrue(next(
            item for item in selected["boards"] if item["uuid"] == second_uuid
        )["selected_topic"])

    @staticmethod
    def runtime(port: int):
        directory = tempfile.TemporaryDirectory()
        config = app_server.load_config(None, "kanban")
        config["storage_file"] = str(Path(directory.name) / f"{port}.json")
        runtime = app_server.create_runtime(port, config)
        runtime._test_tmp = directory
        return runtime


if __name__ == "__main__":
    unittest.main()
