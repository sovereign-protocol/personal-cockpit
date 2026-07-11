import tempfile
import unittest
from pathlib import Path

import app_server
from boardofboards_logic import BoardOfBoardsLogic
from kanban_logic import KanbanLogic


class BoardOfBoardsLogicTests(unittest.TestCase):
    def test_summary_lists_only_picked_boards(self):
        runtime = self.runtime(8501)
        kanban: KanbanLogic = runtime.logic
        bob = BoardOfBoardsLogic(runtime.session, runtime.config)

        board_a = kanban.ensure_board()
        board_b_uuid = kanban.create_board("Board B").value

        payload = bob.summary_payload()
        self.assertEqual(payload["boards"], [])
        self.assertEqual(
            {item["uuid"] for item in payload["available_boards"]},
            {board_a.uuid, board_b_uuid},
        )

        bob.pick_board(board_a.uuid, [], [])
        payload = bob.summary_payload()
        self.assertEqual([b["uuid"] for b in payload["boards"]], [board_a.uuid])

    def test_available_boards_carries_columns_and_binding_for_manage_ui(self):
        runtime = self.runtime(8511)
        kanban: KanbanLogic = runtime.logic
        bob = BoardOfBoardsLogic(runtime.session, runtime.config)
        board = kanban.ensure_board()
        todo, doing, done = kanban.columns(board)

        unpicked = next(
            item for item in bob.summary_payload()["available_boards"]
            if item["uuid"] == board.uuid
        )
        self.assertFalse(unpicked["picked"])
        self.assertEqual(
            {c["uuid"] for c in unpicked["columns"]},
            {todo.uuid, doing.uuid, done.uuid},
        )
        self.assertEqual(unpicked["active_column_uuids"], [])

        bob.pick_board(board.uuid, [doing.uuid], [todo.uuid])

        picked = next(
            item for item in bob.summary_payload()["available_boards"]
            if item["uuid"] == board.uuid
        )
        self.assertTrue(picked["picked"])
        self.assertEqual(picked["active_column_uuids"], [doing.uuid])
        self.assertEqual(picked["next_column_uuids"], [todo.uuid])

    def test_active_and_next_bands_partition_by_mapped_columns(self):
        runtime = self.runtime(8502)
        kanban: KanbanLogic = runtime.logic
        bob = BoardOfBoardsLogic(runtime.session, runtime.config)
        board = kanban.ensure_board()
        todo, doing, done = kanban.columns(board)

        next_card = kanban.create_card(todo.uuid, "Next task").value
        active_card = kanban.create_card(doing.uuid, "Active task").value
        kanban.create_card(done.uuid, "Done task")

        bob.pick_board(board.uuid, [doing.uuid], [todo.uuid])

        summary = bob.summary_payload()["boards"][0]
        self.assertEqual([c["uuid"] for c in summary["active_cards"]], [active_card.uuid])
        self.assertEqual([c["uuid"] for c in summary["next_cards"]], [next_card.uuid])

    def test_selected_flag_is_summary_only_and_toggles(self):
        runtime = self.runtime(8503)
        kanban: KanbanLogic = runtime.logic
        bob = BoardOfBoardsLogic(runtime.session, runtime.config)
        board = kanban.ensure_board()
        todo, doing, done = kanban.columns(board)
        card = kanban.create_card(doing.uuid, "Task").value
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

    def test_unpick_board_drops_binding_and_leaves_the_real_board_untouched(self):
        runtime = self.runtime(8504)
        kanban: KanbanLogic = runtime.logic
        bob = BoardOfBoardsLogic(runtime.session, runtime.config)
        board = kanban.ensure_board()
        bob.pick_board(board.uuid, [], [])

        bob.unpick_board(board.uuid)

        self.assertEqual(bob.summary_payload()["boards"], [])
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
        card = kanban.create_card(todo.uuid, "Task").value
        bob.pick_board(board.uuid, [doing.uuid], [todo.uuid])

        kanban.update_card(card.uuid, "Renamed", "New desc", [])
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
