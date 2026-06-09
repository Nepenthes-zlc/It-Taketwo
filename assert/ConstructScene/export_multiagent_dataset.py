#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def build_agents(task):
    players = task.get("players", {})
    agents = []
    for default_name, key in (("Agent A", "player_a"), ("Agent B", "player_b")):
        player = players.get(key, {})
        goal = player.get("goal", {})
        agents.append(
            {
                "name": default_name,
                "agent_id": key,
                "role": player.get("role", key),
                "start_pos": player.get("start_pos"),
                "start_rotation": player.get("start_rotation"),
                "goal": goal.get("description") or goal.get("type"),
                "goal_spec": goal,
            }
        )
    return agents


def pick_target_region(task):
    for cond in task.get("success_conditions", []):
        target_region = cond.get("target_region")
        if target_region is not None:
            return target_region
    return None


def pick_goal_pos(task):
    player_b = task.get("players", {}).get("player_b", {})
    goal = player_b.get("goal", {})
    target_pos = goal.get("target_pos")
    if target_pos is not None:
        return target_pos

    target_region = goal.get("target_region")
    if isinstance(target_region, list) and len(target_region) >= 6:
        x1, y1, z1, x2, y2, z2 = target_region[:6]
        return [(x1 + x2) / 2.0, y1, (z1 + z2) / 2.0]
    return [0.0, 0.0, 0.0]


def build_row(task):
    agents = build_agents(task)
    player_a = task.get("players", {}).get("player_a", {})

    env_config = {
        "multi_agent": True,
        "task_type": "multiagent",
        "task_str": task.get("task_description", ""),
        "scene_id": task.get("scene_id"),
        "task_template": task.get("task_template"),
        "scene_setup_function": task.get("scene_setup_function"),
        "scene_clear_function": task.get("scene_clear_function"),
        "success_conditions": task.get("success_conditions", []),
        "target_region": pick_target_region(task),
        "agents": agents,
        # Preserve compatibility with older single-agent reset/reward code paths.
        "start_pos": player_a.get("start_pos", [0.0, 0.0, 0.0]),
        "start_rotation": player_a.get("start_rotation", [0.0, 0.0]),
        "goal_pos": pick_goal_pos(task),
    }

    optional_keys = (
        "control_mode",
        "source_zone",
        "target_zone",
        "object_spawn_pos",
        "object_goal_pos",
        "coordination_constraints",
        "scene_entities",
    )
    for key in optional_keys:
        if key in task:
            env_config[key] = task[key]

    return {
        "env_name": "MCMultiAgentSimulator",
        "env_config": env_config,
        "extra_info": {
            "index": task.get("id", 0),
            "task_id": task.get("id", 0),
            "scene_id": task.get("scene_id"),
        },
    }


def validate_rows(rows):
    if not rows:
        raise ValueError("No rows were generated from the input tasks.")

    required_env_keys = {
        "multi_agent",
        "task_str",
        "scene_setup_function",
        "scene_clear_function",
        "success_conditions",
        "agents",
        "start_pos",
        "start_rotation",
        "goal_pos",
    }

    sample = rows[0]
    if "env_config" not in sample:
        raise ValueError("Generated row is missing env_config.")
    if "extra_info" not in sample:
        raise ValueError("Generated row is missing extra_info.")

    missing = sorted(required_env_keys - set(sample["env_config"].keys()))
    if missing:
        raise ValueError(f"Generated env_config is missing keys: {missing}")

    if not isinstance(sample["env_config"]["agents"], list) or len(sample["env_config"]["agents"]) < 2:
        raise ValueError("Generated env_config.agents must contain at least two agents.")


def write_jsonl(rows, output_path):
    with output_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_parquet(rows, output_path):
    try:
        import pandas as pd
    except Exception as exc:
        raise RuntimeError(f"pandas is required for parquet export: {exc}") from exc

    try:
        import pyarrow  # noqa: F401
    except Exception as exc:
        raise RuntimeError(f"pyarrow is required for parquet export: {exc}") from exc

    df = pd.DataFrame(rows)
    df.to_parquet(output_path, index=False)
    return list(df.columns)


def main():
    parser = argparse.ArgumentParser(description="Export multi-agent RL dataset from generated scene tasks.")
    repo_root = Path(__file__).resolve().parents[1]
    parser.add_argument(
        "--input",
        default=str(repo_root / "ConstructScene" / "generated" / "generated_tasks.json"),
        help="Path to generated_tasks.json",
    )
    parser.add_argument(
        "--output-prefix",
        default=str(repo_root / "data" / "multiagent_scene"),
        help="Output prefix without suffix. Writes .jsonl by default and optionally .parquet.",
    )
    parser.add_argument(
        "--parquet-only",
        action="store_true",
        help="Only write parquet output.",
    )
    parser.add_argument(
        "--jsonl-only",
        action="store_true",
        help="Only write jsonl output.",
    )
    args = parser.parse_args()

    if args.parquet_only and args.jsonl_only:
        raise ValueError("--parquet-only and --jsonl-only cannot be used together.")

    input_path = Path(args.input)
    output_prefix = Path(args.output_prefix)
    output_prefix.parent.mkdir(parents=True, exist_ok=True)

    with input_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    tasks = payload.get("tasks", [])
    rows = [build_row(task) for task in tasks]
    validate_rows(rows)

    wrote_any = False
    if not args.parquet_only:
        jsonl_path = output_prefix.with_suffix(".jsonl")
        write_jsonl(rows, jsonl_path)
        print(f"[INFO] wrote jsonl: {jsonl_path}")
        wrote_any = True

    if not args.jsonl_only:
        parquet_path = output_prefix.with_suffix(".parquet")
        columns = write_parquet(rows, parquet_path)
        print(f"[INFO] wrote parquet: {parquet_path}")
        print(f"[INFO] parquet columns: {columns}")
        wrote_any = True

    if not wrote_any:
        raise RuntimeError("No output was written.")

    sample_env = rows[0]["env_config"]
    print(f"[INFO] rows: {len(rows)}")
    print(f"[INFO] sample scene_id: {sample_env.get('scene_id')}")
    print(f"[INFO] sample task_str: {sample_env.get('task_str')}")
    print(f"[INFO] sample agent count: {len(sample_env.get('agents', []))}")
    print(f"[INFO] sample setup function: {sample_env.get('scene_setup_function')}")
    print(f"[INFO] sample clear function: {sample_env.get('scene_clear_function')}")


if __name__ == "__main__":
    main()
