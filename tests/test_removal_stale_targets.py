"""Regression tests for removal aimed at creatures that are no longer on the board.

Reproduces the 2026-07-20 09:26 incident from runtime/analysis/history.log:

    Removal Mortify target=378 (profile={'kind': 'destroy'}, priority=True)
    SelectTargetsReq details: legalTargets=[343:Creature/seat1, 353:Creature/seat1]
    REMOVAL resolve: source=360 grp=94090 profile={'kind': 'destroy'} -> target=378
    target decision -- removal_target=378 opp_creatures=[] own_creatures=[343, 353]
    OPP_BATTLEFIELD_ITEM_TIMEOUT: card 378 not found within 4.0s   (x3, then a stall)

Instance 378 was an opponent creature that had last been alive 17 minutes earlier.
GameState merges gameObjects and only prunes them on an explicit
diffDeletedInstanceIds, so its stale zoneId still said "battlefield".

Controller uses name-mangled double-underscore attributes; from outside the class
body they must be accessed as `_Controller__name`.
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import AI.Utilities.RemovalLogic as RemovalLogic
from Controller.MTGAController.Controller import Controller
from Controller.Utilities.GameState import GameState

MY_SEAT = 1
OPP_SEAT = 2
BATTLEFIELD_ZONE = 28
MORTIFY_GRP_ID = 94090
DESTROY = {"kind": "destroy"}

# The ghost: an opponent creature the merged state still thinks is on zone 28.
GHOST_ID = 378
# What MTGA actually offered: two creatures of OURS.
OUR_CREATURES = [343, 353]


def creature(instance_id, seat, *, power=2, toughness=2, zone=BATTLEFIELD_ZONE):
    return {
        "instanceId": instance_id,
        "grpId": 93824,
        "zoneId": zone,
        "controllerSeatId": seat,
        "cardTypes": ["CardType_Creature"],
        "power": power,
        "toughness": toughness,
    }


def full_state(*, live_ids, game_objects):
    """A state whose battlefield zone lists `live_ids`, while `game_objects` may
    still carry stale entries pointing at the same zone."""
    return {
        "zones": [{
            "zoneId": BATTLEFIELD_ZONE,
            "type": "ZoneType_Battlefield",
            "objectInstanceIds": list(live_ids),
        }],
        "gameObjects": list(game_objects),
    }


class BattlefieldInstanceIdsTest(unittest.TestCase):
    def test_reads_membership_from_the_zone_list(self):
        state = full_state(live_ids=OUR_CREATURES, game_objects=[])
        self.assertEqual(
            RemovalLogic.battlefield_instance_ids(state), set(OUR_CREATURES)
        )

    def test_empty_battlefield_is_an_empty_set_not_none(self):
        """An empty board and an unreadable board must be distinguishable."""
        state = full_state(live_ids=[], game_objects=[])
        self.assertEqual(RemovalLogic.battlefield_instance_ids(state), set())

    def test_no_battlefield_zone_is_none(self):
        self.assertIsNone(RemovalLogic.battlefield_instance_ids({"zones": []}))
        self.assertIsNone(RemovalLogic.battlefield_instance_ids({}))

    def test_cached_zone_id_is_used_when_type_is_not_redeclared(self):
        """battlefield_zone_ids() only sees the zone once MTGA re-declares its
        type, so a diff can carry the zone with membership but no type."""
        state = {"zones": [{
            "zoneId": BATTLEFIELD_ZONE,
            "objectInstanceIds": OUR_CREATURES,
        }]}
        self.assertIsNone(RemovalLogic.battlefield_instance_ids(state))
        self.assertEqual(
            RemovalLogic.battlefield_instance_ids(state, {BATTLEFIELD_ZONE}),
            set(OUR_CREATURES),
        )


class StaleRemovalTargetTest(unittest.TestCase):
    def setUp(self):
        # The exact shape of the incident: the ghost still claims zone 28, but the
        # zone itself only lists our two creatures.
        self.game_objects = [
            creature(GHOST_ID, OPP_SEAT, power=3, toughness=3),
            creature(OUR_CREATURES[0], MY_SEAT, power=1, toughness=1),
            creature(OUR_CREATURES[1], MY_SEAT, power=1, toughness=1),
        ]
        self.state = full_state(live_ids=OUR_CREATURES, game_objects=self.game_objects)
        self.live = RemovalLogic.battlefield_instance_ids(self.state)

    def test_zone_id_filter_alone_still_sees_the_ghost(self):
        """Documents why the extra filter is needed -- not an endorsement."""
        stale = RemovalLogic.opponent_creatures(
            self.game_objects, MY_SEAT, {BATTLEFIELD_ZONE}
        )
        self.assertEqual([c["instanceId"] for c in stale], [GHOST_ID])

    def test_live_membership_filter_drops_the_ghost(self):
        live = RemovalLogic.opponent_creatures(
            self.game_objects, MY_SEAT, {BATTLEFIELD_ZONE}, self.live
        )
        self.assertEqual(live, [])

    def test_removal_finds_no_target_so_the_cast_is_skipped(self):
        """This is the fix the user asked for: with no enemy creature on the board,
        choose_removal_target returns None and DummyAI's existing gate skips the
        cast entirely rather than casting Mortify into our own board."""
        target = RemovalLogic.choose_removal_target(
            DESTROY,
            self.game_objects,
            MY_SEAT,
            battlefield_zone_ids={BATTLEFIELD_ZONE},
            live_instance_ids=self.live,
        )
        self.assertIsNone(target)

    def test_a_real_enemy_creature_is_still_targeted(self):
        """The filter must not blind the bot to creatures that ARE there."""
        alive_enemy = 401
        objs = self.game_objects + [creature(alive_enemy, OPP_SEAT, power=4, toughness=4)]
        state = full_state(
            live_ids=OUR_CREATURES + [alive_enemy], game_objects=objs
        )
        target = RemovalLogic.choose_removal_target(
            DESTROY,
            objs,
            MY_SEAT,
            battlefield_zone_ids={BATTLEFIELD_ZONE},
            live_instance_ids=RemovalLogic.battlefield_instance_ids(state),
        )
        self.assertEqual(target, alive_enemy)

    def test_unknown_membership_falls_back_to_the_zone_filter(self):
        """live_instance_ids=None means "no data", which must not wipe out every
        target -- the old zoneId behaviour still applies."""
        target = RemovalLogic.choose_removal_target(
            DESTROY,
            self.game_objects,
            MY_SEAT,
            battlefield_zone_ids={BATTLEFIELD_ZONE},
            live_instance_ids=None,
        )
        self.assertEqual(target, GHOST_ID)


def make_controller() -> Controller:
    f = tempfile.NamedTemporaryFile(suffix=".log", delete=False)
    f.close()
    c = Controller(f.name)
    c._Controller__system_seat_id = MY_SEAT
    return c


class TargetSelectionSafetyNetTest(unittest.TestCase):
    """Even if a stale target reaches the prompt handler, it must neither be
    hunted on screen nor redirected onto our own creatures."""

    def setUp(self):
        self.c = make_controller()
        mortify = {
            "instanceId": 360,
            "grpId": MORTIFY_GRP_ID,
            "zoneId": 27,
            "controllerSeatId": MY_SEAT,
            "cardTypes": ["CardType_Instant"],
        }
        objs = [
            mortify,
            creature(OUR_CREATURES[0], MY_SEAT, power=1, toughness=1),
            creature(OUR_CREATURES[1], MY_SEAT, power=1, toughness=1),
        ]
        self.c.updated_game_state = GameState({
            "turnInfo": {"turnNumber": 6, "phase": "Phase_Main2", "step": "Step_EndCombat"},
            "timers": [], "annotations": [], "actions": [], "players": [],
            "gameObjects": objs,
            "zones": [{
                "zoneId": BATTLEFIELD_ZONE,
                "type": "ZoneType_Battlefield",
                "objectInstanceIds": list(OUR_CREATURES),
            }],
            "gameStateId": 128,
        })
        self.scheduled = []
        self.c._Controller__schedule_creature_target_selection = (
            lambda source_id, target, reason, friendly=False:
                self.scheduled.append((target, friendly))
        )
        # Stub the debug bundle: it writes files and needs a real screen.
        self.c._Controller__write_target_debug_bundle = lambda reason: None

    def _run(self, removal_target):
        self.c._Controller__resolve_removal_target = lambda source_id: removal_target
        self.c._Controller__schedule_target_selection(
            360, "TEST",
            legal_creature_ids=[],
            face_legal=False,
            own_creature_ids=list(OUR_CREATURES),
        )

    def test_stale_target_is_not_hunted_on_the_opponent_board(self):
        self._run(GHOST_ID)
        self.assertNotIn(
            GHOST_ID, [t for t, _ in self.scheduled],
            "clicking a creature that is not on the board caused the 4s timeouts",
        )

    def test_harmful_spell_never_targets_our_own_creature(self):
        self._run(GHOST_ID)
        for target, friendly in self.scheduled:
            self.assertNotIn(
                target, OUR_CREATURES,
                "Mortify would have destroyed one of our own creatures",
            )
            self.assertFalse(friendly)

    def test_harmful_spell_with_no_stale_target_still_refuses_own_board(self):
        """The path that matters once the stale target is correctly dropped."""
        self._run(None)
        self.assertEqual(self.scheduled, [])

    def test_beneficial_spell_may_still_target_our_own_creature(self):
        """The own-creature branch exists for spells like Undying Malice; the new
        guard must not break them. get_removal_profile is stubbed rather than fed an
        unknown grpId, which would send the test to Scryfall over the network."""
        original = RemovalLogic.get_removal_profile
        RemovalLogic.get_removal_profile = lambda grp_id: None
        self.addCleanup(setattr, RemovalLogic, "get_removal_profile", original)
        self._run(None)
        self.assertEqual(len(self.scheduled), 1)
        target, friendly = self.scheduled[0]
        self.assertIn(target, OUR_CREATURES)
        self.assertTrue(friendly)


if __name__ == "__main__":
    unittest.main()
