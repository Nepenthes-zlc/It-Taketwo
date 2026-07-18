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


def _player_record(task: dict[str, Any], agent_name: str) -> dict[str, Any]:
    key = "player_a" if agent_name == "AgentA" else "player_b"
    value = task.get("players", {}).get(key, {})
    return value if isinstance(value, dict) else {}


def _role_goal(task: dict[str, Any], agent_name: str) -> str:
    player = _player_record(task, agent_name)
    role = str(player.get("role") or "participant").replace("_", " ")
    goal = player.get("goal", {}) if isinstance(player.get("goal"), dict) else {}
    description = str(goal.get("description") or task.get("task_description") or "Complete your assigned part of the task.")
    failure_descriptions = [
        str(condition.get("description"))
        for condition in task.get("failure_conditions", []) or []
        if isinstance(condition, dict) and condition.get("description")
    ]
    text = f"You control {agent_name}. Your role is {role}. Your goal: {description}"
    if failure_descriptions:
        text += " Avoid these failure conditions: " + " ".join(failure_descriptions)
    return text


def _display_agent_name(agent_name: str) -> str:
    return "Agent A" if agent_name == "AgentA" else "Agent B"


def _is_truck_driver_agent_a(task: dict[str, Any], agent_name: str) -> bool:
    task_template = str(task.get("task_template") or "").strip().lower()
    return agent_name == "AgentA" and task_template in {"truck_driver", "truck_blind_navigation"}


def _prompt_context(
    *,
    agent_name: str,
    teammate_name: str,
    task: dict[str, Any],
    teammate_previous_message: str | None = None,
) -> tuple[bool, str, str, str]:
    mode = str(task.get("task_mode") or "multiagent").strip().lower().replace("-", "_")
    single_agent = mode in {"single", "single_agent", "singleagent", "atomic"}
    display_agent = _display_agent_name(agent_name)
    display_teammate = _display_agent_name(teammate_name)
    received = teammate_previous_message.strip() if teammate_previous_message and teammate_previous_message.strip() else "No message received; this is the first communication round."
    if _is_truck_driver_agent_a(task, agent_name):
        teammate_note = "This instruction overrides your black image; do not wait for visual confirmation when the instruction is clear."
        decision_guidance = "Your image is intentionally black for this blind-driving task. Do not treat the black image as missing evidence or as a reason to wait. If Agent B gives a clear movement instruction such as forward, turn_left, or turn_right, execute it immediately. Use your own image only to confirm that it is the blind-driver black view, not to reject Agent B's guidance. Do not apply the general visual-evidence-first rule to override clear Agent B navigation commands."
    else:
        teammate_note = "This message may be stale; verify it against your own current image."
        decision_guidance = "Use visual evidence first. Do not rely on hidden coordinates or sensors. Do not output teleport commands."
    teammate_lines = "" if single_agent else (
        f"Teammate: {display_teammate}\n"
        f"Message received from {display_teammate} after the previous round: {received}\n"
        f"{teammate_note}\n"
    )
    return single_agent, display_agent, teammate_lines, decision_guidance


def _build_cooperation_prompt(
    *,
    agent_name: str,
    teammate_name: str,
    task: dict[str, Any],
    step_index: int,
    allowed_actions: list[str],
    task_type: str,
    team_objective: str,
    agent_a_goal: str,
    agent_b_goal: str,
    role_guidance: str,
    teammate_previous_message: str | None = None,
) -> str:
    single_agent, display_agent, teammate_lines, decision_guidance = _prompt_context(
        agent_name=agent_name,
        teammate_name=teammate_name,
        task=task,
        teammate_previous_message=teammate_previous_message,
    )
    role_goal = agent_a_goal if agent_name == "AgentA" else agent_b_goal
    return f"""
You are controlling one Minecraft agent using only low-level actions.

Task type: {task_type}.
Team objective: {team_objective}

You control {display_agent}.
Your role and goal: {role_goal}

You may choose exactly one action from this allowed list:
{json.dumps(allowed_actions)}

Action meanings:
- forward moves relative to the current view.
- turn_left/turn_right rotate the view.
- look_up/look_down adjust camera pitch.
- wait stops movement for this step.

Step index: {step_index}
Your agent: {display_agent}
{teammate_lines}
The image is your own first-person view. You cannot see the teammate's camera view or any agent coordinates.
Before deciding, read the teammate's previous-round message and inspect only your own current image.
{role_guidance}
Both agents decide simultaneously in this round.
{decision_guidance}

Return ONLY compact JSON:
{{"action":"one_allowed_action", "reason":"short visual and coordination reason", "message":"brief useful message to your teammate for the next round"}}
The message should report useful current observations, whether your role is ready/blocked/completed, and what you intend or need next.
In single-agent mode, set message to an empty string.
""".strip()


def build_elevator_hold_door_prompt(
    *,
    agent_name: str,
    teammate_name: str,
    task: dict[str, Any],
    step_index: int,
    allowed_actions: list[str],
    teammate_previous_message: str | None = None,
) -> str:
    return _build_cooperation_prompt(
        agent_name=agent_name,
        teammate_name=teammate_name,
        task=task,
        step_index=step_index,
        allowed_actions=allowed_actions,
        task_type="elevator hold-door cooperation",
        team_objective="Agent A holds a pressure plate to keep the elevator door open while Agent B enters the elevator doorway.",
        agent_a_goal="Hold a pressure plate and keep the elevator door open. If the door is closed, visually locate a pressure plate on the floor and move onto it to open the door. Once you see that the door is open, choose wait and keep waiting until Agent B passes through. Use your message to tell Agent B that the door is open and ask Agent B to pass through quickly.",
        agent_b_goal="Enter the elevator doorway while Agent A is holding a pressure plate. If the door is closed, move to the doorway and wait there; use your message to ask Agent A to open the door as soon as possible. Once you see that the door is open, move through it quickly.",
        role_guidance="If you are the door holder, visually locate and remain on a pressure plate. If you are the entrant, visually locate the elevator doorway and move through it while the plate is held.",
        teammate_previous_message=teammate_previous_message,
    )


def build_pressure_path_reveal_prompt(
    *,
    agent_name: str,
    teammate_name: str,
    task: dict[str, Any],
    step_index: int,
    allowed_actions: list[str],
    teammate_previous_message: str | None = None,
) -> str:
    return _build_cooperation_prompt(
        agent_name=agent_name,
        teammate_name=teammate_name,
        task=task,
        step_index=step_index,
        allowed_actions=allowed_actions,
        task_type="pressure-path reveal cooperation",
        team_objective="Agent A holds a pressure plate to reveal a temporary path while Agent B crosses it and reaches the gold-block goal marker on the opposite bank.",
        agent_a_goal="Hold a pressure plate and keep the temporary path visible. Once stepping on the pressure plate reveals the path, or once Agent B is on the path, choose wait and keep waiting so the path remains available. Never move off the pressure plate while Agent B is crossing, because the path will disappear; if Agent B falls into the pit, the task fails immediately.",
        agent_b_goal="Cross the revealed path and reach the gold-block goal marker on the opposite bank. If the path ahead is not visible, wait in place for Agent A to reveal it and use your message to tell Agent A that the path is still closed. Move forward only after you can visually confirm the path exists. Moving without a visible path will make you fall into the pit, which fails the task immediately.",
        role_guidance="If you are the path revealer, visually locate and remain on a pressure plate. If you are the crosser, visually confirm the path, cross carefully, and continue to the opposite-bank marker without falling.",
        teammate_previous_message=teammate_previous_message,
    )


def build_truck_blind_navigation_prompt(
    *,
    agent_name: str,
    teammate_name: str,
    task: dict[str, Any],
    step_index: int,
    allowed_actions: list[str],
    teammate_previous_message: str | None = None,
) -> str:
    return _build_cooperation_prompt(
        agent_name=agent_name,
        teammate_name=teammate_name,
        task=task,
        step_index=step_index,
        allowed_actions=allowed_actions,
        task_type="blind truck-driver navigation cooperation",
        team_objective="Agent A, the blind truck driver, must follow Agent B's visual navigation guidance and stop completely inside the colored target area. Agent B is the guide who observes Agent A and the target area and gives safe step-by-step directions.",
        agent_a_goal="You are the blind truck driver. Reach and stop completely inside the colored target area by following Agent B's latest navigation message. Do not try to identify, select, or navigate toward a target color by yourself. If Agent B gives you a clear action instruction, follow it strictly. If Agent B's instruction is missing, stale, ambiguous, or says to stop, choose wait. Never continue moving after Agent B reports that you are inside or aligned with the target area; choose wait and remain stopped.",
        agent_b_goal="You are the navigation guide. If you cannot see Agent A or the colored target area, rotate your view or reposition yourself until you locate both of them. Once both Agent A and the colored target area are visible, choose wait to keep your observation position and use your message to tell Agent A exactly which action to take to reach the colored target area. Give Agent A one clear action at a time from Agent A's perspective, reassessing after each move and warning before overshooting. Tell Agent A to stop and wait once fully inside the colored target area. Do not enter or occupy the target area yourself unless repositioning is necessary to see both Agent A and the target.",
        role_guidance="The room's floor, walls, and ceiling are white; the colored floor region is the destination. Agent A must treat Agent B's message as navigation guidance rather than relying on the target's color. Agent B must express turns from Agent A's viewpoint, keep instructions brief, and use the message to provide the next driving command. Success requires Agent A to be fully within the colored target region and stopped.",
        teammate_previous_message=teammate_previous_message,
    )



def build_picture_center_alignment_prompt(
    *,
    agent_name: str,
    teammate_name: str,
    task: dict[str, Any],
    step_index: int,
    allowed_actions: list[str],
    teammate_previous_message: str | None = None,
) -> str:
    return _build_cooperation_prompt(
        agent_name=agent_name,
        teammate_name=teammate_name,
        task=task,
        step_index=step_index,
        allowed_actions=allowed_actions,
        task_type="elevated picture-centering cooperation",
        team_objective="Agent A is on the elevated platform positioning a picture and must align it with the center of the colored target area directly below the platform.",
        agent_a_goal="You are responsible for aligning the picture from the elevated platform. For now, you do not need to handle the picture itself; you only need to move to the target position. Your view cannot show the colored target area, so do not rely heavily on your image; you cannot complete the task using your own visual judgement alone. Use the message from Agent B to decide your action and follow the guidance from Agent B until you reach the position directly above the colored target area.",
        agent_b_goal="You are the visual alignment guide. You can reliably see the colored target area. Choose wait to preserve your observation position, then determine whether Agent A is directly above the colored target area. From the perspective of Agent A, use your message to tell Agent A exactly how to move using forward, turn_left, turn_right, or wait, and guide Agent A to the position directly above the colored target area. Reassess after every movement. Once Agent A is correctly aligned, tell Agent A to wait and remain still.",
        role_guidance="The room's floor, walls, ceiling, and elevated platform are white. The colored block region is randomly positioned but lies completely and exactly beneath the platform. Agent A must rely on Agent B's message rather than guessing the target position or color. Agent B must keep the colored region and Agent A visible, use brief unambiguous instructions, and stop Agent A as soon as the picture is centered over the region.",
        teammate_previous_message=teammate_previous_message,
    )


def build_maze_command_guidance_prompt(
    *,
    agent_name: str,
    teammate_name: str,
    task: dict[str, Any],
    step_index: int,
    allowed_actions: list[str],
    teammate_previous_message: str | None = None,
) -> str:
    return _build_cooperation_prompt(
        agent_name=agent_name,
        teammate_name=teammate_name,
        task=task,
        step_index=step_index,
        allowed_actions=allowed_actions,
        task_type="overhead maze-guidance cooperation",
        team_objective="Agent A must reach the colored target area on the ground. Agent B observes the maze from the fixed top-center overhead position and guides Agent A with short step-by-step commands.",
        agent_a_goal="You are the maze walker. Your goal is to stand directly above the colored target area on the ground. If you can see the colored target area in your own view, use your own perspective to move onto it. If you cannot see the colored target area, rely more on Agent B's message about which action to take: if Agent B gives a clear action instruction, follow it strictly one action at a time; if Agent B's instruction is missing, stale, ambiguous, or says to stop, choose wait; once Agent B says you are at the goal, choose wait and remain stopped.",
        agent_b_goal="You are the overhead maze guide. You start at the top-center of the room looking down at the maze; keep this observation position by choosing wait. Use your message to guide Agent A from Agent A's perspective with exactly one next action: forward, turn_left, turn_right, or wait. Track Agent A's current facing direction and tell Agent A to wait once it reaches the colored goal region.",
        role_guidance="The maze corridor is two blocks wide. Maze walls are high and have a glowstone bottom layer; the colored floor patch is the goal. Agent A must move cautiously and obey Agent B's newest clear instruction. Agent B should give brief, unambiguous commands from Agent A's viewpoint and reassess after each step.",
        teammate_previous_message=teammate_previous_message,
    )

def build_agent_action_prompt(
    *,
    agent_name: str,
    teammate_name: str,
    task: dict[str, Any],
    step_index: int,
    allowed_actions: list[str],
    poses: dict[str, Any],
    teammate_previous_message: str | None = None,
) -> str:
    del poses
    builders = {
        "elevator_hold_door": build_elevator_hold_door_prompt,
        "pressure_path_reveal": build_pressure_path_reveal_prompt,
        "truck_driver": build_truck_blind_navigation_prompt,
        "truck_blind_navigation": build_truck_blind_navigation_prompt,
        "picture_center_alignment": build_picture_center_alignment_prompt,
        "high_platform_gold_guidance": build_picture_center_alignment_prompt,
        "maze_command_guidance": build_maze_command_guidance_prompt,
    }
    task_template = str(task.get("task_template") or "").strip()
    try:
        builder = builders[task_template]
    except KeyError as exc:
        raise ValueError(f"unsupported task_template for prompt: {task_template!r}") from exc
    return builder(
        agent_name=agent_name,
        teammate_name=teammate_name,
        task=task,
        step_index=step_index,
        allowed_actions=allowed_actions,
        teammate_previous_message=teammate_previous_message,
    )
