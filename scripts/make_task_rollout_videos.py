"""Concatenate all rollouts of each task into one video per task (100 videos).

Each task video plays its rollouts back-to-back. Between rollouts a separator
frame shows task id, rollout index, success/fail, and whether the spawn Y was
correct. Every frame is annotated with step / Y / Z / done.
"""
from __future__ import annotations
import argparse, glob, json, re, sys
from pathlib import Path
from collections import defaultdict

import imageio.v2 as imageio
from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRACE = PROJECT_ROOT / "runs/single_agent/pressure_plate/verl_rollouts/door_agentb_cpu_20260623_142948"
TASKS_JSON = PROJECT_ROOT / "assert/ConstructScene/generated/generated_tasks.json"
SPAWN_Y = -58.0  # all tasks define AgentB start Y = -58

W, H = 854, 480


def task_of(name):
    m = re.search(r"_task(\d+)_", name)
    return int(m.group(1)) if m else None


def load_rows(d):
    try:
        return [json.loads(l) for l in (d / "steps.jsonl").open() if l.strip()]
    except Exception:
        return []


def step_info(rows, step):
    for r in rows:
        if r.get("step") == step:
            p = (r.get("poses_after") or {}).get("AgentB", {}).get("pos")
            y = p[1] if isinstance(p, list) else None
            z = p[2] if isinstance(p, list) else None
            return y, z, r.get("done"), r.get("markers", {}).get("agent_b_within_elevator_door_1")
    return None, None, None, None


def separator(text_lines, color=(255, 255, 255)):
    im = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(im)
    y = H // 2 - 12 * len(text_lines)
    for ln in text_lines:
        d.text((30, y), ln, fill=color)
        y += 24
    return im


def annotate(path, rows, step):
    im = Image.open(path).convert("RGB")
    if im.size != (W, H):
        im = im.resize((W, H))
    d = ImageDraw.Draw(im)
    y, z, done, pad = step_info(rows, step)
    bad_y = (y is not None and abs(y - SPAWN_Y) > 1.0)
    line = f"step {step}"
    if y is not None:
        line += f"  Y={y:.0f} Z={z:.1f}  done={done} pad={pad}"
    d.rectangle([0, 0, 480, 28], fill=(0, 0, 0))
    d.text((6, 6), line, fill=(255, 120, 120) if bad_y else (255, 255, 0))
    if bad_y:
        d.rectangle([0, 28, 300, 50], fill=(120, 0, 0))
        d.text((6, 32), f"SPAWN MISLOCATED Y={y:.0f}", fill=(255, 255, 255))
    return im


def make_task_video(tid, dirs, out_path, fps=4, sep_hold=3):
    dirs = sorted(dirs, key=lambda d: d.name)
    n_succ = n_fail = n_badspawn = 0
    with imageio.get_writer(out_path, fps=fps, codec="libx264", quality=7,
                            macro_block_size=2) as w:
        for idx, d in enumerate(dirs, 1):
            rows = load_rows(d)
            if not rows:
                continue
            files = sorted(glob.glob(str(d / "agent_pov_frames" / "*.png")),
                           key=lambda f: int(re.search(r"step_(\d+)", f).group(1)))
            if not files:
                continue
            last = rows[-1]
            success = bool(last.get("done")) and last.get("binary_reward", 0) > 0
            p0 = (rows[0].get("poses_before") or {}).get("AgentB", {}).get("pos") or \
                 (rows[0].get("poses_after") or {}).get("AgentB", {}).get("pos")
            y0 = p0[1] if isinstance(p0, list) else None
            bad_spawn = (y0 is not None and abs(y0 - SPAWN_Y) > 1.0)
            if success:
                n_succ += 1
            else:
                n_fail += 1
            if bad_spawn:
                n_badspawn += 1
            inst = re.search(r"_instance(\d+)", d.name)
            sep = separator([
                f"task {tid}   rollout {idx}/{len(dirs)}",
                f"instance {inst.group(1) if inst else '?'}   steps {len(rows)}",
                f"{'SUCCESS' if success else 'FAIL'}" + ("   SPAWN BAD (Y=%.0f)" % y0 if bad_spawn else ""),
            ], color=(120, 255, 120) if success else (255, 120, 120))
            for _ in range(sep_hold):
                w.append_data(_np(sep))
            for f in files:
                step = int(re.search(r"step_(\d+)", f).group(1))
                w.append_data(_np(annotate(f, rows, step)))
    return len(dirs), n_succ, n_fail, n_badspawn


def _np(im):
    import numpy as np
    return np.asarray(im)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-dir", type=Path, default=DEFAULT_TRACE)
    ap.add_argument("--output-dir", type=Path,
                    default=PROJECT_ROOT / "runs/single_agent/pressure_plate/task_videos")
    ap.add_argument("--only-task", type=int, default=-1, help="render a single task id (for testing)")
    ap.add_argument("--fps", type=int, default=4)
    args = ap.parse_args()

    by_task = defaultdict(list)
    for d in glob.glob(str(args.trace_dir / "2026*_task*_instance*")):
        d = Path(d)
        t = task_of(d.name)
        if t is not None:
            by_task[t].append(d)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    tasks = sorted(by_task) if args.only_task < 0 else [args.only_task]
    for t in tasks:
        out = args.output_dir / f"task_{t:03d}.mp4"
        nr, ns, nf, nb = make_task_video(t, by_task[t], out, fps=args.fps)
        kb = out.stat().st_size // 1024 if out.exists() else 0
        print(f"task{t:3d}: {nr} rollouts (succ {ns}, fail {nf}, bad-spawn {nb}) -> {out.name} ({kb} KB)", flush=True)


if __name__ == "__main__":
    main()
