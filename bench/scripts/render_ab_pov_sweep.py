#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
FONT_BOLD = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)


def episode_frames(level_dir: Path, episode_dir: Path) -> list[tuple[int, Path, Path]]:
    prompt_dir = episode_dir / "prompts"
    frames: list[tuple[int, Path, Path]] = []
    for agent_a in sorted(prompt_dir.glob("step_*_agent_a.png")):
        step = int(agent_a.stem.split("_")[1])
        agent_b = prompt_dir / f"step_{step:03d}_agent_b.png"
        if agent_b.is_file():
            frames.append((step, agent_a, agent_b))
    return frames


def render_pair(agent_a: Path, agent_b: Path, label: str) -> bytes:
    width, height = 1280, 410
    view_size = (620, 349)
    canvas = Image.new("RGB", (width, height), (16, 19, 25))
    left = Image.open(agent_a).convert("RGB").resize(view_size, Image.Resampling.BILINEAR)
    right = Image.open(agent_b).convert("RGB").resize(view_size, Image.Resampling.BILINEAR)
    canvas.paste(left, (20, 50))
    canvas.paste(right, (660, 50))
    draw = ImageDraw.Draw(canvas)
    draw.text((20, 12), label, font=FONT_BOLD, fill=(245, 248, 255))
    draw.rectangle((28, 58, 155, 92), fill=(10, 25, 43))
    draw.rectangle((668, 58, 795, 92), fill=(43, 25, 10))
    draw.text((40, 62), "Agent A", font=FONT, fill=(130, 202, 255))
    draw.text((680, 62), "Agent B", font=FONT, fill=(255, 197, 126))
    return canvas.tobytes()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--level-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fps", type=int, default=16)
    parser.add_argument("--max-frames", type=int, default=0)
    parser.add_argument("--episode-ids", default="")
    args = parser.parse_args()

    selected_episode_ids = {
        int(value.strip())
        for value in args.episode_ids.split(",")
        if value.strip()
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = "/home/azvm/miniconda3/envs/verl/bin/ffmpeg"
    command = [
        ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", "1280x410", "-r", str(args.fps), "-i", "-", "-an", "-c:v", "libx264",
        "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(args.output),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    written = 0
    try:
        for episode_dir in sorted(args.level_dir.glob("episode_*")):
            episode_id = int(episode_dir.name.split("_")[1])
            if selected_episode_ids and episode_id not in selected_episode_ids:
                continue
            result_path = episode_dir / "result.json"
            if not result_path.is_file():
                continue
            result = json.loads(result_path.read_text(encoding="utf-8"))
            status = "SUCCESS" if result.get("success") else ("ABNORMAL" if not result.get("ok") or result.get("discarded") else "FAIL")
            for step, agent_a, agent_b in episode_frames(args.level_dir, episode_dir):
                label = (
                    f"{args.level_dir.name.upper()} | Task {result.get('task_index')} | "
                    f"Repeat {result.get('repeat_index')} | Step {step} | {status}"
                )
                assert process.stdin is not None
                process.stdin.write(render_pair(agent_a, agent_b, label))
                written += 1
                if args.max_frames and written >= args.max_frames:
                    break
            if args.max_frames and written >= args.max_frames:
                break
    finally:
        if process.stdin is not None:
            process.stdin.close()
        returncode = process.wait()
    if returncode:
        raise SystemExit(returncode)
    print(f"frames={written} seconds={written / args.fps:.2f} output={args.output}")


if __name__ == "__main__":
    main()
