from __future__ import annotations

ACTION_TO_PUPPET = {
    "wait": "stop",
    "forward": "w 0.12",
    # "backward": "s 0.12",
    # "strafe_left": "a 0.12",
    # "strafe_right": "d 0.12",
    "jump": "jump 0.2",
    "turn_left": "turn -20 0 0.1",
    "turn_right": "turn 20 0 0.1",
    "look_up": "turn 0 -15 0.1",
    "look_down": "turn 0 15 0.1",
}

# Jump is intentionally excluded from policy actions for the door/pressure-plate rollout.
# Keeping the low-level mapping lets manual tests still call it explicitly if needed.
ALLOWED_ACTIONS = [action for action in ACTION_TO_PUPPET if action != "jump"]
