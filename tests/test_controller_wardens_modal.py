"""Unit tests for the Wardens of the Cycle modal ("choose one" Morbid trigger).

Policy under test: take the right-hand plate (draw a card, lose 1 life) unless we
are below the low-life threshold, in which case take the left-hand plate (gain 2
life). Nothing here clicks anything -- __resolve_modal_at_point is stubbed out and
we assert on the point/label/policy it would have been handed.

Controller uses name-mangled double-underscore attributes; from outside the class
body they must be accessed as `_Controller__name`.
"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from Controller.MTGAController.Controller import (
    Controller,
    _WARDENS_LOW_LIFE_THRESHOLD,
    _WARDENS_OF_THE_CYCLE_GRP_ID,
)
from Controller.Utilities.GameState import GameState

WARDENS_INSTANCE_ID = 42
OTHER_GRP_ID = 12345


def make_controller() -> Controller:
    f = tempfile.NamedTemporaryFile(suffix=".log", delete=False)
    f.close()
    c = Controller(f.name)
    c._Controller__system_seat_id = 1
    return c


def seed_state(c: Controller, *, my_life=20, source_grp_id=_WARDENS_OF_THE_CYCLE_GRP_ID):
    """Minimal state: two players with life totals, and one stack object standing
    in for the Wardens trigger."""
    players = [{"systemSeatNumber": 1}, {"systemSeatNumber": 2, "lifeTotal": 20}]
    if my_life is not None:
        players[0]["lifeTotal"] = my_life
    c.updated_game_state = GameState({
        "turnInfo": {"turnNumber": 5, "phase": "Phase_Main2", "step": "Step_End"},
        "timers": [],
        "gameObjects": [{
            "instanceId": WARDENS_INSTANCE_ID,
            "grpId": source_grp_id,
            "controllerSeatId": 1,
        }],
        "players": players,
        "annotations": [],
        "actions": [],
        "zones": [],
        "gameStateId": 100,
    })


def capture_modal(c: Controller) -> list:
    """Replace the click plumbing with a recorder, so the policy can be asserted
    without moving a real mouse."""
    calls = []

    def _fake(base_point, label, reason, move_name, move_data):
        calls.append({
            "point": base_point,
            "label": label,
            "reason": reason,
            "move_name": move_name,
            "move_data": move_data,
        })

    c._Controller__resolve_modal_at_point = _fake
    return calls


def select_n_line(*, n_options=2, source_id=WARDENS_INSTANCE_ID) -> str:
    """A SelectNReq log line shaped like the modal "choose one" MTGA sends when a
    resolving ability offers prompt-parameter-index options."""
    return "[Message] " + json.dumps({
        "greToClientEvent": {
            "greToClientMessages": [{
                "type": "GREMessageType_SelectNReq",
                "systemSeatIds": [1],
                "selectNReq": {
                    "ids": list(range(1, n_options + 1)),
                    "idType": "IdType_PromptParameterIndex",
                    "context": "SelectionContext_Resolution",
                    "sourceId": source_id,
                    "minSel": 1,
                    "maxSel": 1,
                },
            }]
        }
    })


class WardensModalPolicyTest(unittest.TestCase):
    def setUp(self):
        self.c = make_controller()
        self.calls = capture_modal(self.c)

    def test_healthy_life_takes_the_right_plate_and_draws(self):
        seed_state(self.c, my_life=17)
        self.c._Controller__handle_wardens_of_the_cycle_modal(WARDENS_INSTANCE_ID)
        self.assertEqual(len(self.calls), 1)
        call = self.calls[0]
        self.assertEqual(call["label"], "MODAL_WARDENS_DRAW")
        self.assertEqual(call["move_data"]["mode"], "draw_lose_1_life")
        self.assertGreater(call["point"][0], 960, "draw plate is right of centre")

    def test_low_life_takes_the_left_plate_and_gains_life(self):
        seed_state(self.c, my_life=_WARDENS_LOW_LIFE_THRESHOLD - 1)
        self.c._Controller__handle_wardens_of_the_cycle_modal(WARDENS_INSTANCE_ID)
        call = self.calls[0]
        self.assertEqual(call["label"], "MODAL_WARDENS_GAIN_LIFE")
        self.assertEqual(call["move_data"]["mode"], "gain_2_life")
        self.assertLess(call["point"][0], 960, "gain-life plate is left of centre")

    def test_threshold_itself_still_draws(self):
        seed_state(self.c, my_life=_WARDENS_LOW_LIFE_THRESHOLD)
        self.c._Controller__handle_wardens_of_the_cycle_modal(WARDENS_INSTANCE_ID)
        self.assertEqual(self.calls[0]["move_data"]["mode"], "draw_lose_1_life")

    def test_unknown_life_falls_back_to_drawing(self):
        seed_state(self.c, my_life=None)
        self.c._Controller__handle_wardens_of_the_cycle_modal(WARDENS_INSTANCE_ID)
        self.assertEqual(self.calls[0]["move_data"]["mode"], "draw_lose_1_life")
        self.assertIsNone(self.calls[0]["move_data"]["life"])

    def test_both_plates_are_symmetric_about_the_modal_centre(self):
        seed_state(self.c, my_life=20)
        self.c._Controller__handle_wardens_of_the_cycle_modal(WARDENS_INSTANCE_ID)
        seed_state(self.c, my_life=1)
        self.c._Controller__handle_wardens_of_the_cycle_modal(WARDENS_INSTANCE_ID)
        draw, gain = self.calls[0]["point"], self.calls[1]["point"]
        self.assertEqual(draw[1], gain[1], "plates share a row")
        self.assertEqual(draw[0] - 956, 956 - gain[0], "plates straddle centre")


class WardensSourceDetectionTest(unittest.TestCase):
    def setUp(self):
        self.c = make_controller()

    def test_detects_wardens_by_grp_id(self):
        seed_state(self.c)
        self.assertTrue(
            self.c._Controller__is_wardens_of_the_cycle_source(WARDENS_INSTANCE_ID)
        )

    def test_detects_wardens_via_object_source_grp_id(self):
        """A triggered ability on the stack carries the card's grpId on
        objectSourceGrpId rather than grpId."""
        seed_state(self.c, source_grp_id=OTHER_GRP_ID)
        self.c.updated_game_state.get_game_objects()[0]["objectSourceGrpId"] = (
            _WARDENS_OF_THE_CYCLE_GRP_ID
        )
        self.assertTrue(
            self.c._Controller__is_wardens_of_the_cycle_source(WARDENS_INSTANCE_ID)
        )

    def test_other_card_is_not_wardens(self):
        seed_state(self.c, source_grp_id=OTHER_GRP_ID)
        self.assertFalse(
            self.c._Controller__is_wardens_of_the_cycle_source(WARDENS_INSTANCE_ID)
        )

    def test_unknown_source_is_not_wardens(self):
        seed_state(self.c)
        self.assertFalse(self.c._Controller__is_wardens_of_the_cycle_source(None))
        self.assertFalse(self.c._Controller__is_wardens_of_the_cycle_source(999))


class WardensDispatchTest(unittest.TestCase):
    """The SelectNReq handler must route Wardens to the horizontal two-plate
    handler and everything else to the existing bottom-of-the-stack handler."""

    def setUp(self):
        self.c = make_controller()
        self.routed = []
        self.c._Controller__handle_wardens_of_the_cycle_modal = (
            lambda source_id=None: self.routed.append(("wardens", source_id))
        )
        self.c._Controller__handle_modal_choose_last_option = (
            lambda n, source_id=None: self.routed.append(("last", n, source_id))
        )

    def test_wardens_modal_routes_to_wardens_handler(self):
        seed_state(self.c)
        self.c._Controller__handle_select_n_req(select_n_line())
        self.assertEqual(self.routed, [("wardens", WARDENS_INSTANCE_ID)])

    def test_other_card_modal_routes_to_choose_last(self):
        seed_state(self.c, source_grp_id=OTHER_GRP_ID)
        self.c._Controller__handle_select_n_req(select_n_line())
        self.assertEqual(self.routed, [("last", 2, WARDENS_INSTANCE_ID)])

    def test_three_option_modal_never_uses_the_two_plate_geometry(self):
        """The horizontal geometry was measured from a 2-option capture, so an
        unexpected option count must fall through to the generic handler."""
        seed_state(self.c)
        self.c._Controller__handle_select_n_req(select_n_line(n_options=3))
        self.assertEqual(self.routed, [("last", 3, WARDENS_INSTANCE_ID)])


if __name__ == "__main__":
    unittest.main()
