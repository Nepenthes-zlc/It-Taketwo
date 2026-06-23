#!/usr/bin/env python3
"""Render selected rollout episodes into ONE stitched video, with the FULL
(untruncated) LLM reasoning overlaid on each step.

Single-agent friendly: shows the controlled agent's first-person POV (top) and a
text panel (bottom) with step/action/reward/done plus the complete raw LLM output.
Episodes are concatenated into a single mp4 with a title card between each.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def load_steps(path: Path) -> list[dict[str, Any]]:
    out = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def episode_success(steps: list[dict[str, Any]]) -> bool:
    return any(s.get("done") for s in steps)


def load_font(size: int) -> ImageFont.ImageFont:
    for p in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ):
        if Path(p).is_file():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


POV_W, POV_H = 640, 360       # upscaled first-person view
PANEL_H = 440                 # room for LLM input (text) + LLM output
CANVAS_W = POV_W
CANVAS_H = POV_H + PANEL_H

FONT_HDR = load_font(20)
FONT_TXT = load_font(16)
FONT_BIG = load_font(30)


def open_pov(path: str | None) -> Image.Image:
    if path and Path(path).is_file():
        img = Image.open(path).convert("RGB")
    else:
        img = Image.new("RGB", (POV_W, POV_H), (15, 15, 15))
    return img.resize((POV_W, POV_H), Image.Resampling.NEAREST)


def controlled_agent(steps: list[dict[str, Any]]) -> str:
    for s in steps:
        aa = s.get("active_agents")
        if isinstance(aa, list) and aa:
            return aa[0]
    return "AgentA"


def reconstruct_input_text(step: dict[str, Any], agent: str) -> str:
    """Rebuild the state the LLM was given this step (the exact prompt text is not
    saved in the trace, so this summarizes the observation fields it was built from)."""
    pose = (step.get("poses_before") or {}).get(agent) or (step.get("poses_after") or {}).get(agent) or {}
    pos = pose.get("pos") or [0, 0, 0]
    yaw = pose.get("yaw", 0.0)
    pitch = pose.get("pitch", 0.0)
    m = step.get("markers") or {}
    if agent == "AgentB":
        task = "Reach the elevator door (within 1 block). The door is BLACK — find the black region in the image."
        dist = m.get("agent_b_to_elevator_door")
        reached = m.get("agent_b_within_elevator_door_1")
        goal = f"dist_to_door={dist:.1f}  reached={reached}" if dist is not None else f"reached={reached}"
    else:
        task = "Step onto the 3x3 pressure-plate region. The plate is BLACK — find the black tiles in the image."
        goal = f"plate_powered={m.get('pressure_plate_powered')}"
    return (
        f"{task}\n"
        f"your_pose: x={pos[0]:.1f} y={pos[1]:.1f} z={pos[2]:.1f}  yaw={yaw:.0f} pitch={pitch:.0f}\n"
        f"target_state: {goal}\n"
        f"[+ first-person image above]"
    )


def render_step(step: dict[str, Any], agent: str, title: str) -> Image.Image:
    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), (245, 245, 245))
    key = "agent_a" if agent == "AgentA" else "agent_b"
    # the IMAGE actually fed to the LLM (llm_input_frame); fall back to the raw POV
    img_path = (step.get("llm_input_frames") or {}).get(agent) or (step.get("agent_pov_frames") or {}).get(agent)
    canvas.paste(open_pov(img_path), (0, 0))

    draw = ImageDraw.Draw(canvas)
    dec = (step.get("agent_decisions") or {}).get(agent) or {}
    action = dec.get("action") or (step.get("actions") or {}).get(key) or "?"
    reason = dec.get("reason") or ""
    raw = dec.get("raw_response") or ""
    reward = float(step.get("reward") or 0.0)
    done = bool(step.get("done"))

    draw.rectangle((6, 6, 6 + 11 * len("LLM INPUT IMAGE") + 30, 30), fill=(0, 0, 0))
    draw.text((10, 9), f"LLM INPUT IMAGE ({agent})", fill=(255, 255, 255), font=FONT_HDR)

    y = POV_H + 6
    hdr = f"{title}  |  step {step.get('step')}  action={action}  reward={reward:.3f}  done={done}"
    draw.text((10, y), hdr, fill=(0, 0, 90), font=FONT_HDR)
    y += 26
    draw.line((8, y, CANVAS_W - 8, y), fill=(180, 180, 180))
    y += 5

    # ===== LLM INPUT (text) =====
    draw.text((10, y), "LLM INPUT (text):", fill=(0, 90, 0), font=FONT_TXT)
    y += 21
    for line in reconstruct_input_text(step, agent).split("\n"):
        for wl in textwrap.wrap(line, width=78) or [""]:
            if y > CANVAS_H - 18:
                break
            draw.text((14, y), wl, fill=(25, 60, 25), font=FONT_TXT)
            y += 19
    y += 6
    draw.line((8, y, CANVAS_W - 8, y), fill=(210, 210, 210))
    y += 5

    # ===== LLM OUTPUT (full, untruncated) =====
    full = raw.strip() if raw else f'{{"action":"{action}","reason":"{reason}"}}'
    draw.text((10, y), "LLM OUTPUT:", fill=(120, 0, 0), font=FONT_TXT)
    y += 21
    for line in textwrap.wrap(full, width=78) or [""]:
        if y > CANVAS_H - 16:
            break
        draw.text((14, y), line, fill=(20, 20, 20), font=FONT_TXT)
        y += 19
    return canvas




def title_card(text_lines: list[str], color: tuple[int, int, int]) -> Image.Image:
    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), color)
    draw = ImageDraw.Draw(canvas)
    y = CANVAS_H // 2 - 20 * len(text_lines)
    for ln in text_lines:
        draw.text((30, y), ln, fill=(255, 255, 255), font=FONT_BIG)
        y += 44
    return canvas


def to_bgr(img: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def find_ffmpeg() -> str | None:
    f = shutil.which("ffmpeg")
    if f:
        return f
    c = Path("/home/azvm/miniconda3/envs/verl/bin/ffmpeg")
    return str(c) if c.exists() else None


def transcode(src: Path, dst: Path) -> None:
    ff = find_ffmpeg()
    if not ff:
        src.replace(dst)
        return
    cmd = [ff, "-y", "-i", str(src), "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-profile:v", "baseline", "-level", "3.0", "-movflags", "+faststart", "-an", str(dst)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-1500:])
    src.unlink(missing_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-dir", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--n-success", type=int, default=3)
    ap.add_argument("--n-fail", type=int, default=3)
    ap.add_argument("--fps", type=float, default=1.5)
    ap.add_argument("--hold", type=int, default=3)
    args = ap.parse_args()

    eps = []
    for sp in sorted(args.trace_dir.glob("*/steps.jsonl"), key=lambda p: p.parent.name):
        steps = load_steps(sp)
        if not steps:
            continue
        # require POV frames present
        if not any((s.get("agent_pov_frames") or {}) for s in steps):
            continue
        eps.append((sp.parent.name, steps, episode_success(steps)))

    succ = [e for e in eps if e[2]][: args.n_success]
    fail = [e for e in eps if not e[2]][: args.n_fail]
    chosen = succ + fail
    if not chosen:
        raise SystemExit("no episodes with POV frames found")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(".tmp.mp4")
    writer = cv2.VideoWriter(str(tmp), cv2.VideoWriter_fourcc(*"mp4v"), args.fps, (CANVAS_W, CANVAS_H))
    if not writer.isOpened():
        raise SystemExit("cannot open video writer")

    try:
        for idx, (name, steps, ok) in enumerate(chosen, 1):
            agent = controlled_agent(steps)
            tag = "SUCCESS" if ok else "FAIL"
            task = name.split("_task")[-1].split("_")[0] if "_task" in name else "?"
            card = title_card(
                [f"Episode {idx}/{len(chosen)}  [{tag}]", f"task {task}", f"{agent}", f"{len(steps)} steps"],
                (20, 110, 40) if ok else (130, 30, 30),
            )
            for _ in range(args.hold + 2):
                writer.write(to_bgr(card))
            title = f"ep{idx} [{tag}] task{task}"
            for s in steps:
                frame = render_step(s, agent, title)
                arr = to_bgr(frame)
                for _ in range(max(1, args.hold)):
                    writer.write(arr)
    finally:
        writer.release()

    transcode(tmp, args.output)
    print(f"chosen episodes: {len(chosen)} ({len(succ)} success + {len(fail)} fail)")
    print(f"wrote: {args.output}")


if __name__ == "__main__":
    main()
