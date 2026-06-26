#!/usr/bin/env python3
"""Batch-generate multi-agent Minecraft scenes as mcfunction files."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple


DEFAULT_NAMESPACE = "multiagent_scene"
DEFAULT_PACK_NAME = "multiagent_scene_pack"
DEFAULT_PACK_FORMAT = 48
DEFAULT_SUPPORTED_FORMATS = [48, 81]
FUNCTION_DIR_NAMES = ("function", "functions")
DEFAULT_SCENE_GAP = 8

BLOCK_RGB = {
    "minecraft:white_concrete": (230, 235, 235),
    "minecraft:light_gray_concrete": (125, 125, 115),
    "minecraft:gray_concrete": (55, 58, 62),
    "minecraft:black_concrete": (8, 10, 15),
    "minecraft:red_concrete": (140, 30, 30),
    "minecraft:orange_concrete": (220, 105, 20),
    "minecraft:yellow_concrete": (240, 175, 35),
    "minecraft:lime_concrete": (95, 170, 25),
    "minecraft:green_concrete": (70, 90, 35),
    "minecraft:cyan_concrete": (20, 120, 135),
    "minecraft:blue_concrete": (45, 55, 160),
    "minecraft:purple_concrete": (100, 35, 150),
    "minecraft:magenta_concrete": (170, 50, 160),
    "minecraft:stone_pressure_plate": (125, 125, 125),
    "minecraft:polished_blackstone_pressure_plate": (25, 22, 28),
    "minecraft:birch_pressure_plate": (205, 185, 120),
    "minecraft:quartz_block": (235, 230, 220),
    "minecraft:gold_block": (245, 190, 35),
    "minecraft:lapis_block": (25, 65, 180),
}

HIGH_CONTRAST_ELEVATOR_PALETTES = [
    # Uniform light shell (floor + walls + divider + ceiling) with TWO distinct,
    # mutually-different target colors: a BLACK elevator door and a RED pressure
    # plate. All three groups (shell / door / plate) are different colors so the
    # door and plate are individually distinguishable in the agent POV.
    {
        "floor_block": "minecraft:white_concrete",
        "wall_block": "minecraft:white_concrete",
        "divider_block": "minecraft:white_concrete",
        "ceiling_block": "minecraft:white_concrete",
        "plate_pad_block": "minecraft:red_concrete",
        "pressure_plate_block": "minecraft:polished_blackstone_pressure_plate",
        "elevator_block": "minecraft:black_concrete",
    },
]



@dataclass(frozen=True)
class Vec3:
    x: int
    y: int
    z: int

    def shift(self, dx: int = 0, dy: int = 0, dz: int = 0) -> "Vec3":
        return Vec3(self.x + dx, self.y + dy, self.z + dz)

    def to_cmd(self) -> str:
        return f"{self.x} {self.y} {self.z}"


def fill_cmd(start: Vec3, end: Vec3, block: str) -> str:
    return f"fill {start.to_cmd()} {end.to_cmd()} {block}"


def setblock_cmd(pos: Vec3, block: str) -> str:
    return f"setblock {pos.to_cmd()} {block}"


def region_positions(min_pos: Vec3, max_pos: Vec3) -> List[Vec3]:
    return [
        Vec3(x, y, z)
        for x in range(min_pos.x, max_pos.x + 1)
        for y in range(min_pos.y, max_pos.y + 1)
        for z in range(min_pos.z, max_pos.z + 1)
    ]


def say_cmd(text: str) -> str:
    escaped = text.replace('"', '\\"')
    return f'tellraw @a {{"text":"{escaped}","color":"yellow"}}'


def sanitize_name(name: str) -> str:
    allowed = []
    for char in name.lower():
        if char.isalnum() or char in {"_", "-"}:
            allowed.append(char)
        else:
            allowed.append("_")
    return "".join(allowed).strip("_") or "scene"


def material_suffix(block: str) -> str:
    return sanitize_name(block.split(":")[-1])


def short_variant_token(value: str, limit: int = 10) -> str:
    parts = [part for part in sanitize_name(value).split("_") if part]
    if not parts:
        return "v"
    token = "".join(part[:2] for part in parts[: min(3, len(parts))])
    return token[:limit] or "v"


def make_variant_scene_id(base_id: str, variant_key: str, index: int) -> str:
    digest = hashlib.sha1(variant_key.encode("utf-8")).hexdigest()[:8]
    return f"{base_id}__v{index:02d}_{digest}"


def relativize_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_function_file(datapack_root: Path, namespace: str, relative_path: Path, content: str) -> None:
    for dir_name in FUNCTION_DIR_NAMES:
        write_text(datapack_root / "data" / namespace / dir_name / relative_path, content)


def load_specs(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError("Spec file must be a JSON list.")
    return data


def validate_size(size: Iterable[Any], key: str) -> Tuple[int, int, int]:
    values = list(size)
    if len(values) != 3 or not all(isinstance(v, int) for v in values):
        raise ValueError(f"{key} must be [int, int, int].")
    return values[0], values[1], values[2]


def validate_size_2(size: Iterable[Any], key: str) -> Tuple[int, int]:
    values = list(size)
    if len(values) != 2 or not all(isinstance(v, int) for v in values):
        raise ValueError(f"{key} must be [int, int].")
    return values[0], values[1]


def get_required_int(spec: Dict[str, Any], key: str) -> int:
    value = spec.get(key)
    if not isinstance(value, int):
        raise ValueError(f"{key} must be an int.")
    return value


def normalize_options(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and value and all(isinstance(item, str) for item in value):
        return value
    raise ValueError("Block option must be a string or a non-empty list of strings.")


def block_rgb(block: str) -> Tuple[int, int, int]:
    return BLOCK_RGB.get(str(block), (128, 128, 128))


def color_distance(left: str, right: str) -> float:
    a = block_rgb(left)
    b = block_rgb(right)
    return round(sum((a[i] - b[i]) ** 2 for i in range(3)) ** 0.5, 2)


def luminance(block: str) -> float:
    r, g, b = block_rgb(block)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def visual_contrast_summary(spec: Dict[str, Any]) -> Dict[str, Any]:
    floor = str(spec.get("floor_block", "minecraft:smooth_stone"))
    pad = str(spec.get("plate_pad_block", floor))
    plate = str(spec.get("pressure_plate_block", "minecraft:stone_pressure_plate"))
    wall = str(spec.get("divider_block", spec.get("wall_block", "minecraft:white_concrete")))
    door = str(spec.get("elevator_block", "minecraft:iron_block"))
    return {
        "floor_block": floor,
        "plate_pad_block": pad,
        "pressure_plate_block": plate,
        "wall_block": wall,
        "elevator_block": door,
        "plate_floor_distance": color_distance(plate, floor),
        "plate_pad_distance": color_distance(plate, pad),
        "pad_floor_distance": color_distance(pad, floor),
        "door_wall_distance": color_distance(door, wall),
        "door_plate_distance": color_distance(door, plate),
        "plate_pad_luminance_gap": round(abs(luminance(plate) - luminance(pad)), 2),
        "door_wall_luminance_gap": round(abs(luminance(door) - luminance(wall)), 2),
    }


def apply_high_contrast_elevator_palette(spec: Dict[str, Any]) -> Dict[str, Any]:
    if str(spec.get("task_template", "elevator_hold_door")) != "elevator_hold_door":
        return dict(spec)
    if spec.get("preserve_materials") or spec.get("auto_contrast_materials") is False:
        return dict(spec)

    item = dict(spec)
    scene_id = sanitize_name(str(item.get("id", "scene")))
    digest = int(hashlib.sha1(scene_id.encode("utf-8")).hexdigest()[:8], 16)
    palette = HIGH_CONTRAST_ELEVATOR_PALETTES[digest % len(HIGH_CONTRAST_ELEVATOR_PALETTES)]
    item.update(palette)
    item["auto_contrast_materials"] = True
    item["visual_contrast"] = visual_contrast_summary(item)
    original_notes = str(item.get("notes", "")).strip()
    contrast_note = (
        "Auto high-contrast materials: pressure plate/pad/floor and elevator door/wall colors are separated for VLM visibility."
    )
    item["notes"] = f"{original_notes} {contrast_note}".strip()
    return item


def expand_specs(specs: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    expanded: List[Dict[str, Any]] = []

    for spec in specs:
        option_lists: List[List[str]] = []
        present_keys: List[str] = []
        for key, value in spec.items():
            if not key.endswith("_block"):
                continue
            if isinstance(value, str):
                continue
            if isinstance(value, list) and value and all(isinstance(item, str) for item in value):
                present_keys.append(key)
                option_lists.append(value)

        if not present_keys:
            expanded.append(dict(spec))
            continue

        base_id = sanitize_name(str(spec.get("id", "scene")))
        for index, combo in enumerate(itertools.product(*option_lists), start=1):
            item = dict(spec)
            variant_parts = []
            variant_options: Dict[str, str] = {}
            for key, value in zip(present_keys, combo):
                item[key] = value
                short_key = key.replace("_block", "")
                variant_parts.append(f"{short_key}={material_suffix(value)}")
                variant_options[short_key] = value
            variant_key = "|".join(variant_parts)
            item["id"] = make_variant_scene_id(base_id, variant_key, index)
            item["variant_of"] = spec.get("id", base_id)
            item["variant_index"] = index
            item["variant_key"] = variant_key
            item["variant_label"] = short_variant_token(variant_key)
            item["variant_options"] = variant_options
            expanded.append(item)

    return expanded


def layout_specs_non_overlapping(specs: Sequence[Dict[str, Any]], gap: int = DEFAULT_SCENE_GAP) -> List[Dict[str, Any]]:
    if gap < 0:
        raise ValueError("scene gap must be >= 0.")

    laid_out: List[Dict[str, Any]] = []
    cursor_x: int | None = None

    for spec in specs:
        item = dict(spec)
        origin_values = item.get("origin")
        room_values = item.get("room_size")
        if origin_values is None or room_values is None:
            raise ValueError("Each spec must include origin and room_size before layout.")

        ox, oy, oz = validate_size(origin_values, "origin")
        width, _, _ = validate_size(room_values, "room_size")
        if cursor_x is None:
            cursor_x = ox
        shift_x = cursor_x - ox
        item["origin"] = [cursor_x, oy, oz]
        command_block_base = item.get("command_block_base")
        if command_block_base is not None:
            cbx, cby, cbz = validate_size(command_block_base, "command_block_base")
            item["command_block_base"] = [cbx + shift_x, cby, cbz]
        laid_out.append(item)
        cursor_x += width + gap

    return laid_out


def fill_outline(min_pos: Vec3, max_pos: Vec3, block: str) -> List[str]:
    return [
        fill_cmd(Vec3(min_pos.x, min_pos.y, min_pos.z), Vec3(max_pos.x, min_pos.y, max_pos.z), block),
        fill_cmd(Vec3(min_pos.x, max_pos.y, min_pos.z), Vec3(max_pos.x, max_pos.y, max_pos.z), block),
        fill_cmd(Vec3(min_pos.x, min_pos.y, min_pos.z), Vec3(min_pos.x, max_pos.y, max_pos.z), block),
        fill_cmd(Vec3(max_pos.x, min_pos.y, min_pos.z), Vec3(max_pos.x, max_pos.y, max_pos.z), block),
        fill_cmd(Vec3(min_pos.x, min_pos.y, min_pos.z), Vec3(max_pos.x, max_pos.y, min_pos.z), block),
        fill_cmd(Vec3(min_pos.x, min_pos.y, max_pos.z), Vec3(max_pos.x, max_pos.y, max_pos.z), block),
    ]


def fill_plane_outline(min_pos: Vec3, max_pos: Vec3, block: str) -> List[str]:
    if min_pos.y != max_pos.y:
        raise ValueError("fill_plane_outline requires positions on the same Y plane.")
    if min_pos.x > max_pos.x or min_pos.z > max_pos.z:
        raise ValueError("fill_plane_outline requires min_pos <= max_pos.")
    if min_pos.x == max_pos.x or min_pos.z == max_pos.z:
        return [fill_cmd(min_pos, max_pos, block)]
    return [
        fill_cmd(Vec3(min_pos.x, min_pos.y, min_pos.z), Vec3(max_pos.x, max_pos.y, min_pos.z), block),
        fill_cmd(Vec3(min_pos.x, min_pos.y, max_pos.z), Vec3(max_pos.x, max_pos.y, max_pos.z), block),
        fill_cmd(Vec3(min_pos.x, min_pos.y, min_pos.z + 1), Vec3(min_pos.x, max_pos.y, max_pos.z - 1), block),
        fill_cmd(Vec3(max_pos.x, min_pos.y, min_pos.z + 1), Vec3(max_pos.x, max_pos.y, max_pos.z - 1), block),
    ]


def default_command_base(ox: int, y1: int, oz: int) -> Vec3:
    return Vec3(ox + 1, y1 - 1, oz + 1)


def prepare_common(spec: Dict[str, Any]) -> Dict[str, Any]:
    scene_id = sanitize_name(str(spec.get("id", "scene")))
    origin_values = spec.get("origin")
    room_values = spec.get("room_size")
    if origin_values is None or room_values is None:
        raise ValueError(f"{scene_id}: missing origin or room_size.")

    ox, oy, oz = validate_size(origin_values, "origin")
    width, height, depth = validate_size(room_values, "room_size")
    if width < 7 or height < 5 or depth < 7:
        raise ValueError(f"{scene_id}: room_size is too small.")

    x1 = ox + width - 1
    y1 = oy + height - 1
    z1 = oz + depth - 1

    floor_block = str(spec.get("floor_block", "minecraft:smooth_stone"))
    wall_block = str(spec.get("wall_block", "minecraft:white_concrete"))
    ceiling_block = str(spec.get("ceiling_block", wall_block))
    light_block = str(spec.get("ceiling_light_block", "minecraft:glowstone"))
    light_mode = str(
        spec.get(
            "ceiling_light_mode",
            "inner_ring_spotlight" if spec.get("task_template") == "elevator_hold_door" else "panel",
        )
    ).lower()
    spotlight_block = str(spec.get("ceiling_spotlight_block", light_block))
    notes = str(spec.get("notes", "")).strip()
    variant_of = spec.get("variant_of")
    variant_index = spec.get("variant_index")
    variant_key = str(spec.get("variant_key", "")).strip()
    variant_label = str(spec.get("variant_label", "")).strip()
    variant_options = spec.get("variant_options")

    command_block_base = spec.get("command_block_base")
    if command_block_base is None:
        command_base = default_command_base(ox, y1, oz)
    else:
        cbx, cby, cbz = validate_size(command_block_base, "command_block_base")
        command_base = Vec3(cbx, cby, cbz)

    if not (ox < command_base.x < x1 and oy < command_base.y < y1 and oz < command_base.z < z1):
        raise ValueError(f"{scene_id}: command_block_base must be inside the room shell.")

    light_size_raw = spec.get("ceiling_light_size", [1, 1])
    spotlight_inset = get_required_int(spec, "ceiling_spotlight_inset") if "ceiling_spotlight_inset" in spec else 1
    light_size_x, light_size_z = validate_size_2(light_size_raw, "ceiling_light_size")
    if light_size_x < 1 or light_size_z < 1:
        raise ValueError(f"{scene_id}: ceiling_light_size values must be >= 1.")

    light_size_x = max(light_size_x, 3) if light_mode == "inner_ring_spotlight" else light_size_x
    light_size_z = max(light_size_z, 3) if light_mode == "inner_ring_spotlight" else light_size_z

    light_x0 = ox + (width - light_size_x) // 2
    light_z0 = oz + (depth - light_size_z) // 2
    light_x1 = light_x0 + light_size_x - 1
    light_z1 = light_z0 + light_size_z - 1
    if light_x0 <= ox or light_x1 >= x1 or light_z0 <= oz or light_z1 >= z1:
        raise ValueError(f"{scene_id}: ceiling_light_size is too large for this room.")

    light_min = Vec3(light_x0, y1, light_z0)
    light_max = Vec3(light_x1, y1, light_z1)
    inner_light_min = Vec3(light_x0, y1, light_z0)
    inner_light_max = Vec3(light_x1, y1, light_z1)
    spotlight_ring_min = Vec3(ox + spotlight_inset, y1, oz + spotlight_inset)
    spotlight_ring_max = Vec3(x1 - spotlight_inset, y1, z1 - spotlight_inset)
    if light_mode == "inner_ring_spotlight":
        if spotlight_ring_min.x > spotlight_ring_max.x or spotlight_ring_min.z > spotlight_ring_max.z:
            raise ValueError(f"{scene_id}: ceiling_spotlight_inset is too large for this room.")

    base_setup = [
        f"# Scene: {scene_id}",
        "# Auto-generated by multiagent/scene/generate_scenes.py",
    ]
    if notes:
        base_setup.append(f"# Notes: {notes}")
    base_setup.extend(
        [
            fill_cmd(Vec3(ox, oy, oz), Vec3(x1, oy, z1), floor_block),
            fill_cmd(Vec3(ox, oy + 1, oz), Vec3(x1, y1 - 1, z1), wall_block),
            fill_cmd(Vec3(ox + 1, oy + 1, oz + 1), Vec3(x1 - 1, y1 - 1, z1 - 1), "minecraft:air"),
            fill_cmd(Vec3(ox, y1, oz), Vec3(x1, y1, z1), ceiling_block),
        ]
    )
    if light_mode == "inner_ring_spotlight":
        base_setup.extend(fill_plane_outline(spotlight_ring_min, spotlight_ring_max, spotlight_block))
    else:
        base_setup.append(fill_cmd(light_min, light_max, light_block))

    clear_lines = [
        f"# Clear scene: {scene_id}",
        fill_cmd(Vec3(ox, oy, oz), Vec3(x1, y1, z1), "minecraft:air"),
    ]

    return {
        "scene_id": scene_id,
        "origin": Vec3(ox, oy, oz),
        "room_size": [width, height, depth],
        "bounds_max": Vec3(x1, y1, z1),
        "floor_block": floor_block,
        "wall_block": wall_block,
        "ceiling_block": ceiling_block,
        "light_block": light_block,
        "light_mode": light_mode,
        "spotlight_block": spotlight_block,
        "light_region": [light_min.x, light_min.y, light_min.z, light_max.x, light_max.y, light_max.z],
        "inner_light_region": [
            inner_light_min.x,
            inner_light_min.y,
            inner_light_min.z,
            inner_light_max.x,
            inner_light_max.y,
            inner_light_max.z,
        ],
        "spotlight_ring_region": [
            spotlight_ring_min.x,
            spotlight_ring_min.y,
            spotlight_ring_min.z,
            spotlight_ring_max.x,
            spotlight_ring_max.y,
            spotlight_ring_max.z,
        ],
        "command_base": command_base,
        "setup_lines": base_setup,
        "clear_lines": clear_lines,
        "notes": notes,
        "variant_of": variant_of,
        "variant_index": variant_index,
        "variant_key": variant_key,
        "variant_label": variant_label,
        "variant_options": variant_options if isinstance(variant_options, dict) else None,
        "spec": spec,
    }


def finalize_scene(
    common: Dict[str, Any],
    namespace: str,
    task_template: str,
    setup_lines: List[str],
    place_command_blocks_lines: List[str],
    tick_lines: List[str],
    clear_lines: List[str],
    extras: Dict[str, Any],
) -> Dict[str, Any]:
    scene_id = common["scene_id"]
    summary = {
        "scene_id": scene_id,
        "variant_of": common["variant_of"],
        "variant_index": common["variant_index"],
        "variant_label": common["variant_label"],
        "variant_key": common["variant_key"],
        "variant_options": common["variant_options"],
        "namespace": namespace,
        "task_template": task_template,
        "origin": [common["origin"].x, common["origin"].y, common["origin"].z],
        "room_size": common["room_size"],
        "command_block_base": [
            common["command_base"].x,
            common["command_base"].y,
            common["command_base"].z,
        ],
        "ceiling_light_region": common["light_region"],
        "ceiling_light_block": common["light_block"],
        "ceiling_light_mode": common["light_mode"],
        "ceiling_inner_light_region": common["inner_light_region"],
        "ceiling_spotlight_ring_region": common["spotlight_ring_region"],
        "ceiling_spotlight_block": common["spotlight_block"],
        "setup_function": f"{namespace}:{scene_id}/setup",
        "place_command_blocks_function": f"{namespace}:{scene_id}/place_command_blocks",
        "tick_function": f"{namespace}:{scene_id}/tick",
        "clear_function": f"{namespace}:{scene_id}/clear",
    }
    summary.update(extras)

    return {
        "scene_id": scene_id,
        "setup": "\n".join(setup_lines) + "\n",
        "place_command_blocks": "\n".join(place_command_blocks_lines) + "\n",
        "tick": "\n".join(tick_lines) + "\n",
        "clear": "\n".join(clear_lines) + "\n",
        "summary": summary,
    }


def build_elevator_scene(spec: Dict[str, Any], namespace: str) -> Dict[str, Any]:
    spec = apply_high_contrast_elevator_palette(spec)
    common = prepare_common(spec)
    scene_id = common["scene_id"]
    ox, oy, oz = common["origin"].x, common["origin"].y, common["origin"].z
    x1, y1, z1 = common["bounds_max"].x, common["bounds_max"].y, common["bounds_max"].z
    width, height, depth = common["room_size"]

    divider_block = str(spec.get("divider_block", common["wall_block"]))
    elevator_block = str(spec.get("elevator_block", "minecraft:iron_block"))
    plate_block = str(spec.get("pressure_plate_block", "minecraft:stone_pressure_plate"))
    plate_state = str(spec.get("pressure_plate_active_state", "powered=true"))
    divider_axis = str(spec.get("divider_axis", "z")).lower()
    if divider_axis not in {"x", "z"}:
        raise ValueError(f"{scene_id}: divider_axis must be 'x' or 'z'.")

    door_width = get_required_int(spec, "door_width")
    door_height = get_required_int(spec, "door_height")
    plate_offset = get_required_int(spec, "plate_offset")
    door_lateral_offset = int(spec.get("door_lateral_offset", 0))
    plate_lateral_offset = int(spec.get("plate_lateral_offset", 0))
    pressure_plate_size = int(spec.get("pressure_plate_size", 3))
    if pressure_plate_size < 1 or pressure_plate_size % 2 != 1:
        raise ValueError(f"{scene_id}: pressure_plate_size must be a positive odd integer.")
    plate_radius = pressure_plate_size // 2

    if divider_axis == "z":
        divider_coord = oz + depth // 2
        door_center_x = ox + width // 2 + door_lateral_offset
        door_x0 = door_center_x - door_width // 2
        door_x1 = door_x0 + door_width - 1
        door_min = Vec3(door_x0, oy + 1, divider_coord)
        door_max = Vec3(door_x1, oy + door_height, divider_coord)
        divider_start = Vec3(ox + 1, oy + 1, divider_coord)
        divider_end = Vec3(x1 - 1, y1 - 1, divider_coord)
        plate_pos = Vec3(ox + width // 2 + plate_lateral_offset, oy + 1, divider_coord - plate_offset)
        plate_min = Vec3(plate_pos.x - plate_radius, plate_pos.y, plate_pos.z - plate_radius)
        plate_max = Vec3(plate_pos.x + plate_radius, plate_pos.y, plate_pos.z + plate_radius)
        if door_x0 <= ox or door_x1 >= x1:
            raise ValueError(f"{scene_id}: elevator door is outside the room wall.")
        if plate_min.x <= ox or plate_max.x >= x1 or plate_min.z <= oz or plate_max.z >= divider_coord:
            raise ValueError(f"{scene_id}: pressure plate region is outside the first room.")
        if divider_coord - plate_max.z < 1:
            raise ValueError(f"{scene_id}: pressure plate region must be at least 1 block away from the elevator door.")
    else:
        divider_coord = ox + width // 2
        door_center_z = oz + depth // 2 + door_lateral_offset
        door_z0 = door_center_z - door_width // 2
        door_z1 = door_z0 + door_width - 1
        door_min = Vec3(divider_coord, oy + 1, door_z0)
        door_max = Vec3(divider_coord, oy + door_height, door_z1)
        divider_start = Vec3(divider_coord, oy + 1, oz + 1)
        divider_end = Vec3(divider_coord, y1 - 1, z1 - 1)
        plate_pos = Vec3(divider_coord - plate_offset, oy + 1, oz + depth // 2 + plate_lateral_offset)
        plate_min = Vec3(plate_pos.x - plate_radius, plate_pos.y, plate_pos.z - plate_radius)
        plate_max = Vec3(plate_pos.x + plate_radius, plate_pos.y, plate_pos.z + plate_radius)
        if door_z0 <= oz or door_z1 >= z1:
            raise ValueError(f"{scene_id}: elevator door is outside the room wall.")
        if plate_min.x <= ox or plate_min.z <= oz or plate_max.z >= z1 or plate_max.x >= divider_coord:
            raise ValueError(f"{scene_id}: pressure plate region is outside the first room.")
        if divider_coord - plate_max.x < 1:
            raise ValueError(f"{scene_id}: pressure plate region must be at least 1 block away from the elevator door.")

    if door_height >= height - 1:
        raise ValueError(f"{scene_id}: door_height is too large for room height.")

    plate_positions = region_positions(plate_min, plate_max)
    plate_pad_block = str(spec.get("plate_pad_block", common["floor_block"]))
    pad_min = Vec3(max(ox + 1, plate_min.x - 1), plate_pos.y - 1, max(oz + 1, plate_min.z - 1))
    pad_max = Vec3(min(x1 - 1, plate_max.x + 1), plate_pos.y - 1, min(z1 - 1, plate_max.z + 1))

    setup_lines = list(common["setup_lines"])
    setup_lines.extend(
        [
            fill_cmd(divider_start, divider_end, divider_block),
            fill_cmd(door_min, door_max, elevator_block),
            fill_cmd(pad_min, pad_max, plate_pad_block),
            *[setblock_cmd(pos, plate_block) for pos in plate_positions],
            "",
            "# Command blocks that keep the elevator door open while the plate is pressed.",
            f"function {namespace}:{scene_id}/place_command_blocks",
        ]
    )

    active_plate_block = f"{plate_block}[{plate_state}]"
    open_cmd = fill_cmd(door_min, door_max, "minecraft:air")
    close_cmd = fill_cmd(door_min, door_max, elevator_block)
    close_condition = " ".join(f"unless block {pos.to_cmd()} {active_plate_block}" for pos in plate_positions)
    command_base = common["command_base"]
    open_command_lines = [
        (
            f'setblock {command_base.shift(dx=index).to_cmd()} minecraft:repeating_command_block[facing=east]'
            f'{{auto:1b,Command:"execute if block {pos.to_cmd()} {active_plate_block} run {open_cmd}"}}'
        )
        for index, pos in enumerate(plate_positions)
    ]
    close_command_line = (
        f'setblock {command_base.shift(dx=len(plate_positions)).to_cmd()} minecraft:repeating_command_block[facing=east]'
        f'{{auto:1b,Command:"execute {close_condition} run {close_cmd}"}}'
    )
    place_command_blocks_lines = [
        f"# Place command blocks for scene: {scene_id}",
        *open_command_lines,
        close_command_line,
    ]
    tick_lines = [
        f"# Tick logic for scene: {scene_id}",
        *[f"execute if block {pos.to_cmd()} {active_plate_block} run {open_cmd}" for pos in plate_positions],
        f"execute {close_condition} run {close_cmd}",
    ]
    clear_lines = list(common["clear_lines"])
    clear_lines.append(fill_cmd(command_base, command_base.shift(dx=len(plate_positions)), "minecraft:air"))

    return finalize_scene(
        common,
        namespace,
        "elevator_hold_door",
        setup_lines,
        place_command_blocks_lines,
        tick_lines,
        clear_lines,
        {
            "divider_axis": divider_axis,
            "door_lateral_offset": door_lateral_offset,
            "plate_lateral_offset": plate_lateral_offset,
            "plate_offset": plate_offset,
            "pressure_plate_size": pressure_plate_size,
            "door_region": [door_min.x, door_min.y, door_min.z, door_max.x, door_max.y, door_max.z],
            "pressure_plate_pos": [plate_pos.x, plate_pos.y, plate_pos.z],
            "pressure_plate_region": [plate_min.x, plate_min.y, plate_min.z, plate_max.x, plate_max.y, plate_max.z],
            "pressure_plate_positions": [[pos.x, pos.y, pos.z] for pos in plate_positions],
            "pressure_plate_block": plate_block,
            "plate_pad_block": plate_pad_block,
            "plate_pad_region": [pad_min.x, pad_min.y, pad_min.z, pad_max.x, pad_max.y, pad_max.z],
            "floor_block": common["floor_block"],
            "wall_block": common["wall_block"],
            "divider_block": divider_block,
            "elevator_block": elevator_block,
            "visual_contrast": visual_contrast_summary(spec),
        },
    )


def build_middle_wall_opening_scene(spec: Dict[str, Any], namespace: str) -> Dict[str, Any]:
    common = prepare_common(spec)
    scene_id = common["scene_id"]
    ox, oy, oz = common["origin"].x, common["origin"].y, common["origin"].z
    x1, y1, z1 = common["bounds_max"].x, common["bounds_max"].y, common["bounds_max"].z
    width, height, depth = common["room_size"]

    divider_block = str(spec.get("divider_block", common["wall_block"]))
    divider_axis = str(spec.get("divider_axis", "z")).lower()
    if divider_axis not in {"x", "z"}:
        raise ValueError(f"{scene_id}: divider_axis must be 'x' or 'z'.")

    door_width = get_required_int(spec, "door_width")
    door_height = get_required_int(spec, "door_height")
    if door_height >= height - 1:
        raise ValueError(f"{scene_id}: door_height is too large for room height.")

    if divider_axis == "z":
        divider_coord = oz + depth // 2
        door_x0 = ox + (width - door_width) // 2
        door_x1 = door_x0 + door_width - 1
        divider_start = Vec3(ox + 1, oy + 1, divider_coord)
        divider_end = Vec3(x1 - 1, y1 - 1, divider_coord)
        door_min = Vec3(door_x0, oy + 1, divider_coord)
        door_max = Vec3(door_x1, oy + door_height, divider_coord)
    else:
        divider_coord = ox + width // 2
        door_z0 = oz + (depth - door_width) // 2
        door_z1 = door_z0 + door_width - 1
        divider_start = Vec3(divider_coord, oy + 1, oz + 1)
        divider_end = Vec3(divider_coord, y1 - 1, z1 - 1)
        door_min = Vec3(divider_coord, oy + 1, door_z0)
        door_max = Vec3(divider_coord, oy + door_height, door_z1)

    setup_lines = list(common["setup_lines"])
    setup_lines.extend(
        [
            fill_cmd(divider_start, divider_end, divider_block),
            fill_cmd(door_min, door_max, "minecraft:air"),
        ]
    )

    place_command_blocks_lines = [
        f"# No command blocks are needed for scene: {scene_id}",
    ]
    tick_lines = [
        f"# No tick logic is needed for scene: {scene_id}",
    ]
    clear_lines = list(common["clear_lines"])

    return finalize_scene(
        common,
        namespace,
        "middle_wall_opening",
        setup_lines,
        place_command_blocks_lines,
        tick_lines,
        clear_lines,
        {
            "divider_axis": divider_axis,
            "divider_region": [
                divider_start.x,
                divider_start.y,
                divider_start.z,
                divider_end.x,
                divider_end.y,
                divider_end.z,
            ],
            "door_region": [door_min.x, door_min.y, door_min.z, door_max.x, door_max.y, door_max.z],
        },
    )


def build_reverse_parking_opening_scene(spec: Dict[str, Any], namespace: str) -> Dict[str, Any]:
    common = prepare_common(spec)
    scene_id = common["scene_id"]
    ox, oy, oz = common["origin"].x, common["origin"].y, common["origin"].z
    x1, y1, z1 = common["bounds_max"].x, common["bounds_max"].y, common["bounds_max"].z
    width, height, depth = common["room_size"]

    divider_block = str(spec.get("divider_block", common["wall_block"]))
    divider_axis = str(spec.get("divider_axis", "z")).lower()
    if divider_axis not in {"x", "z"}:
        raise ValueError(f"{scene_id}: divider_axis must be 'x' or 'z'.")

    door_width = get_required_int(spec, "door_width")
    door_height = get_required_int(spec, "door_height")
    if door_height >= height - 1:
        raise ValueError(f"{scene_id}: door_height is too large for room height.")

    if divider_axis == "z":
        divider_coord = oz + depth // 2
        door_x0 = ox + (width - door_width) // 2
        door_x1 = door_x0 + door_width - 1
        divider_start = Vec3(ox + 1, oy + 1, divider_coord)
        divider_end = Vec3(x1 - 1, y1 - 1, divider_coord)
        door_min = Vec3(door_x0, oy + 1, divider_coord)
        door_max = Vec3(door_x1, oy + door_height, divider_coord)
        lane_x0 = ox + (width - door_width) // 2
        lane_x1 = lane_x0 + door_width - 1
        lane_start = Vec3(lane_x0, oy, oz + 1)
        lane_end = Vec3(lane_x1, oy, z1 - 1)
    else:
        divider_coord = ox + width // 2
        door_z0 = oz + (depth - door_width) // 2
        door_z1 = door_z0 + door_width - 1
        divider_start = Vec3(divider_coord, oy + 1, oz + 1)
        divider_end = Vec3(divider_coord, y1 - 1, z1 - 1)
        door_min = Vec3(divider_coord, oy + 1, door_z0)
        door_max = Vec3(divider_coord, oy + door_height, door_z1)
        lane_z0 = oz + (depth - door_width) // 2
        lane_z1 = lane_z0 + door_width - 1
        lane_start = Vec3(ox + 1, oy, lane_z0)
        lane_end = Vec3(x1 - 1, oy, lane_z1)

    reverse_lane_block = str(spec.get("reverse_lane_block", common["floor_block"]))
    opening_marker_block = str(spec.get("opening_marker_block", "minecraft:yellow_concrete"))

    setup_lines = list(common["setup_lines"])
    setup_lines.extend(
        [
            fill_cmd(divider_start, divider_end, divider_block),
            fill_cmd(door_min, door_max, "minecraft:air"),
            fill_cmd(lane_start, lane_end, reverse_lane_block),
            fill_cmd(door_min.shift(dy=-1), door_max.shift(dy=-1), opening_marker_block),
        ]
    )

    place_command_blocks_lines = [
        f"# No command blocks are needed for scene: {scene_id}",
    ]
    tick_lines = [
        f"# No tick logic is needed for scene: {scene_id}",
    ]
    clear_lines = list(common["clear_lines"])

    return finalize_scene(
        common,
        namespace,
        "reverse_parking_opening",
        setup_lines,
        place_command_blocks_lines,
        tick_lines,
        clear_lines,
        {
            "divider_axis": divider_axis,
            "divider_region": [
                divider_start.x,
                divider_start.y,
                divider_start.z,
                divider_end.x,
                divider_end.y,
                divider_end.z,
            ],
            "door_region": [door_min.x, door_min.y, door_min.z, door_max.x, door_max.y, door_max.z],
            "reverse_lane_region": [lane_start.x, lane_start.y, lane_start.z, lane_end.x, lane_end.y, lane_end.z],
        },
    )


def build_truck_reverse_guidance_scene(spec: Dict[str, Any], namespace: str) -> Dict[str, Any]:
    common = prepare_common(spec)
    scene_id = common["scene_id"]
    ox, oy, oz = common["origin"].x, common["origin"].y, common["origin"].z
    x1, y1, z1 = common["bounds_max"].x, common["bounds_max"].y, common["bounds_max"].z
    width, height, depth = common["room_size"]

    lane_marker_block = str(spec.get("lane_marker_block", "minecraft:yellow_concrete"))
    blind_wall_block = str(spec.get("blind_wall_block", "minecraft:gray_concrete"))
    parking_border_block = str(spec.get("parking_border_block", "minecraft:white_concrete"))
    parking_fill_block = str(spec.get("parking_fill_block", "minecraft:black_concrete"))
    truck_block = str(spec.get("truck_block", "minecraft:blue_concrete"))
    guidance_indicator_off_block = str(spec.get("guidance_indicator_off_block", "minecraft:red_concrete"))
    guidance_indicator_on_block = str(spec.get("guidance_indicator_on_block", "minecraft:lime_concrete"))
    checkpoint_plate_block = str(spec.get("checkpoint_plate_block", "minecraft:light_weighted_pressure_plate"))
    checkpoint_state = str(spec.get("checkpoint_plate_active_state", "powered=true"))
    observation_platform_block = str(spec.get("observation_platform_block", "minecraft:polished_andesite"))

    truck_size = validate_size(spec.get("truck_size", [3, 2, 5]), "truck_size")
    parking_size = validate_size(spec.get("parking_zone_size", [5, 1, 6]), "parking_zone_size")
    observation_size = validate_size(spec.get("observation_platform_size", [2, 2, 4]), "observation_platform_size")
    reverse_lane_width = get_required_int(spec, "reverse_lane_width")
    blind_wall_offset = get_required_int(spec, "blind_wall_offset")

    if reverse_lane_width < truck_size[0]:
        raise ValueError(f"{scene_id}: reverse_lane_width must be >= truck width.")

    lane_x0 = ox + (width - reverse_lane_width) // 2
    lane_x1 = lane_x0 + reverse_lane_width - 1
    lane_z0 = oz + 1
    lane_z1 = z1 - 1

    truck_min = Vec3(ox + (width - truck_size[0]) // 2, oy + 1, oz + 2)
    truck_max = Vec3(truck_min.x + truck_size[0] - 1, truck_min.y + truck_size[1] - 1, truck_min.z + truck_size[2] - 1)
    if truck_max.z >= z1 - 4:
        raise ValueError(f"{scene_id}: truck_size is too large for this room depth.")

    parking_min = Vec3(ox + (width - parking_size[0]) // 2, oy + 1, z1 - parking_size[2] - 1)
    parking_max = Vec3(parking_min.x + parking_size[0] - 1, parking_min.y + parking_size[1] - 1, parking_min.z + parking_size[2] - 1)

    blind_wall_z = min(truck_max.z + blind_wall_offset, parking_min.z - 2)
    if blind_wall_z <= truck_max.z:
        raise ValueError(f"{scene_id}: blind_wall_offset leaves no room for the truck blind wall.")
    blind_wall_min = Vec3(lane_x0, oy + 1, blind_wall_z)
    blind_wall_max = Vec3(lane_x1, oy + min(height - 2, truck_size[1] + 2), blind_wall_z)

    obs_w, obs_h, obs_d = observation_size
    observation_min = Vec3(ox + 1, oy + 1, parking_min.z)
    observation_max = Vec3(observation_min.x + obs_w - 1, observation_min.y + obs_h - 1, observation_min.z + obs_d - 1)
    if observation_max.z >= z1 or observation_max.y >= y1:
        raise ValueError(f"{scene_id}: observation_platform_size is too large.")

    rear_left_plate = Vec3(parking_min.x + 1, oy + 1, parking_min.z + 1)
    rear_right_plate = Vec3(parking_max.x - 1, oy + 1, parking_min.z + 1)
    indicator_min = Vec3(ox + width // 2 - 1, y1 - 1, z1 - 1)
    indicator_max = Vec3(ox + width // 2 + 1, y1 - 1, z1 - 1)

    setup_lines = list(common["setup_lines"])
    setup_lines.extend(
        [
            fill_cmd(Vec3(lane_x0, oy, lane_z0), Vec3(lane_x1, oy, lane_z1), lane_marker_block),
            fill_cmd(Vec3(lane_x0 + 1, oy, lane_z0), Vec3(lane_x1 - 1, oy, lane_z1), common["floor_block"]),
        ]
    )
    setup_lines.extend(fill_outline(parking_min, parking_max, parking_border_block))
    setup_lines.append(fill_cmd(parking_min.shift(dx=1, dz=1), parking_max.shift(dx=-1, dz=-1), parking_fill_block))
    setup_lines.extend(
        [
            fill_cmd(truck_min, truck_max, truck_block),
            fill_cmd(blind_wall_min, blind_wall_max, blind_wall_block),
            fill_cmd(observation_min.shift(dy=-1), observation_max.shift(dy=-1), observation_platform_block),
            fill_cmd(observation_min, observation_max, "minecraft:air"),
            setblock_cmd(rear_left_plate, checkpoint_plate_block),
            setblock_cmd(rear_right_plate, checkpoint_plate_block),
            fill_cmd(indicator_min, indicator_max, guidance_indicator_off_block),
            "",
            "# Command blocks that update the parking guidance indicator.",
            f"function {namespace}:{scene_id}/place_command_blocks",
        ]
    )

    active_plate_block = f"{checkpoint_plate_block}[{checkpoint_state}]"
    success_cond = (
        f"if block {rear_left_plate.to_cmd()} {active_plate_block} "
        f"if block {rear_right_plate.to_cmd()} {active_plate_block}"
    )
    success_cmd = fill_cmd(indicator_min, indicator_max, guidance_indicator_on_block)
    failure_cmd = fill_cmd(indicator_min, indicator_max, guidance_indicator_off_block)
    command_base = common["command_base"]
    place_command_blocks_lines = [
        f"# Place command blocks for scene: {scene_id}",
        (
            f'setblock {command_base.to_cmd()} minecraft:repeating_command_block[facing=east]'
            f'{{auto:1b,Command:"execute {success_cond} run {success_cmd}"}}'
        ),
        (
            f'setblock {command_base.shift(dx=1).to_cmd()} minecraft:repeating_command_block[facing=east]'
            f'{{auto:1b,Command:"execute unless block {rear_left_plate.to_cmd()} {active_plate_block} run {failure_cmd}"}}'
        ),
        (
            f'setblock {command_base.shift(dx=2).to_cmd()} minecraft:repeating_command_block[facing=east]'
            f'{{auto:1b,Command:"execute if block {rear_left_plate.to_cmd()} {active_plate_block} unless block {rear_right_plate.to_cmd()} {active_plate_block} run {failure_cmd}"}}'
        ),
    ]
    tick_lines = [
        f"# Tick logic for scene: {scene_id}",
        f"execute {success_cond} run {success_cmd}",
        f"execute unless block {rear_left_plate.to_cmd()} {active_plate_block} run {failure_cmd}",
        f"execute if block {rear_left_plate.to_cmd()} {active_plate_block} unless block {rear_right_plate.to_cmd()} {active_plate_block} run {failure_cmd}",
    ]
    clear_lines = list(common["clear_lines"])
    clear_lines.append(fill_cmd(command_base, command_base.shift(dx=2), "minecraft:air"))

    return finalize_scene(
        common,
        namespace,
        "truck_reverse_guidance",
        setup_lines,
        place_command_blocks_lines,
        tick_lines,
        clear_lines,
        {
            "truck_region": [truck_min.x, truck_min.y, truck_min.z, truck_max.x, truck_max.y, truck_max.z],
            "parking_zone": [parking_min.x, parking_min.y, parking_min.z, parking_max.x, parking_max.y, parking_max.z],
            "blind_wall": [blind_wall_min.x, blind_wall_min.y, blind_wall_min.z, blind_wall_max.x, blind_wall_max.y, blind_wall_max.z],
            "observation_platform": [
                observation_min.x,
                observation_min.y,
                observation_min.z,
                observation_max.x,
                observation_max.y,
                observation_max.z,
            ],
            "parking_checkpoint_plates": [
                [rear_left_plate.x, rear_left_plate.y, rear_left_plate.z],
                [rear_right_plate.x, rear_right_plate.y, rear_right_plate.z],
            ],
            "indicator_region": [indicator_min.x, indicator_min.y, indicator_min.z, indicator_max.x, indicator_max.y, indicator_max.z],
        },
    )


def build_heavy_object_dual_drag_scene(spec: Dict[str, Any], namespace: str) -> Dict[str, Any]:
    common = prepare_common(spec)
    scene_id = common["scene_id"]
    ox, oy, oz = common["origin"].x, common["origin"].y, common["origin"].z
    x1, y1, z1 = common["bounds_max"].x, common["bounds_max"].y, common["bounds_max"].z
    width, height, depth = common["room_size"]

    heavy_object_block = str(spec.get("heavy_object_block", "minecraft:ancient_debris"))
    target_outline_block = str(spec.get("target_outline_block", "minecraft:yellow_concrete"))
    drag_pad_block = str(spec.get("drag_pad_block", "minecraft:stone_pressure_plate"))
    drag_pad_state = str(spec.get("drag_pad_active_state", "powered=true"))
    moved_object_block = str(spec.get("moved_object_block", heavy_object_block))

    object_size = validate_size(spec.get("heavy_object_size", [3, 2, 3]), "heavy_object_size")
    target_offset = get_required_int(spec, "target_offset")

    obj_w, obj_h, obj_d = object_size
    object_min = Vec3(ox + (width - obj_w) // 2, oy + 1, oz + 2)
    object_max = Vec3(object_min.x + obj_w - 1, object_min.y + obj_h - 1, object_min.z + obj_d - 1)
    moved_min = object_min.shift(dz=target_offset)
    moved_max = object_max.shift(dz=target_offset)
    if moved_max.z >= z1 - 1:
        raise ValueError(f"{scene_id}: target_offset pushes the heavy object outside the room.")
    if obj_h >= height - 1:
        raise ValueError(f"{scene_id}: heavy_object_size is too tall for the room.")

    left_pad = Vec3(object_min.x - 1, oy + 1, object_min.z + obj_d // 2)
    right_pad = Vec3(object_max.x + 1, oy + 1, object_min.z + obj_d // 2)
    if left_pad.x <= ox or right_pad.x >= x1:
        raise ValueError(f"{scene_id}: room is too narrow for dual drag pads.")

    setup_lines = list(common["setup_lines"])
    setup_lines.extend(
        fill_outline(moved_min.shift(dy=-1), moved_max, target_outline_block)
    )
    setup_lines.extend(
        [
            fill_cmd(object_min, object_max, heavy_object_block),
            fill_cmd(moved_min, moved_max, "minecraft:air"),
            setblock_cmd(left_pad.shift(dy=-1), common["floor_block"]),
            setblock_cmd(right_pad.shift(dy=-1), common["floor_block"]),
            setblock_cmd(left_pad, drag_pad_block),
            setblock_cmd(right_pad, drag_pad_block),
            "",
            "# Command blocks that require both agents to drag at the same time.",
            f"function {namespace}:{scene_id}/place_command_blocks",
        ]
    )

    active_pad_block = f"{drag_pad_block}[{drag_pad_state}]"
    both_pressed = f"if block {left_pad.to_cmd()} {active_pad_block} if block {right_pad.to_cmd()} {active_pad_block}"
    left_not_pressed = f"unless block {left_pad.to_cmd()} {active_pad_block}"
    left_only_pressed = f"if block {left_pad.to_cmd()} {active_pad_block} unless block {right_pad.to_cmd()} {active_pad_block}"
    move_start_clear = fill_cmd(object_min, object_max, "minecraft:air")
    move_target_fill = fill_cmd(moved_min, moved_max, moved_object_block)
    reset_start_fill = fill_cmd(object_min, object_max, heavy_object_block)
    reset_target_clear = fill_cmd(moved_min, moved_max, "minecraft:air")

    command_base = common["command_base"]
    place_command_blocks_lines = [
        f"# Place command blocks for scene: {scene_id}",
        (
            f'setblock {command_base.to_cmd()} minecraft:repeating_command_block[facing=east]'
            f'{{auto:1b,Command:"execute {both_pressed} run {move_start_clear}"}}'
        ),
        (
            f'setblock {command_base.shift(dx=1).to_cmd()} minecraft:repeating_command_block[facing=east]'
            f'{{auto:1b,Command:"execute {both_pressed} run {move_target_fill}"}}'
        ),
        (
            f'setblock {command_base.shift(dx=2).to_cmd()} minecraft:repeating_command_block[facing=east]'
            f'{{auto:1b,Command:"execute {left_not_pressed} run {reset_start_fill}"}}'
        ),
        (
            f'setblock {command_base.shift(dx=3).to_cmd()} minecraft:repeating_command_block[facing=east]'
            f'{{auto:1b,Command:"execute {left_not_pressed} run {reset_target_clear}"}}'
        ),
        (
            f'setblock {command_base.shift(dx=4).to_cmd()} minecraft:repeating_command_block[facing=east]'
            f'{{auto:1b,Command:"execute {left_only_pressed} run {reset_start_fill}"}}'
        ),
        (
            f'setblock {command_base.shift(dx=5).to_cmd()} minecraft:repeating_command_block[facing=east]'
            f'{{auto:1b,Command:"execute {left_only_pressed} run {reset_target_clear}"}}'
        ),
    ]
    tick_lines = [
        f"# Tick logic for scene: {scene_id}",
        f"execute {both_pressed} run {move_start_clear}",
        f"execute {both_pressed} run {move_target_fill}",
        f"execute {left_not_pressed} run {reset_start_fill}",
        f"execute {left_not_pressed} run {reset_target_clear}",
        f"execute {left_only_pressed} run {reset_start_fill}",
        f"execute {left_only_pressed} run {reset_target_clear}",
    ]
    clear_lines = list(common["clear_lines"])
    clear_lines.append(fill_cmd(command_base, command_base.shift(dx=5), "minecraft:air"))

    return finalize_scene(
        common,
        namespace,
        "heavy_object_dual_drag",
        setup_lines,
        place_command_blocks_lines,
        tick_lines,
        clear_lines,
        {
            "heavy_object_start": [object_min.x, object_min.y, object_min.z, object_max.x, object_max.y, object_max.z],
            "heavy_object_target": [moved_min.x, moved_min.y, moved_min.z, moved_max.x, moved_max.y, moved_max.z],
            "drag_pad_positions": [
                [left_pad.x, left_pad.y, left_pad.z],
                [right_pad.x, right_pad.y, right_pad.z],
            ],
        },
    )


def build_lift_time_dependency_scene(spec: Dict[str, Any], namespace: str) -> Dict[str, Any]:
    common = prepare_common(spec)
    scene_id = common["scene_id"]
    ox, oy, oz = common["origin"].x, common["origin"].y, common["origin"].z
    x1, _, z1 = common["bounds_max"].x, common["bounds_max"].y, common["bounds_max"].z
    width, _, depth = common["room_size"]

    split_axis = str(spec.get("split_axis", "z")).lower()
    if split_axis not in {"x", "z"}:
        raise ValueError(f"{scene_id}: split_axis must be 'x' or 'z'.")

    source_floor_block = str(spec.get("source_floor_block", "minecraft:calcite"))
    target_floor_block = str(spec.get("target_floor_block", "minecraft:red_wool"))

    if split_axis == "z":
        split_coord = oz + depth // 2
        source_floor_min = Vec3(ox, oy, oz)
        source_floor_max = Vec3(x1, oy, split_coord - 1)
        target_floor_min = Vec3(ox, oy, split_coord)
        target_floor_max = Vec3(x1, oy, z1)
        source_zone_min = Vec3(ox + 1, oy + 1, oz + 1)
        source_zone_max = Vec3(x1 - 1, oy + 1, split_coord - 1)
        target_zone_min = Vec3(ox + 1, oy + 1, split_coord)
        target_zone_max = Vec3(x1 - 1, oy + 1, z1 - 1)
    else:
        split_coord = ox + width // 2
        source_floor_min = Vec3(ox, oy, oz)
        source_floor_max = Vec3(split_coord - 1, oy, z1)
        target_floor_min = Vec3(split_coord, oy, oz)
        target_floor_max = Vec3(x1, oy, z1)
        source_zone_min = Vec3(ox + 1, oy + 1, oz + 1)
        source_zone_max = Vec3(split_coord - 1, oy + 1, z1 - 1)
        target_zone_min = Vec3(split_coord, oy + 1, oz + 1)
        target_zone_max = Vec3(x1 - 1, oy + 1, z1 - 1)

    if source_zone_min.x > source_zone_max.x or source_zone_min.z > source_zone_max.z:
        raise ValueError(f"{scene_id}: source zone is too small for lift_time_dependency.")
    if target_zone_min.x > target_zone_max.x or target_zone_min.z > target_zone_max.z:
        raise ValueError(f"{scene_id}: target zone is too small for lift_time_dependency.")

    object_spawn = Vec3(
        (source_zone_min.x + source_zone_max.x) // 2,
        oy + 1,
        (source_zone_min.z + source_zone_max.z) // 2,
    )
    object_goal = Vec3(
        (target_zone_min.x + target_zone_max.x) // 2,
        oy + 1,
        (target_zone_min.z + target_zone_max.z) // 2,
    )

    setup_lines = list(common["setup_lines"])
    setup_lines.extend(
        [
            fill_cmd(source_floor_min, source_floor_max, source_floor_block),
            fill_cmd(target_floor_min, target_floor_max, target_floor_block),
        ]
    )

    place_command_blocks_lines = [
        f"# No command blocks are needed for scene: {scene_id}",
    ]
    tick_lines = [
        f"# No tick logic is needed for scene: {scene_id}",
    ]
    clear_lines = list(common["clear_lines"])

    return finalize_scene(
        common,
        namespace,
        "lift_time_dependency",
        setup_lines,
        place_command_blocks_lines,
        tick_lines,
        clear_lines,
        {
            "control_mode": "external_mod_binding",
            "split_axis": split_axis,
            "source_floor_block": source_floor_block,
            "target_floor_block": target_floor_block,
            "source_floor_region": [
                source_floor_min.x,
                source_floor_min.y,
                source_floor_min.z,
                source_floor_max.x,
                source_floor_max.y,
                source_floor_max.z,
            ],
            "target_floor_region": [
                target_floor_min.x,
                target_floor_min.y,
                target_floor_min.z,
                target_floor_max.x,
                target_floor_max.y,
                target_floor_max.z,
            ],
            "source_zone": [
                source_zone_min.x,
                source_zone_min.y,
                source_zone_min.z,
                source_zone_max.x,
                source_zone_max.y,
                source_zone_max.z,
            ],
            "target_zone": [
                target_zone_min.x,
                target_zone_min.y,
                target_zone_min.z,
                target_zone_max.x,
                target_zone_max.y,
                target_zone_max.z,
            ],
            "object_spawn_pos": [object_spawn.x, object_spawn.y, object_spawn.z],
            "object_goal_pos": [object_goal.x, object_goal.y, object_goal.z],
        },
    )


def build_scene(spec: Dict[str, Any], namespace: str) -> Dict[str, Any]:
    task_template = str(spec.get("task_template", "elevator_hold_door"))
    if task_template == "elevator_hold_door":
        return build_elevator_scene(spec, namespace)
    if task_template == "middle_wall_opening":
        return build_middle_wall_opening_scene(spec, namespace)
    if task_template == "reverse_parking_opening":
        return build_reverse_parking_opening_scene(spec, namespace)
    if task_template == "truck_reverse_guidance":
        return build_truck_reverse_guidance_scene(spec, namespace)
    if task_template == "heavy_object_dual_drag":
        return build_heavy_object_dual_drag_scene(spec, namespace)
    if task_template == "lift_time_dependency":
        return build_lift_time_dependency_scene(spec, namespace)
    raise ValueError(f"Unsupported task_template: {task_template}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate batch multi-agent Minecraft scenes.")
    parser.add_argument(
        "--spec",
        default="scene_specs/elevator_time_dependency_batch.json",
        help="Path to the scene spec JSON list.",
    )
    parser.add_argument(
        "--out",
        default="generated",
        help="Output root directory for generated mcfunction files.",
    )
    parser.add_argument(
        "--namespace",
        default=DEFAULT_NAMESPACE,
        help="Datapack namespace for generated functions.",
    )
    parser.add_argument(
        "--pack-name",
        default=DEFAULT_PACK_NAME,
        help="Folder name used under the generated datapacks directory.",
    )
    parser.add_argument(
        "--pack-format",
        type=int,
        default=DEFAULT_PACK_FORMAT,
        help="Datapack pack_format written into pack.mcmeta.",
    )
    parser.add_argument(
        "--scene-gap",
        type=int,
        default=DEFAULT_SCENE_GAP,
        help="Gap in blocks inserted between generated scenes along the X axis.",
    )
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    spec_path = (base_dir / args.spec).resolve() if not Path(args.spec).is_absolute() else Path(args.spec)
    out_root = (base_dir / args.out).resolve() if not Path(args.out).is_absolute() else Path(args.out)
    datapack_root = out_root / "datapacks" / sanitize_name(args.pack_name)

    if out_root.exists():
        shutil.rmtree(out_root)

    specs = layout_specs_non_overlapping(expand_specs(load_specs(spec_path)), gap=args.scene_gap)
    summaries: List[Dict[str, Any]] = []
    batch_setup_lines = ["# Auto-generated batch setup"]
    batch_clear_lines = ["# Auto-generated batch clear"]

    for spec in specs:
        scene = build_scene(spec, namespace=args.namespace)
        scene_dir = Path(scene["scene_id"])
        write_function_file(datapack_root, args.namespace, scene_dir / "setup.mcfunction", scene["setup"])
        write_function_file(
            datapack_root,
            args.namespace,
            scene_dir / "place_command_blocks.mcfunction",
            scene["place_command_blocks"],
        )
        write_function_file(datapack_root, args.namespace, scene_dir / "tick.mcfunction", scene["tick"])
        write_function_file(datapack_root, args.namespace, scene_dir / "clear.mcfunction", scene["clear"])
        summaries.append(scene["summary"])
        batch_setup_lines.append(f"function {args.namespace}:{scene['scene_id']}/setup")
        batch_clear_lines.append(f"function {args.namespace}:{scene['scene_id']}/clear")

    manifest = {
        "namespace": args.namespace,
        "datapack_name": sanitize_name(args.pack_name),
        "datapack_root": relativize_path(datapack_root, base_dir),
        "source_spec": relativize_path(spec_path, base_dir),
        "scene_count": len(summaries),
        "scenes": summaries,
    }

    pack_meta = {
        "pack": {
            "description": "Multi-agent Minecraft scene pack generated by multiagent/scene",
            "pack_format": args.pack_format,
            "supported_formats": DEFAULT_SUPPORTED_FORMATS,
        }
    }

    write_function_file(datapack_root, args.namespace, Path("setup_all.mcfunction"), "\n".join(batch_setup_lines) + "\n")
    write_function_file(datapack_root, args.namespace, Path("clear_all.mcfunction"), "\n".join(batch_clear_lines) + "\n")
    write_text(out_root / "scene_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    write_text(datapack_root / "pack.mcmeta", json.dumps(pack_meta, ensure_ascii=False, indent=2) + "\n")

    print(f"Generated {len(summaries)} scenes into {out_root}")


if __name__ == "__main__":
    main()
