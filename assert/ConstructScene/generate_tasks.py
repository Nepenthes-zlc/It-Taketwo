#!/usr/bin/env python3
"""Generate randomized multi-agent task JSON from generated scene manifests."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


SUPPORTED_TASK_TEMPLATES = {
    "elevator_hold_door",
    "truck_reverse_guidance",
    "heavy_object_dual_drag",
    "lift_time_dependency",
}

# Extra cells of clearance kept between a spawn position and any wall, on top of
# the 1-cell inset already applied. With margin 1 the base spawn cell sits >=2
# cells from the wall block, so after the rollout's +/-0.6 position jitter the
# agent still spawns >=~1.4 blocks clear of walls (no wall-hugging / clipping).
# Overridable via --wall-margin.
WALL_MARGIN = 1


TASK_TEMPLATE_ALIASES = {
    "elevator": "elevator_hold_door",
    "elevator_hold_door": "elevator_hold_door",
    "truck": "truck_reverse_guidance",
    "truck_reverse_guidance": "truck_reverse_guidance",
    "heavy": "heavy_object_dual_drag",
    "heavy_object_dual_drag": "heavy_object_dual_drag",
    "lift": "lift_time_dependency",
    "lift_time_dependency": "lift_time_dependency",
}


def load_manifest(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def relativize_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def center_from_region(region: Sequence[int]) -> List[float]:
    return [
        round((region[0] + region[3]) / 2, 3),
        round(region[1], 3),
        round((region[2] + region[5]) / 2, 3),
    ]


def elevator_door_regions(door_region: Sequence[int], b_start: Sequence[float]) -> tuple[List[float], List[float]]:
    """Two floor-level door targets, mirroring game_functions at runtime:
    - cell region (multiagent target): the door cells themselves
    - front region (single-agent target): door cells + one row on the player's side (2xN)
    """
    x0, y0, z0, x1, y1, z1 = [float(v) for v in door_region[:6]]
    xlo, xhi, zlo, zhi = min(x0, x1), max(x0, x1), min(z0, z1), max(z0, z1)
    cell = [xlo, y0, zlo, xhi, y0, zhi]
    if int(z0) == int(z1):  # door along x; approach along z
        door_z = zlo
        if float(b_start[2]) <= door_z:
            front = [xlo, y0, door_z - 1.0, xhi, y0, door_z]
        else:
            front = [xlo, y0, door_z, xhi, y0, door_z + 1.0]
    elif int(x0) == int(x1):  # door along z; approach along x
        door_x = xlo
        if float(b_start[0]) <= door_x:
            front = [door_x - 1.0, y0, zlo, door_x, y0, zhi]
        else:
            front = [door_x, y0, zlo, door_x + 1.0, y0, zhi]
    else:
        front = list(cell)
    return cell, front


def random_rotation(rng: random.Random) -> List[float]:
    yaw = round(rng.uniform(-180.0, 180.0), 1)
    pitch = round(rng.uniform(10.0, 35.0), 1)
    return [yaw, pitch]


def choose_xy_positions(
    rng: random.Random,
    x_min: int,
    x_max: int,
    y: int,
    z_min: int,
    z_max: int,
    count: int = 1,
    min_dist: int = 2,
) -> List[List[float]]:
    candidates: List[Tuple[int, int]] = []
    for x in range(x_min, x_max + 1):
        for z in range(z_min, z_max + 1):
            candidates.append((x, z))
    rng.shuffle(candidates)

    selected: List[Tuple[int, int]] = []
    for candidate in candidates:
        if all(abs(candidate[0] - sx) + abs(candidate[1] - sz) >= min_dist for sx, sz in selected):
            selected.append(candidate)
            if len(selected) == count:
                break

    if len(selected) < count:
        raise ValueError("Not enough valid spawn positions in the requested region.")

    return [[float(x), float(y), float(z)] for x, z in selected]


def elevator_spawn_points(scene: Dict[str, Any], rng: random.Random) -> Tuple[List[float], List[float]]:
    ox, oy, oz = scene["origin"]
    width, _, _ = scene["room_size"]
    plate_region = scene.get("pressure_plate_region")
    if isinstance(plate_region, list) and len(plate_region) >= 6:
        plate_x = int(round((float(plate_region[0]) + float(plate_region[3])) / 2.0))
        plate_y = int(plate_region[1])
        plate_z = int(round((float(plate_region[2]) + float(plate_region[5])) / 2.0))
    else:
        plate_x, plate_y, plate_z = scene["pressure_plate_pos"]
    door = scene["door_region"]
    door_center_z = round((door[2] + door[5]) / 2)
    first_room_z_max = max(oz + 1, min(plate_z - 1, door_center_z - 2))
    # Keep spawns off the wall-adjacent ring: inset the west/east walls (x) and
    # the north wall (z_min) by WALL_MARGIN extra cells. z_max is bounded by the
    # plate/door, not a wall, so it is left untouched.
    x_lo = ox + 1 + WALL_MARGIN
    x_hi = ox + width - 2 - WALL_MARGIN
    z_lo = min(oz + 1 + WALL_MARGIN, first_room_z_max)
    if x_hi < x_lo:
        x_lo, x_hi = ox + 1, ox + width - 2
    positions = choose_xy_positions(
        rng,
        x_lo,
        x_hi,
        plate_y,
        z_lo,
        first_room_z_max,
        count=2,
        min_dist=4,
    )
    if rng.random() < 0.5:
        positions.reverse()
    return positions[0], positions[1]


def truck_spawn_points(scene: Dict[str, Any], rng: random.Random) -> Tuple[List[float], List[float]]:
    truck = scene["truck_region"]
    obs = scene["observation_platform"]
    driver = center_from_region(truck)
    driver[2] = max(driver[2] - 1.0, scene["origin"][2] + 2.0)

    ox, oy, oz = scene["origin"]
    width, _, _ = scene["room_size"]
    observer = choose_xy_positions(
        rng,
        obs[0],
        obs[3],
        oy + 1,
        obs[2],
        obs[5],
        count=1,
        min_dist=1,
    )[0]
    observer[1] = float(obs[1])
    if observer[0] <= ox or observer[0] >= ox + width - 1:
        observer[0] = float(ox + 1)
    return driver, observer


def heavy_spawn_points(scene: Dict[str, Any], rng: random.Random) -> Tuple[List[float], List[float]]:
    left_pad, right_pad = scene["drag_pad_positions"]
    left_spawn = [float(left_pad[0]), float(left_pad[1]), float(left_pad[2] - 1)]
    right_spawn = [float(right_pad[0]), float(right_pad[1]), float(right_pad[2] - 1)]
    if rng.random() < 0.5:
        left_spawn[2] += 1.0
    if rng.random() < 0.5:
        right_spawn[2] += 1.0
    return left_spawn, right_spawn


def nearby_spawn_points(
    scene_region: Sequence[int],
    anchor_pos: Sequence[int],
    rng: random.Random,
    count: int = 2,
    max_distance: int = 3,
) -> List[List[float]]:
    x0, y0, z0, x1, _, z1 = scene_region
    ax, ay, az = anchor_pos
    candidates: List[Tuple[int, int]] = []
    for x in range(x0, x1 + 1):
        for z in range(z0, z1 + 1):
            if x == ax and z == az:
                continue
            if (x - ax) ** 2 + (z - az) ** 2 <= max_distance ** 2:
                candidates.append((x, z))

    rng.shuffle(candidates)
    selected: List[Tuple[int, int]] = []
    for candidate in candidates:
        if candidate in selected:
            continue
        selected.append(candidate)
        if len(selected) == count:
            break

    if len(selected) < count:
        raise ValueError("Not enough nearby positions to place all lift agents.")

    return [[float(x), float(ay), float(z)] for x, z in selected]


def build_elevator_task(scene: Dict[str, Any], rng: random.Random, task_id: int) -> Dict[str, Any]:
    a_start, b_start = elevator_spawn_points(scene, rng)
    plate = scene["pressure_plate_pos"]
    plate_region = scene.get("pressure_plate_region") or [plate[0], plate[1], plate[2], plate[0], plate[1], plate[2]]
    plate_positions = scene.get("pressure_plate_positions") or [plate]
    door_region = scene["door_region"]
    door_goal = center_from_region(door_region)
    door_cell_region, door_front_region = elevator_door_regions(door_region, b_start)

    return {
        "id": task_id,
        "scene_id": scene["scene_id"],
        "task_template": scene["task_template"],
        "scene_setup_function": scene["setup_function"],
        "scene_clear_function": scene["clear_function"],
        "task_description": "Player A must hold the pressure plate so Player B can pass through the elevator door.",
        "players": {
            "player_a": {
                "role": "door_holder",
                "start_pos": a_start,
                "start_rotation": random_rotation(rng),
                "goal": {
                    "type": "hold_region",
                    "target_pos": [float(plate[0]), float(plate[1]), float(plate[2])],
                    "target_region": plate_region,
                    "target_positions": plate_positions,
                    "pressure_plate_block": scene.get("pressure_plate_block", "minecraft:stone_pressure_plate"),
                    "description": "Move onto any pressure plate in the 3x3 region and keep the elevator door open.",
                },
            },
            "player_b": {
                "role": "elevator_entry",
                "start_pos": b_start,
                "start_rotation": random_rotation(rng),
                "goal": {
                    "type": "reach_region",
                    "target_region": door_region,
                    "target_pos": door_goal,
                    "door_cell_region": door_cell_region,
                    "door_front_region": door_front_region,
                    "description": "Enter the elevator doorway while Player A is still holding the pressure plate.",
                },
            },
        },
        "success_conditions": [
            {
                "type": "block_state_any",
                "target_pos": plate,
                "target_region": plate_region,
                "target_positions": plate_positions,
                "pressure_plate_block": scene.get("pressure_plate_block", "minecraft:stone_pressure_plate"),
                "expected_block_state": "pressure_plate_powered",
                "description": "Any pressure plate in the 3x3 region is being pressed by Player A.",
            },
            {
                "type": "player_in_region",
                "player": "player_b",
                "target_region": door_region,
                "description": "Player B is inside the elevator door region.",
            },
        ],
    }


def build_truck_task(scene: Dict[str, Any], rng: random.Random, task_id: int) -> Dict[str, Any]:
    driver_start, observer_start = truck_spawn_points(scene, rng)
    parking_zone = scene["parking_zone"]

    return {
        "id": task_id,
        "scene_id": scene["scene_id"],
        "task_template": scene["task_template"],
        "scene_setup_function": scene["setup_function"],
        "scene_clear_function": scene["clear_function"],
        "task_description": "Player A drives the truck backward while Player B shares missing rear-view information from the observation platform.",
        "players": {
            "player_a": {
                "role": "driver",
                "start_pos": driver_start,
                "start_rotation": [180.0, 0.0],
                "goal": {
                    "type": "park_vehicle",
                    "target_region": parking_zone,
                    "description": "Back the truck into the parking zone without direct full rear visibility.",
                },
            },
            "player_b": {
                "role": "spotter",
                "start_pos": observer_start,
                "start_rotation": random_rotation(rng),
                "goal": {
                    "type": "guide_from_position",
                    "target_region": scene["observation_platform"],
                    "description": "Stay on the observation platform and guide the driver with rear-view information.",
                },
            },
        },
        "success_conditions": [
            {
                "type": "all_blocks_match_state",
                "target_positions": scene["parking_checkpoint_plates"],
                "expected_block_state": "checkpoint_plate_powered",
                "description": "The truck has reached the two rear parking checkpoints.",
            },
            {
                "type": "indicator_region_state",
                "target_region": scene["indicator_region"],
                "expected_block": "guidance_indicator_on_block",
                "description": "The parking indicator has turned green.",
            },
        ],
    }


def build_heavy_task(scene: Dict[str, Any], rng: random.Random, task_id: int) -> Dict[str, Any]:
    left_start, right_start = heavy_spawn_points(scene, rng)
    target_region = scene["heavy_object_target"]

    return {
        "id": task_id,
        "scene_id": scene["scene_id"],
        "task_template": scene["task_template"],
        "scene_setup_function": scene["setup_function"],
        "scene_clear_function": scene["clear_function"],
        "task_description": "Both players must drag the heavy object together. One player alone is not enough to move it.",
        "players": {
            "player_a": {
                "role": "left_dragger",
                "start_pos": left_start,
                "start_rotation": [0.0, 0.0],
                "goal": {
                    "type": "hold_position",
                    "target_pos": scene["drag_pad_positions"][0],
                    "description": "Stand on the left drag pad at the same time as Player B.",
                },
            },
            "player_b": {
                "role": "right_dragger",
                "start_pos": right_start,
                "start_rotation": [180.0, 0.0],
                "goal": {
                    "type": "hold_position",
                    "target_pos": scene["drag_pad_positions"][1],
                    "description": "Stand on the right drag pad at the same time as Player A.",
                },
            },
        },
        "success_conditions": [
            {
                "type": "all_blocks_match_state",
                "target_positions": scene["drag_pad_positions"],
                "expected_block_state": "drag_pad_powered",
                "description": "Both drag pads are pressed simultaneously.",
            },
            {
                "type": "region_filled",
                "target_region": target_region,
                "expected_block": "moved_object_block",
                "description": "The heavy object has been moved into the target region.",
            },
        ],
    }


def build_lift_task(scene: Dict[str, Any], rng: random.Random, task_id: int) -> Dict[str, Any]:
    object_spawn_pos = scene["object_spawn_pos"]
    object_goal_pos = scene["object_goal_pos"]
    source_zone = scene["source_zone"]
    target_zone = scene["target_zone"]
    a_start, b_start = nearby_spawn_points(source_zone, object_spawn_pos, rng, count=2, max_distance=3)

    return {
        "id": task_id,
        "scene_id": scene["scene_id"],
        "task_template": scene["task_template"],
        "control_mode": scene.get("control_mode", "external_mod_binding"),
        "scene_setup_function": scene["setup_function"],
        "scene_clear_function": scene["clear_function"],
        "task_description": "Two players must bind to the mod-controlled heavy object and pull it from the source floor to the target floor together.",
        "source_zone": source_zone,
        "target_zone": target_zone,
        "object_spawn_pos": object_spawn_pos,
        "object_goal_pos": object_goal_pos,
        "coordination_constraints": {
            "max_agent_spawn_distance_to_object": 3,
            "object_control_mode": scene.get("control_mode", "external_mod_binding"),
            "description": "Both agents start within three blocks of the heavy object spawn position inside the room.",
        },
        "scene_entities": {
            "heavy_object": {
                "spawn_pos": object_spawn_pos,
                "goal_pos": object_goal_pos,
                "goal_region": target_zone,
                "control_mode": scene.get("control_mode", "external_mod_binding"),
                "description": "Summon and bind the heavy object with the custom lift mod, then pull it onto the target floor zone.",
            }
        },
        "players": {
            "player_a": {
                "role": "puller_a",
                "start_pos": a_start,
                "start_rotation": random_rotation(rng),
                "goal": {
                    "type": "cooperate_move_object",
                    "target_pos": object_goal_pos,
                    "target_region": target_zone,
                    "description": "Bind to the heavy object and cooperatively pull it from the source floor onto the target floor.",
                },
            },
            "player_b": {
                "role": "puller_b",
                "start_pos": b_start,
                "start_rotation": random_rotation(rng),
                "goal": {
                    "type": "cooperate_move_object",
                    "target_pos": object_goal_pos,
                    "target_region": target_zone,
                    "description": "Stay close to the heavy object, bind through the mod, and help pull it onto the target floor.",
                },
            },
        },
        "success_conditions": [
            {
                "type": "object_in_region",
                "entity": "heavy_object",
                "target_region": target_zone,
                "description": "The mod-controlled heavy object has been pulled from the source floor onto the target floor zone.",
            }
        ],
    }


def build_task(scene: Dict[str, Any], rng: random.Random, task_id: int) -> Dict[str, Any]:
    template = scene["task_template"]
    if template == "elevator_hold_door":
        return build_elevator_task(scene, rng, task_id)
    if template == "truck_reverse_guidance":
        return build_truck_task(scene, rng, task_id)
    if template == "heavy_object_dual_drag":
        return build_heavy_task(scene, rng, task_id)
    if template == "lift_time_dependency":
        return build_lift_task(scene, rng, task_id)
    raise ValueError(f"Unsupported task template: {template}")


def normalize_task_template(template: Optional[str]) -> Optional[str]:
    if template is None:
        return None
    canonical = TASK_TEMPLATE_ALIASES.get(template.strip().lower())
    if canonical is None:
        allowed = ", ".join(sorted(TASK_TEMPLATE_ALIASES))
        raise ValueError(f"Unknown task template/category '{template}'. Allowed values: {allowed}")
    return canonical


def filter_scenes(scenes: Sequence[Dict[str, Any]], template: Optional[str]) -> List[Dict[str, Any]]:
    if not template:
        return list(scenes)
    return [scene for scene in scenes if scene["task_template"] == template]


def main() -> None:
    global WALL_MARGIN
    parser = argparse.ArgumentParser(description="Generate randomized multi-agent tasks from scene_manifest.json.")
    parser.add_argument(
        "--manifest",
        default="generated/scene_manifest.json",
        help="Path to a generated scene manifest JSON.",
    )
    parser.add_argument(
        "--num-tasks",
        type=int,
        default=10,
        help="How many tasks to generate.",
    )
    parser.add_argument(
        "--task-template",
        default=None,
        help="Optional template filter: elevator_hold_door / truck_reverse_guidance / heavy_object_dual_drag / lift_time_dependency",
    )
    parser.add_argument(
        "--task-category",
        default=None,
        help="Alias of --task-template. Supports short names like: elevator / truck / heavy / lift",
    )
    parser.add_argument(
        "--tasks-per-scene",
        type=int,
        default=None,
        help="If set, generate this many tasks for each matched scene instead of sampling globally.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility.",
    )
    parser.add_argument(
        "--out",
        default="generated/generated_tasks.json",
        help="Output JSON path.",
    )
    parser.add_argument(
        "--wall-margin",
        type=int,
        default=WALL_MARGIN,
        help="Extra cells of clearance kept between spawn positions and walls (default: %(default)s).",
    )
    args = parser.parse_args()

    WALL_MARGIN = args.wall_margin

    base_dir = Path(__file__).resolve().parent
    manifest_path = (base_dir / args.manifest).resolve() if not Path(args.manifest).is_absolute() else Path(args.manifest)
    out_path = (base_dir / args.out).resolve() if not Path(args.out).is_absolute() else Path(args.out)

    manifest = load_manifest(manifest_path)
    requested_template = args.task_category or args.task_template
    normalized_template = normalize_task_template(requested_template)
    scenes = filter_scenes(manifest["scenes"], normalized_template)
    if not scenes:
        raise ValueError("No scenes matched the requested task template.")
    unsupported_templates = sorted({scene["task_template"] for scene in scenes if scene["task_template"] not in SUPPORTED_TASK_TEMPLATES})
    if unsupported_templates:
        unsupported = ", ".join(unsupported_templates)
        raise ValueError(
            f"Task generation is not implemented for these matched templates: {unsupported}"
        )
    if args.num_tasks < 1:
        raise ValueError("--num-tasks must be >= 1.")
    if args.tasks_per_scene is not None and args.tasks_per_scene < 1:
        raise ValueError("--tasks-per-scene must be >= 1.")

    rng = random.Random(args.seed)
    tasks: List[Dict[str, Any]] = []
    if args.tasks_per_scene is not None:
        task_id = 0
        for scene in scenes:
            for _ in range(args.tasks_per_scene):
                tasks.append(build_task(scene, rng, task_id))
                task_id += 1
    else:
        for task_id in range(args.num_tasks):
            scene = rng.choice(scenes)
            tasks.append(build_task(scene, rng, task_id))

    payload = {
        "manifest_path": relativize_path(manifest_path, base_dir),
        "namespace": manifest.get("namespace"),
        "task_count": len(tasks),
        "task_template_filter": normalized_template,
        "tasks_per_scene": args.tasks_per_scene,
        "seed": args.seed,
        "tasks": tasks,
    }
    write_json(out_path, payload)
    print(f"Generated {len(tasks)} tasks into {out_path}")


if __name__ == "__main__":
    main()
