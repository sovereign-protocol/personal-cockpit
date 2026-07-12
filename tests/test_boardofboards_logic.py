import tempfile
import unittest
from pathlib import Path

import app_server
from boardofboards_logic import BoardOfBoardsLogic
from kanban_logic import KanbanLogic
from protocol import PRSPNode


class BoardOfBoardsLogicTests(unittest.TestCase):
    def test_summary_lists_all_boards_collapsed_by_default(self):
        runtime = self.runtime(8501)
        kanban: KanbanLogic = runtime.logic
        bob = BoardOfBoardsLogic(runtime.session, runtime.config)

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
        bob = BoardOfBoardsLogic(runtime.session, runtime.config)
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
        bob = BoardOfBoardsLogic(runtime.session, runtime.config)
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
        bob = BoardOfBoardsLogic(runtime.session, runtime.config)
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
        bob = BoardOfBoardsLogic(runtime.session, runtime.config)
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
        bob = BoardOfBoardsLogic(runtime.session, runtime.config)
        kanban.set_user_profile("Andrea")
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

    def test_summary_counts_cards_in_discussion(self):
        runtime = self.runtime(8525)
        kanban: KanbanLogic = runtime.logic
        bob = BoardOfBoardsLogic(runtime.session, runtime.config)
        board = kanban.ensure_board()
        todo, doing, done = kanban.columns(board)
        my_id = kanban.user_profile().uuid
        card = kanban.create_card(doing.uuid, "Discuss me", "", [my_id], owner=my_id).value
        bob.pick_board(board.uuid, [doing.uuid], [])
        runtime.session.add_peer("http://peer", board.uuid)
        runtime.session.apply_peer_subtree(
            "http://peer",
            PRSPNode.from_dict(runtime.session.protocol.index[board.uuid].to_dict()),
            runtime.session.protocol.root.uuid,
        )

        kanban.update_card(card.uuid, "Discuss me locally", "", [my_id], owner=my_id)

        summary = bob.summary_payload()["boards"][0]
        self.assertEqual(summary["discussion_count"], 1)
        self.assertEqual(summary["column_count"], 3)
        transition = summary["active_cards"][0]["transition"]
        self.assertEqual(transition["type"], "local_made_changes")
        self.assertEqual(transition["peer_addr"], "http://peer")
        self.assertEqual(summary["active_cards"][0]["perspective_state"], "none")

    def test_selected_flag_is_summary_only_and_toggles(self):
        runtime = self.runtime(8503)
        kanban: KanbanLogic = runtime.logic
        bob = BoardOfBoardsLogic(runtime.session, runtime.config)
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
        bob = BoardOfBoardsLogic(runtime.session, runtime.config)
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
        bob = BoardOfBoardsLogic(runtime.session, runtime.config)
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

    def test_summary_drops_a_picked_board_that_no_longer_exists(self):
        runtime = self.runtime(8506)
        kanban: KanbanLogic = runtime.logic
        bob = BoardOfBoardsLogic(runtime.session, runtime.config)
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
        bob = BoardOfBoardsLogic(runtime.session, runtime.config)
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
        bob = BoardOfBoardsLogic(runtime.session, runtime.config)
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
        bob = BoardOfBoardsLogic(runtime.session, runtime.config)
        board = kanban.ensure_board()
        todo = kanban.columns(board)[0]

        bob.pick_board(board.uuid, [todo.uuid], [todo.uuid])

        summary = bob.summary_payload()["boards"][0]
        self.assertEqual(summary["active_column_uuids"], [todo.uuid])
        self.assertEqual(summary["next_column_uuids"], [])

    def test_collapse_keeps_column_mapping(self):
        runtime = self.runtime(8515)
        kanban: KanbanLogic = runtime.logic
        bob = BoardOfBoardsLogic(runtime.session, runtime.config)
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
        bob = BoardOfBoardsLogic(runtime.session, runtime.config)

        result = bob.toggle_selected("does-not-exist")

        self.assertEqual(result.status, "error")

    def test_objective_field_defaults_to_empty_and_is_settable(self):
        runtime = self.runtime(8510)
        kanban: KanbanLogic = runtime.logic
        bob = BoardOfBoardsLogic(runtime.session, runtime.config)
        board = kanban.ensure_board()
        bob.pick_board(board.uuid, [], [])

        self.assertEqual(bob.summary_payload()["boards"][0]["objective"], "")

        kanban.set_board_objective(board.uuid, "Ship the thing")
        self.assertEqual(
            bob.summary_payload()["boards"][0]["objective"],
            "Ship the thing",
        )

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
