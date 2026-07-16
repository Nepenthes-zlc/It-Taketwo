#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import textwrap
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
BOLD_FONT_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(BOLD_FONT_PATH if bold else FONT_PATH), size)


def wrapped(text: Any, width: int, max_lines: int) -> list[str]:
    lines = textwrap.wrap(str(text or "(none)").replace("\n", " "), width=width) or ["(none)"]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:-3] + "..." if len(lines[-1]) > 3 else "..."
    return lines


def draw_lines(draw: ImageDraw.ImageDraw, x: int, y: int, lines: list[str], text_font: ImageFont.FreeTypeFont, color: tuple[int, int, int], spacing: int = 5) -> int:
    for line in lines:
        draw.text((x, y), line, font=text_font, fill=color)
        y += text_font.size + spacing
    return y


def open_image(path: Path, size: tuple[int, int]) -> Image.Image:
    return Image.open(path).convert("RGB").resize(size, Image.Resampling.LANCZOS)


def render_frame(run_dir: Path, episode_id: int, task_index: int, row: dict[str, Any], total_steps: int) -> Image.Image:
    step = int(row["step"])
    width, height = 1280, 900
    image_width, image_height = 620, 349
    canvas = Image.new("RGB", (width, height), (19, 23, 31))
    draw = ImageDraw.Draw(canvas)

    title_font = font(25, bold=True)
    label_font = font(21, bold=True)
    body_font = font(17)
    small_font = font(15)

    draw.text((24, 14), f"DuoAgent communication | episode {episode_id} | task {task_index} | step {step + 1}/{total_steps}", font=title_font, fill=(245, 248, 255))
    prompt_dir = run_dir / f"episode_{episode_id:04d}" / "prompts"
    a_image = open_image(prompt_dir / f"step_{step:03d}_agent_a.png", (image_width, image_height))
    b_image = open_image(prompt_dir / f"step_{step:03d}_agent_b.png", (image_width, image_height))
    canvas.paste(a_image, (20, 55))
    canvas.paste(b_image, (660, 55))
    draw.rectangle((20, 55, 640, 404), outline=(86, 156, 214), width=3)
    draw.rectangle((660, 55, 1280, 404), outline=(214, 154, 86), width=3)
    draw.rectangle((28, 63, 170, 98), fill=(8, 28, 48))
    draw.rectangle((668, 63, 810, 98), fill=(48, 28, 8))
    draw.text((38, 68), "AgentA POV", font=label_font, fill=(138, 205, 255))
    draw.text((678, 68), "AgentB POV", font=label_font, fill=(255, 202, 133))

    received = row.get("received_previous_messages") or {}
    sent = row.get("sent_messages") or {}
    decisions = row.get("decisions") or {}
    panel_y = 420
    panel_h = 455
    for index, (agent, teammate, x, accent) in enumerate((
        ("AgentA", "AgentB", 20, (86, 156, 214)),
        ("AgentB", "AgentA", 660, (214, 154, 86)),
    )):
        draw.rounded_rectangle((x, panel_y, x + 620, panel_y + panel_h), radius=12, fill=(29, 35, 46), outline=accent, width=2)
        decision = decisions.get(agent) or {}
        y = panel_y + 14
        draw.text((x + 16, y), agent, font=label_font, fill=accent)
        y += 34
        draw.text((x + 16, y), f"RECEIVED from {teammate} (previous round)", font=small_font, fill=(171, 181, 198))
        y += 24
        message = received.get(teammate) if received else None
        if not message:
            message = "No previous message (first round)."
        y = draw_lines(draw, x + 28, y, wrapped(message, 67, 3), body_font, (230, 235, 244)) + 8
        draw.line((x + 16, y, x + 604, y), fill=(62, 71, 88), width=1)
        y += 10
        action = decision.get("action") or "?"
        draw.text((x + 16, y), "ACTION", font=small_font, fill=(171, 181, 198))
        draw.rounded_rectangle((x + 102, y - 4, x + 250, y + 25), radius=7, fill=accent)
        draw.text((x + 115, y), str(action), font=small_font, fill=(10, 15, 21))
        y += 39
        draw.text((x + 16, y), "REASON", font=small_font, fill=(171, 181, 198))
        y += 24
        y = draw_lines(draw, x + 28, y, wrapped(decision.get("reason"), 67, 4), body_font, (230, 235, 244)) + 8
        draw.line((x + 16, y, x + 604, y), fill=(62, 71, 88), width=1)
        y += 10
        draw.text((x + 16, y), f"SENT to {teammate} (for next round)", font=small_font, fill=(171, 181, 198))
        y += 24
        draw_lines(draw, x + 28, y, wrapped(sent.get(agent), 67, 4), body_font, (238, 222, 174))

    draw.text((24, 880), "Each frame shows the exact images and communication used for that decision round.", font=small_font, fill=(143, 153, 170))
    return canvas


def render_episode(run_dir: Path, episode_id: int, fps: float, seconds_per_step: float, output_dir: Path) -> dict[str, Any]:
    episode_dir = run_dir / f"episode_{episode_id:04d}"
    result = json.loads((episode_dir / "result.json").read_text(encoding="utf-8"))
    rows = load_jsonl(episode_dir / "communication.jsonl")
    output = output_dir / f"episode_{episode_id:04d}_task_{result['task_index']}_duo_communication.mp4"
    output_dir.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(output), cv2.VideoWriter_fourcc(*"mp4v"), fps, (1280, 900))
    if not writer.isOpened():
        raise RuntimeError(f"cannot open video writer: {output}")
    hold = max(1, round(fps * seconds_per_step))
    preview_dir = output_dir / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    try:
        for index, row in enumerate(rows):
            frame = render_frame(run_dir, episode_id, int(result["task_index"]), row, len(rows))
            if index in {0, 1, len(rows) - 1}:
                frame.save(preview_dir / f"episode_{episode_id:04d}_step_{int(row['step']):03d}.png")
            bgr = cv2.cvtColor(np.asarray(frame), cv2.COLOR_RGB2BGR)
            for _ in range(hold):
                writer.write(bgr)
    finally:
        writer.release()
    return {
        "episode": episode_id,
        "task": result["task_index"],
        "steps": len(rows),
        "success": result["success"],
        "video": str(output),
        "seconds": round(len(rows) * hold / fps, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--fps", type=float, default=4.0)
    parser.add_argument("--seconds-per-step", type=float, default=2.5)
    parser.add_argument("--episode-ids", default="0-3", help="Comma-separated episode IDs and inclusive ranges.")
    args = parser.parse_args()
    episode_ids: list[int] = []
    for part in args.episode_ids.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = (int(value) for value in part.split("-", 1))
            episode_ids.extend(range(start, end + 1))
        else:
            episode_ids.append(int(part))
    results = [render_episode(args.run_dir, episode, args.fps, args.seconds_per_step, args.output_dir) for episode in episode_ids]
    (args.output_dir / "summary.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for result in results:
        print(result["video"])


if __name__ == "__main__":
    main()
