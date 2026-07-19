import unittest
from unittest.mock import patch

from state.state_machine import BotState
from tools.session_watchdog import _Thresholds, _detect_stuck_reason


class SessionWatchdogStallTests(unittest.TestCase):
    def setUp(self):
        self.thresholds = _Thresholds()

    def test_critical_inactivity_timer_is_reported_outside_home(self):
        status = {
            "bot_state": str(BotState.IN_GAME),
            "my_timer_type": "TimerType_Inactivity",
            "my_timer_critical_count": 1,
        }

        self.assertEqual(
            _detect_stuck_reason(status, self.thresholds),
            "repeated_own_timer_critical",
        )

    @patch("tools.session_watchdog.time.time", return_value=1000.0)
    def test_stalled_local_priority_is_reported(self, _time):
        status = {
            "bot_state": str(BotState.IN_GAME),
            "mode": "in_game",
            "my_timer_type": "TimerType_Inactivity",
            "my_timer_running": True,
            "my_timer_elapsed_sec": 60.0,
            "my_timer_remaining_sec": 10.0,
            "last_input_at_epoch": 900.0,
            "last_decision_at_epoch": 900.0,
            "last_playerlog_event_at_epoch": 900.0,
            "local_system_seat_id": 1,
            "turn_info": {"decisionPlayer": 1, "priorityPlayer": 2},
        }

        self.assertEqual(
            _detect_stuck_reason(status, self.thresholds),
            "own_inactivity_timer_stalled",
        )

    @patch("tools.session_watchdog.time.time", return_value=1000.0)
    def test_stall_is_ignored_without_local_priority(self, _time):
        status = {
            "bot_state": str(BotState.IN_GAME),
            "mode": "in_game",
            "my_timer_type": "TimerType_Inactivity",
            "my_timer_running": True,
            "my_timer_elapsed_sec": 60.0,
            "last_input_at_epoch": 900.0,
            "local_system_seat_id": 1,
            "turn_info": {"decisionPlayer": 2, "priorityPlayer": 2},
        }

        self.assertIsNone(_detect_stuck_reason(status, self.thresholds))


if __name__ == "__main__":
    unittest.main()
