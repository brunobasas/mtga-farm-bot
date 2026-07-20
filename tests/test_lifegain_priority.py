"""Tests for lifegain-payoff detection and its effect on cast ordering.

The Orzhov starter deck's engine is "gain life -> a creature grows". Ajani's
Pridemate, Twinblade Paladin and Fiendish Panda all read "Whenever you gain
life, put a +1/+1 counter on this creature", and only earn counters from lifegain
that happens while they are already on the board -- so they should be deployed
ahead of other creatures in the same mana plan.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import AI.Utilities.CardInfo as CardInfo
import AI.Utilities.LifegainLogic as LifegainLogic
from AI.DummyAI import DummyAI

AJANIS_PRIDEMATE = 93447
TWINBLADE_PALADIN = 93652
FIENDISH_PANDA = 93833
INSPIRING_OVERSEER = 93645  # gains life, but does NOT grow from it
VAMPIRE_NIGHTHAWK = 93899   # lifelink, but no payoff trigger

WHITE = {"white"}
WB = {"white", "black"}


def cast_action(
    paid_cost, instance_id, name, *, type_priority=5, cmc=None, payoff=False,
    mana_cost=None,
):
    """Build one entry of DummyAI's cast_actions tuple.

    Layout: (paid, instId, name, costStr, manaCost, convoke, typePriority,
             nominalCmc, discounted, priorityRemoval, lifegainPayoff)
    """
    if mana_cost is None:
        mana_cost = [{"color": ["ManaColor_Generic"], "count": paid_cost}]
    return (
        paid_cost, instance_id, name, f"{{{paid_cost}}}", mana_cost,
        False, type_priority, cmc if cmc is not None else paid_cost,
        False, False, payoff,
    )


class PayoffDetectionTest(unittest.TestCase):
    def setUp(self):
        # Detection normally reads oracle text; stub CardInfo so the tests never
        # depend on Scryfall being reachable.
        self._oracle = {
            AJANIS_PRIDEMATE: "Whenever you gain life, put a +1/+1 counter on this creature.",
            TWINBLADE_PALADIN: (
                "Whenever you gain life, put a +1/+1 counter on this creature.\n"
                "As long as you have 25 or more life, this creature has double strike."
            ),
            FIENDISH_PANDA: "Whenever you gain life, put a +1/+1 counter on this creature.",
            INSPIRING_OVERSEER: "Flying\nWhen this creature enters, you gain 1 life and draw a card.",
            VAMPIRE_NIGHTHAWK: "Flying\nDeathtouch\nLifelink",
        }
        original = CardInfo.get_oracle_text
        CardInfo.get_oracle_text = lambda grp_id: self._oracle.get(int(grp_id), "")
        self.addCleanup(setattr, CardInfo, "get_oracle_text", original)
        LifegainLogic._payoff_memo.clear()
        self.addCleanup(LifegainLogic._payoff_memo.clear)

    def test_detects_the_three_payoff_creatures(self):
        for grp_id in (AJANIS_PRIDEMATE, TWINBLADE_PALADIN, FIENDISH_PANDA):
            self.assertTrue(LifegainLogic.is_lifegain_payoff(grp_id), grp_id)

    def test_a_card_that_merely_gains_life_is_not_a_payoff(self):
        """Inspiring Overseer feeds the engine but does not grow from it, so it
        must not jump the queue."""
        self.assertFalse(LifegainLogic.is_lifegain_payoff(INSPIRING_OVERSEER))

    def test_lifelink_alone_is_not_a_payoff(self):
        self.assertFalse(LifegainLogic.is_lifegain_payoff(VAMPIRE_NIGHTHAWK))

    def test_every_printing_is_covered_without_oracle_text(self):
        """The offline fallback must cover all printings in the deck data -- a
        reprint is the failure mode a hand-written grpId list has."""
        CardInfo.get_oracle_text = lambda grp_id: ""
        LifegainLogic._payoff_memo.clear()
        for grp_id in (67690, 69455, 93447, 93848, 70069, 93652, 93833):
            self.assertTrue(LifegainLogic.is_lifegain_payoff(grp_id), grp_id)

    def test_bad_input_is_not_a_payoff(self):
        self.assertFalse(LifegainLogic.is_lifegain_payoff(None))
        self.assertFalse(LifegainLogic.is_lifegain_payoff("not-a-grpid"))


class CastOrderingTest(unittest.TestCase):
    def setUp(self):
        self.ai = DummyAI()
        self.ai._debug = lambda message: None

    def _choose(self, actions, colors=WB, mana=4):
        sources = [set(colors) for _ in range(mana)]
        chosen, _score = self.ai._select_cast_action_max_mana(
            actions, colors, mana, sources
        )
        return chosen

    def test_payoff_is_cast_first_within_the_same_plan(self):
        """Two 2-drops, 4 mana: both get cast this turn, but the AI returns one
        cast per decision, so the payoff must be the one returned now."""
        chosen = self._choose([
            cast_action(2, 101, "Ajani's Pridemate", payoff=True),
            cast_action(2, 102, "Vengeful Bloodwitch"),
        ])
        self.assertEqual(chosen[2], "Ajani's Pridemate")

    def test_payoff_wins_the_tie_regardless_of_list_order(self):
        chosen = self._choose([
            cast_action(2, 102, "Vengeful Bloodwitch"),
            cast_action(2, 101, "Ajani's Pridemate", payoff=True),
        ])
        self.assertEqual(chosen[2], "Ajani's Pridemate")

    def test_mana_efficiency_still_beats_the_payoff(self):
        """The payoff is a tiebreak, not an override: spending 4 mana on a 4-drop
        beats spending 2 on the Pridemate. Guards against the bot throwing away
        tempo to force the engine out."""
        chosen = self._choose([
            cast_action(2, 101, "Ajani's Pridemate", payoff=True),
            cast_action(4, 103, "Serra Angel"),
        ])
        self.assertEqual(chosen[2], "Serra Angel")

    def test_full_plan_still_leads_with_the_payoff(self):
        """4 mana, a 2-drop payoff and a 2-drop non-payoff: the plan spends all 4
        and the payoff goes first."""
        chosen = self._choose([
            cast_action(2, 103, "Ajani's Pridemate", payoff=True),
            cast_action(2, 104, "Inspiring Overseer"),
        ], mana=4)
        self.assertEqual(chosen[2], "Ajani's Pridemate")

    def test_no_payoff_available_keeps_the_old_ordering(self):
        """Without a payoff in hand the previous behaviour (most expensive first,
        type priority as tiebreak) must be unchanged."""
        chosen = self._choose([
            cast_action(1, 105, "Healer's Hawk"),
            cast_action(3, 106, "Vampire Nighthawk"),
        ], mana=4)
        self.assertEqual(chosen[2], "Vampire Nighthawk")

    def test_empty_input_is_handled(self):
        chosen, score = self.ai._select_cast_action_max_mana([], WB, 4, [WB])
        self.assertIsNone(chosen)
        self.assertIsNone(score)


if __name__ == "__main__":
    unittest.main()
