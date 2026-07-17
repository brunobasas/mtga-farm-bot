"""Unit tests for AI/DummyAI.py's named-activation helper (Finding 7):
_find_phoenix_chick_activation and _find_reassembling_skeleton_activation used
to be near-verbatim copies of each other. They were extracted into a shared
_find_named_activation helper; these tests pin the exact observable behavior
(including debug log wording) that the extraction promised to preserve.
"""
import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from AI.DummyAI import DummyAI


def activate_action(instance_id, grp_id, ability_grp_id=42, mana_cost=None, action_type="ActionType_Activate"):
    action = {"actionType": action_type, "instanceId": instance_id, "grpId": grp_id, "abilityGrpId": ability_grp_id}
    if mana_cost is not None:
        action["manaCost"] = mana_cost
    return {"action": action}


class DummyAIActivationTest(unittest.TestCase):
    def setUp(self):
        self.ai = DummyAI()
        self.debug_messages = []
        # _debug() opens a real log file per call; capture instead so tests
        # don't touch disk and so we can assert on exact wording.
        self.ai._debug = self.debug_messages.append

    def _card_info(self, name):
        return patch("AI.DummyAI.CardInfo.get_card_info", return_value={"name": name})

    def test_phoenix_chick_found_with_explicit_payable_mana_cost(self):
        action_list = [activate_action(10, 111, mana_cost=[{"color": ["ManaColor_Red"], "count": 1}])]
        with self._card_info("Phoenix Chick"):
            result = self.ai._find_phoenix_chick_activation(action_list, {}, {"red"}, total_mana=1, sources=[{"red"}])
        self.assertEqual(result, (10, 42))
        self.assertEqual(self.debug_messages, [])

    def test_phoenix_chick_explicit_mana_cost_not_payable_logs_specific_message(self):
        action_list = [activate_action(10, 111, mana_cost=[{"color": ["ManaColor_Red"], "count": 5}])]
        with self._card_info("Phoenix Chick"):
            result = self.ai._find_phoenix_chick_activation(action_list, {}, {"red"}, total_mana=1, sources=[{"red"}])
        self.assertIsNone(result)
        self.assertEqual(self.debug_messages, ["Phoenix Chick activation available but mana cost not payable"])

    def test_phoenix_chick_falls_back_to_rr_when_mana_cost_missing(self):
        action_list = [activate_action(10, 111, mana_cost=None)]
        with self._card_info("Phoenix Chick"):
            # Only 1 red source available: RR (2 red) is not payable.
            result = self.ai._find_phoenix_chick_activation(
                action_list, {}, {"red"}, total_mana=1, sources=[{"red"}]
            )
        self.assertIsNone(result)
        self.assertEqual(self.debug_messages, ["Phoenix Chick activation available but RR not payable"])

    def test_phoenix_chick_rr_fallback_payable(self):
        action_list = [activate_action(10, 111, mana_cost=None)]
        with self._card_info("Phoenix Chick"):
            result = self.ai._find_phoenix_chick_activation(
                action_list, {}, {"red"}, total_mana=2, sources=[{"red"}, {"red"}]
            )
        self.assertEqual(result, (10, 42))

    def test_reassembling_skeleton_found_with_explicit_payable_mana_cost(self):
        action_list = [activate_action(20, 222, mana_cost=[{"color": ["ManaColor_Black"], "count": 1}])]
        with self._card_info("Reassembling Skeleton"):
            result = self.ai._find_reassembling_skeleton_activation(
                action_list, {}, {"black"}, total_mana=1, sources=[{"black"}]
            )
        self.assertEqual(result, (20, 42))

    def test_reassembling_skeleton_falls_back_to_1b_when_mana_cost_missing(self):
        action_list = [activate_action(20, 222, mana_cost=None)]
        with self._card_info("Reassembling Skeleton"):
            # No sources at all: 1B fallback is not payable.
            result = self.ai._find_reassembling_skeleton_activation(
                action_list, {}, set(), total_mana=0, sources=[]
            )
        self.assertIsNone(result)
        self.assertEqual(
            self.debug_messages,
            ["Reassembling Skeleton return available but mana cost not payable"],
        )

    def test_reassembling_skeleton_1b_fallback_payable(self):
        action_list = [activate_action(20, 222, mana_cost=None)]
        with self._card_info("Reassembling Skeleton"):
            result = self.ai._find_reassembling_skeleton_activation(
                action_list, {}, {"black"}, total_mana=2, sources=[{"black"}, {"black"}]
            )
        self.assertEqual(result, (20, 42))

    def test_activate_mana_actions_are_skipped(self):
        action_list = [activate_action(30, 333, action_type="ActionType_Activate_Mana")]
        with self._card_info("Phoenix Chick"):
            result = self.ai._find_phoenix_chick_activation(action_list, {}, {"red"}, total_mana=5, sources=[{"red"}] * 5)
        self.assertIsNone(result)

    def test_non_matching_card_name_is_ignored(self):
        action_list = [activate_action(10, 111, mana_cost=[{"color": ["ManaColor_Red"], "count": 1}])]
        with self._card_info("Some Other Card"):
            result = self.ai._find_phoenix_chick_activation(action_list, {}, {"red"}, total_mana=1, sources=[{"red"}])
        self.assertIsNone(result)

    def test_both_wrappers_delegate_to_shared_helper(self):
        """Pin the extraction itself: both card-specific finders must be thin
        wrappers around the one shared _find_named_activation implementation
        (Finding 7), not independent copies."""
        calls = []
        original = DummyAI._find_named_activation

        def spy(self, *args, **kwargs):
            calls.append(kwargs.get("card_name"))
            return original(self, *args, **kwargs)

        with patch.object(DummyAI, "_find_named_activation", spy):
            with self._card_info("Phoenix Chick"):
                self.ai._find_phoenix_chick_activation([], {}, set(), total_mana=0, sources=[])
            with self._card_info("Reassembling Skeleton"):
                self.ai._find_reassembling_skeleton_activation([], {}, set(), total_mana=0, sources=[])

        self.assertEqual(calls, ["Phoenix Chick", "Reassembling Skeleton"])


if __name__ == "__main__":
    unittest.main()
