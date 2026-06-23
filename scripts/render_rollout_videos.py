#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Any

import cv2
from PIL import Image, ImageDraw, ImageFont


def load_steps(path: Path) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                steps.append(json.loads(line))
    return steps


def score_rollout(steps: list[dict[str, Any]]) -> tuple[float, float, bool]:
    if not steps:
        return 0.0, 0.0, False
    final = steps[-1]
    total = float(final.get("episode_reward") or 0.0)
    max_step = max(float(step.get("reward") or 0.0) for step in steps)
    success = any(float(step.get("binary_reward") or 0.0) > 0.0 or bool(step.get("done")) for step in steps)
    return total, max_step, success


def collect_rollouts(trace_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for steps_path in trace_dir.glob("*/steps.jsonl"):
        try:
            steps = load_steps(steps_path)
        except Exception:
            continue
        if not steps:
            continue
        total, max_step, success = score_rollout(steps)
        rows.append(
            {
                "dir": steps_path.parent,
                "steps": steps,
                "total_reward": total,
                "max_step_reward": max_step,
                "success": success,
                "num_steps": len(steps),
            }
        )
    return rows


def pick_rollouts(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    chosen: list[dict[str, Any]] = []
    successes = sorted([row for row in rows if row["success"]], key=lambda r: r["total_reward"], reverse=True)
    best = sorted(rows, key=lambda r: r["total_reward"], reverse=True)
    recent = sorted(rows, key=lambda r: r["dir"].name, reverse=True)
    for group in (successes, best, recent):
        for row in group:
            if row not in chosen:
                chosen.append(row)
            if len(chosen) >= limit:
                return chosen
    return chosen


def open_frame(path: str | None, size: tuple[int, int]) -> Image.Image:
    if path and Path(path).is_file():
        image = Image.open(path).convert("RGB")
    else:
        image = Image.new("RGB", size, (20, 20, 20))
    return image.resize(size, Image.Resampling.BILINEAR)


def wrap(text: str, width: int = 76, max_lines: int = 5) -> list[str]:
    lines = textwrap.wrap(str(text).replace("\n", " "), width=width)
    if len(lines) > max_lines:
        lines = lines[: max_lines - 1] + [lines[max_lines - 1][: max(0, width - 3)] + "..."]
    return lines


def draw_label(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font: ImageFont.ImageFont) -> None:
    x, y = xy
    draw.rectangle((x - 4, y - 3, x + len(text) * 8 + 8, y + 18), fill=(0, 0, 0))
    draw.text((x, y), text, fill=(255, 255, 255), font=font)


def render_step(step: dict[str, Any], title: str, frame_size: tuple[int, int], font: ImageFont.ImageFont) -> Image.Image:
    w, h = frame_size
    panel_h = 260
    canvas = Image.new("RGB", (w * 2, h + panel_h), (245, 245, 245))

    pov = step.get("agent_pov_frames") or {}
    a_frame = open_frame(pov.get("AgentA"), frame_size)
    b_frame = open_frame(pov.get("AgentB"), frame_size)
    canvas.paste(a_frame, (0, 0))
    canvas.paste(b_frame, (w, 0))
    draw = ImageDraw.Draw(canvas)
    draw_label(draw, (10, 10), "AgentA POV", font)
    draw_label(draw, (w + 10, 10), "AgentB POV", font)

    y = h + 12
    decisions = step.get("agent_decisions") or {}
    actions = step.get("actions") or {}
    markers = step.get("markers") or {}
    reward = float(step.get("reward") or 0.0)
    episode_reward = float(step.get("episode_reward") or 0.0)
    done = bool(step.get("done"))
    header = (
        f"{title} | step={step.get('step')} reward={reward:.4f} "
        f"episode={episode_reward:.4f} done={done} markers={markers}"
    )
    draw.text((12, y), header, fill=(0, 0, 0), font=font)
    y += 24

    for agent, key in (("AgentA", "agent_a"), ("AgentB", "agent_b")):
        decision = decisions.get(agent) or {}
        action = decision.get("action") or actions.get(key) or "?"
        reason = decision.get("reason") or decision.get("raw_response") or ""
        draw.text((12, y), f"{agent}: action={action}", fill=(0, 0, 0), font=font)
        y += 20
        for line in wrap(f"reason: {reason}", width=115, max_lines=7):
            draw.text((28, y), line, fill=(30, 30, 30), font=font)
            y += 18
        y += 4

    breakdown = step.get("reward_breakdown") or {}
    align = breakdown.get("target_alignment") or {}
    if align:
        for agent in ("AgentA", "AgentB"):
            item = align.get(agent) or {}
            msg = (
                f"{agent} target={item.get('target')} score={item.get('score')} "
                f"yaw_err={item.get('yaw_error')} pitch_err={item.get('pitch_error')}"
            )
            draw.text((12, y), msg, fill=(40, 40, 40), font=font)
            y += 18
    return canvas


def find_ffmpeg() -> str | None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    conda_ffmpeg = Path("/home/azvm/miniconda3/envs/verl/bin/ffmpeg")
    return str(conda_ffmpeg) if conda_ffmpeg.exists() else None


def transcode_h264(source: Path, output: Path) -> None:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        if source != output:
            source.replace(output)
        return
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(source),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-profile:v",
        "baseline",
        "-level",
        "3.0",
        "-movflags",
        "+faststart",
        "-an",
        str(output),
    ]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed for {source}: {proc.stderr[-2000:]}")
    if source != output:
        source.unlink(missing_ok=True)


def render_video(row: dict[str, Any], output: Path, fps: float, hold: int) -> None:
    steps = row["steps"]
    if not steps:
        return
    font = ImageFont.load_default()
    title = row["dir"].name
    frame_size = (512, 288)
    first = render_step(steps[0], title, frame_size, font)
    raw_output = output.with_name(output.stem + ".mp4v.tmp.mp4") if find_ffmpeg() else output
    writer = cv2.VideoWriter(
        str(raw_output),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        first.size,
    )
    if not writer.isOpened():
        raise RuntimeError(f"failed to open video writer for {raw_output}")
    try:
        for step in steps:
            frame = render_step(step, title, frame_size, font)
            arr = cv2.cvtColor(__import__("numpy").array(frame), cv2.COLOR_RGB2BGR)
            for _ in range(max(1, hold)):
                writer.write(arr)
    finally:
        writer.release()
    transcode_h264(raw_output, output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--fps", type=float, default=2.0)
    parser.add_argument("--hold", type=int, default=2)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows = collect_rollouts(args.trace_dir)
    chosen = pick_rollouts(rows, args.limit)
    summary = []
    for index, row in enumerate(chosen, 1):
        name = f"{index:02d}_{row['dir'].name}_reward_{row['total_reward']:.3f}.mp4"
        output = args.output_dir / name
        render_video(row, output, fps=args.fps, hold=args.hold)
        summary.append(
            {
                "video": str(output),
                "trace": str(row["dir"]),
                "num_steps": row["num_steps"],
                "total_reward": row["total_reward"],
                "max_step_reward": row["max_step_reward"],
                "success": row["success"],
            }
        )
        print(output)
    with (args.output_dir / "summary.json").open("w", encoding="utf-8") as file:
        json.dump(summary, file, indent=2)


if __name__ == "__main__":
    main()
