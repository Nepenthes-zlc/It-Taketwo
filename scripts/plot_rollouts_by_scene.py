#!/usr/bin/env python3
"""Top-down map of AgentB rollout trajectories grouped by scene (one subplot per scene).

Each subplot overlays, in local world coords (x horizontal, z vertical):
- pressure-plate region (green), door-cell region (red), 2xN approach pad / new target (blue)
- every rollout's AgentB path as a random-colored polyline with small circle nodes

Geometry mirrors mc_rollout/game_functions.py (kept inline so this runs under any
python with matplotlib, without importing the project).
"""
from __future__ import annotations

import argparse
import colorsys
import glob
import json
import math
import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TASKS_JSON = PROJECT_ROOT / "assert/ConstructScene/generated/generated_tasks.json"
SCENE_MANIFEST = PROJECT_ROOT / "assert/ConstructScene/generated/scene_manifest.json"
DEFAULT_TRACE = PROJECT_ROOT / "runs/single_agent/pressure_plate/verl_rollouts/door_agentb_full_20260622_134947"


def door_cell_region(reg):
    x0, y0, z0, x1, y1, z1 = [float(v) for v in reg[:6]]
    return [min(x0, x1), min(z0, z1), max(x0, x1), max(z0, z1)]  # xlo, zlo, xhi, zhi


def door_front_region(reg, b_start):
    x0, y0, z0, x1, y1, z1 = [float(v) for v in reg[:6]]
    xlo, xhi, zlo, zhi = min(x0, x1), max(x0, x1), min(z0, z1), max(z0, z1)
    if int(z0) == int(z1):  # door along x; approach along z
        dz = zlo
        if float(b_start[2]) <= dz:
            return [xlo, dz - 1.0, xhi, dz]
        return [xlo, dz, xhi, dz + 1.0]
    if int(x0) == int(x1):  # door along z; approach along x
        dx = xlo
        if float(b_start[0]) <= dx:
            return [dx - 1.0, zlo, dx, zhi]
        return [dx, zlo, dx + 1.0, zhi]
    return [xlo, zlo, xhi, zhi]


def rect_xywh(region_xzxz):
    """region as [xlo,zlo,xhi,zhi] (block-corner) -> Rectangle (x,z,w,h) covering full cells."""
    xlo, zlo, xhi, zhi = region_xzxz
    return (xlo, zlo, (xhi - xlo) + 1.0, (zhi - zlo) + 1.0)


def task_id_of(d):
    try:
        return int(os.path.basename(d).split("_task")[1].split("_")[0])
    except Exception:
        return None


def random_color(i, n):
    h = (i * 0.61803398875) % 1.0
    s = 0.55 + 0.35 * ((i % 3) / 2.0)
    v = 0.75 + 0.2 * ((i % 2))
    return colorsys.hsv_to_rgb(h, s, min(v, 1.0))


def agentb_path(rows):
    pts = []
    for r in rows:
        pose = (r.get("poses_after") or {}).get("AgentB") or (r.get("poses_before") or {}).get("AgentB") or {}
        pos = pose.get("pos")
        if isinstance(pos, list) and len(pos) >= 3:
            pts.append((float(pos[0]), float(pos[2])))
    return pts


def in_region(pt, reg_xzxz, half=0.3):
    x, z = pt
    xlo, zlo, xhi, zhi = reg_xzxz
    return (x + half) > xlo and (x - half) < (xhi + 1.0) and (z + half) > zlo and (z - half) < (zhi + 1.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-dir", type=Path, default=DEFAULT_TRACE)
    ap.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "runs/single_agent/pressure_plate/rollout_maps")
    ap.add_argument("--max-per-scene", type=int, default=0, help="0 = all")
    args = ap.parse_args()

    tj = json.loads(TASKS_JSON.read_text())
    TASK = {int(t["id"]): t for t in tj["tasks"]}
    manifest = {s["scene_id"]: s for s in json.loads(SCENE_MANIFEST.read_text()).get("scenes", [])}

    # group rollout dirs by scene
    dirs = sorted(glob.glob(str(args.trace_dir / "2026*_task*_instance*")))
    by_scene: dict[str, list[str]] = {}
    for d in dirs:
        t = TASK.get(task_id_of(d))
        if t is None:
            continue
        by_scene.setdefault(t["scene_id"], []).append(d)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    scenes = sorted(by_scene)
    written = []
    for scene in scenes:
        sdirs = by_scene[scene]
        # representative task for geometry (door/plate fixed per scene)
        t0 = TASK[task_id_of(sdirs[0])]
        plate_reg = t0["players"]["player_a"]["goal"]["target_region"]
        door_reg = t0["players"]["player_b"]["goal"]["target_region"]
        b_start0 = t0["players"]["player_b"]["start_pos"]
        plate_xzxz = [min(plate_reg[0], plate_reg[3]), min(plate_reg[2], plate_reg[5]),
                      max(plate_reg[0], plate_reg[3]), max(plate_reg[2], plate_reg[5])]
        cell_xzxz = door_cell_region(door_reg)
        front_xzxz = door_front_region(door_reg, b_start0)

        fig, ax = plt.subplots(figsize=(11, 11))

        # room walls + divider (from manifest)
        sm = manifest.get(scene)
        if sm:
            ox, oz = float(sm["origin"][0]), float(sm["origin"][2])
            rx, rz = float(sm["room_size"][0]), float(sm["room_size"][2])
            ax.add_patch(Rectangle((ox, oz), rx, rz, fill=False, edgecolor="0.35", lw=2.6, zorder=0, label="room wall"))
            # divider wall sits on the door line; door opening is the gap (door cells)
            dx0, dz0, dx1, dz1 = cell_xzxz_pre = door_cell_region(door_reg)
            if int(door_reg[2]) == int(door_reg[5]):  # divider runs along x at z = door line
                dz = float(door_reg[2])
                ax.plot([ox, dx0], [dz + 0.5, dz + 0.5], color="0.35", lw=3.0, zorder=0)
                ax.plot([dx1 + 1.0, ox + rx], [dz + 0.5, dz + 0.5], color="0.35", lw=3.0, zorder=0)
            else:  # divider runs along z at x = door line
                dx = float(door_reg[0])
                ax.plot([dx + 0.5, dx + 0.5], [oz, dz0], color="0.35", lw=3.0, zorder=0)
                ax.plot([dx + 0.5, dx + 0.5], [dz1 + 1.0, oz + rz], color="0.35", lw=3.0, zorder=0)

        # region patches
        px, pz, pw, ph = rect_xywh(plate_xzxz)
        ax.add_patch(Rectangle((px, pz), pw, ph, facecolor="#2ca02c", alpha=0.30, edgecolor="#1a661a", lw=1.6, zorder=1, label="pressure plate"))
        fx, fz, fw, fh = rect_xywh(front_xzxz)
        ax.add_patch(Rectangle((fx, fz), fw, fh, facecolor="#1f77b4", alpha=0.22, edgecolor="#11436b", lw=1.8, zorder=2, label="target pad (2xN)"))
        cx, cz, cw, ch = rect_xywh(cell_xzxz)
        ax.add_patch(Rectangle((cx, cz), cw, ch, facecolor="#d62728", alpha=0.45, edgecolor="#7a1416", lw=1.8, zorder=3, label="door cells"))

        # trajectories
        chosen = sdirs if args.max_per_scene <= 0 else sdirs[: args.max_per_scene]
        succ = 0
        drawn = 0
        for i, d in enumerate(chosen):
            p = os.path.join(d, "steps.jsonl")
            if not os.path.exists(p):
                continue
            rows = [json.loads(l) for l in open(p) if l.strip()]
            pts = agentb_path(rows)
            if not pts:
                continue
            drawn += 1
            if any(in_region(pt, front_xzxz) for pt in pts):
                succ += 1
            xs = [q[0] for q in pts]
            zs = [q[1] for q in pts]
            c = random_color(i, len(chosen))
            ax.plot(xs, zs, "-", color=c, lw=0.9, alpha=0.55, zorder=5)
            ax.plot(xs, zs, "o", color=c, ms=2.6, alpha=0.7, zorder=6)
            # start = hollow square, end = filled star, both edged for contrast
            ax.plot(xs[0], zs[0], "s", mfc="none", mec=c, mew=1.8, ms=9, zorder=8)
            ax.plot(xs[-1], zs[-1], "*", mfc=c, mec="black", mew=0.6, ms=15, zorder=9)

        # legend proxies for start/end
        ax.plot([], [], "s", mfc="none", mec="black", mew=1.8, ms=9, label="start")
        ax.plot([], [], "*", mfc="0.4", mec="black", mew=0.6, ms=15, label="end")

        ax.set_title(f"{scene}\n{drawn} rollouts · pad-hit (any step) {succ} ({100*succ/max(drawn,1):.0f}%)", fontsize=14)
        ax.set_xlabel("x", fontsize=12); ax.set_ylabel("z", fontsize=12)
        ax.set_aspect("equal", adjustable="box")

        # Minecraft block grid: one cell per block, lines on integer block edges
        if sm:
            gx0, gz0 = int(math.floor(ox)), int(math.floor(oz))
            gx1, gz1 = int(math.ceil(ox + rx)), int(math.ceil(oz + rz))
        else:
            gx0, gx1, gz0, gz1 = -1, 13, -1, 16
        ax.set_xlim(gx0 - 0.5, gx1 + 0.5)
        ax.set_ylim(gz0 - 0.5, gz1 + 0.5)
        ax.set_xticks(range(gx0, gx1 + 1))
        ax.set_yticks(range(gz0, gz1 + 1))
        ax.grid(True, which="major", ls="-", lw=0.5, color="0.85", alpha=0.9, zorder=-1)
        ax.tick_params(labelsize=8)
        ax.legend(loc="upper right", fontsize=10, framealpha=0.9, ncol=1)

        out = args.output_dir / f"{scene}.png"
        fig.tight_layout()
        fig.savefig(out, dpi=160)
        plt.close(fig)
        written.append((scene, drawn, succ))
        print(f"wrote {out}  ({drawn} rollouts, pad-hit {succ})")

    print(f"\n{len(written)} scene images -> {args.output_dir}")


if __name__ == "__main__":
    main()
