from __future__ import annotations

import json
from typing import Any


def extract_first_json_object(text: str) -> dict[str, Any]:
    start = text.find("{")
    if start < 0:
        raise ValueError(f"model did not return a JSON object: {text!r}")
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : index + 1])
    raise ValueError(f"unclosed JSON object in model response: {text!r}")


def build_agent_action_prompt(
    *,
    agent_name: str,
    teammate_name: str,
    task: dict[str, Any],
    step_index: int,
    allowed_actions: list[str],
    poses: dict[str, Any],
) -> str:
    task_text = task.get("task_description") or "Player A holds the pressure plate while Player B enters the second room."
    if agent_name == "AgentA":
        role_goal = (
            "You control AgentA. AgentA's job is to find, step onto, and keep holding the stone pressure plate. "
            "Do not wait unless the visual evidence suggests AgentA is actually on the pressure plate."
        )
    else:
        role_goal = (
            "You control AgentB. AgentB's job is to move through the doorway/elevator door into the second room. "
            "If the door is not passable, keep searching or positioning for the doorway instead of assuming success."
        )

    own_pose = poses.get(agent_name, {})
    teammate_pose = poses.get(teammate_name, {})
    return f"""
You are driving one Minecraft fake player using only low-level actions.

Task: {task_text}

{role_goal}

You may choose exactly one action from this allowed list:
{json.dumps(allowed_actions)}

Action meanings:
- forward/backward/strafe_left/strafe_right move relative to the current view.
- turn_left/turn_right rotate the view.
- look_up/look_down adjust camera pitch.
- jump jumps briefly.
- wait stops movement for this step.

Step index: {step_index}
Your agent: {agent_name}
Teammate: {teammate_name}
Your last known pose: {json.dumps(own_pose, ensure_ascii=False)}
Teammate last known pose: {json.dumps(teammate_pose, ensure_ascii=False)}

The first image is your own first-person view. The second image is the teammate's first-person view.
Use visual evidence first. Do not rely on hidden coordinates or sensors. Do not output teleport commands.

Return ONLY compact JSON:
{{"action":"one_allowed_action", "reason":"short reason"}}
""".strip()
