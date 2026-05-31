# Multi-Agent Scene Generator

这里放的是一个可批量生成 Minecraft `mcfunction` 场景的工具。现在已经支持 3 类多智能体协作模板:

- `elevator_hold_door`: 时空依赖性任务，Agent A 持续踩住压力板，Agent B 才能进入电梯
- `middle_wall_opening`: 一个基础场景模板，只搭中间隔墙和留空门洞，不放电梯门
- `reverse_parking_opening`: 倒车任务的基础场景模板，只搭中间隔墙和留空门洞，保留倒车通道
- `truck_reverse_guidance`: 信息共享任务，司机视野受限，需要另一名 Agent 在观察位引导倒车入库
- `heavy_object_dual_drag`: 单个 Agent 能力不足任务，必须两个 Agent 同时发力，重物才会移动

## 文件说明

- `generate_scenes.py`: 读取 JSON 配置，批量生成场景。
- `scene_specs/elevator_time_dependency_batch.json`: 示例批量配置，里面现在包含 3 类模板。
- `generated/`: 运行脚本后生成的 `mcfunction` 输出目录。

## 你现在可以直接控制的参数

- 场景起点 `origin`
- 房子长宽高 `room_size`
- 电梯门大小 `door_width` 和 `door_height`
- 电梯门到压力板的距离 `plate_offset`
- 天花板嵌入式光源大小 `ceiling_light_size`
- 各类方块可以写成单个字符串，或者可选列表

例如:

```json
{
  "origin": [0, -59, 0],
  "room_size": [13, 6, 15],
  "door_width": 2,
  "door_height": 3,
  "plate_offset": 2,
  "ceiling_light_block": "minecraft:sea_lantern",
  "ceiling_light_size": [1, 1],
  "floor_block": ["minecraft:smooth_stone", "minecraft:deepslate_tiles"],
  "wall_block": ["minecraft:quartz_block", "minecraft:light_gray_concrete"],
  "elevator_block": ["minecraft:tinted_glass", "minecraft:iron_block"]
}
```

如果某个方块字段写成列表，脚本会自动做笛卡尔积展开，生成多个场景变体。
为避免输出路径过长，变体场景现在会使用较短的 `scene_id`，并把完整材质组合保留在 `scene_manifest.json` 的 `variant_key` / `variant_options` 里。

## 模板概览

### `elevator_hold_door`

- 一个中空房间
- 地板、四周墙壁、天花板
- 房间正中间的一堵厚度为 1 的隔墙
- 隔墙正中的电梯门区域
- 门前的压力板
- 两个自动命令方块

逻辑是:

- 压力板被按下时，把电梯门区域 `fill` 成 `minecraft:air`
- 压力板没有被按住时，把电梯门区域恢复成指定的 `elevator_block`

### `truck_reverse_guidance`

- 一个倒车车道
- 一个停车目标区
- 一个遮挡司机视线的盲区墙
- 一个供另一名 Agent 观察和指挥的观察平台
- 两个停车检测压力板和一个红绿指示区

逻辑是:

- 车辆尾部到达目标区两处检测点时，指示灯切到绿色
- 司机本身受盲区墙影响，需要另一名 Agent 共享信息

### `heavy_object_dual_drag`

- 一个重物起始区
- 一个重物目标区
- 重物两侧的双人拖拽压力板

逻辑是:

- 两块压力板同时被按下时，重物从起点移动到目标区
- 只按下一块或没人按时，重物保持在起点

### `middle_wall_opening`

- 一个中空房间
- 一面房间正中的隔墙
- 一个指定宽高的门洞
- 不填充任何“电梯门”方块

逻辑是:

- 这是一个纯结构模板，没有命令方块逻辑
- 适合你先批量造基础房间，再接别的任务机制

### `reverse_parking_opening`

- 一个中空房间
- 一面房间正中的隔墙
- 一个指定宽高的留空门洞
- 一条对准门洞的倒车通道
- 不填充任何门方块

逻辑是:

- 这是给倒车任务用的基础结构模板
- 你可以在此基础上再叠加停车位、障碍物、检查点等机制

## 用法

在这个目录下运行:

```bash
python3 generate_scenes.py
```

如果要基于已经生成好的场景，随机生成多智能体任务 JSON:

```bash
python3 generate_tasks.py --num-tasks 20
```

如果只想生成电梯任务:

```bash
python3 generate_tasks.py --task-template elevator_hold_door --num-tasks 20
```

也可以按更直观的任务类别名来生成，例如只生成电梯类任务:

```bash
python3 generate_tasks.py --task-category elevator --num-tasks 20
```

当前 `generate_tasks.py` 支持的任务类别别名有:

- `elevator` -> `elevator_hold_door`
- `truck` -> `truck_reverse_guidance`
- `heavy` -> `heavy_object_dual_drag`

如果要换配置文件:

```bash
python3 generate_scenes.py --spec scene_specs/elevator_time_dependency_batch.json
```

如果要换输出目录或命名空间:

```bash
python3 generate_scenes.py --out generated_custom --namespace my_scene
```

## 生成结果

默认会输出到:

`generated/datapacks/multiagent_scene_pack/data/multiagent_scene/functions/`

每个场景都有:

- `setup.mcfunction`: 建场景并放下命令方块
- `place_command_blocks.mcfunction`: 单独放置“检测压力板并开/关门”的两个命令方块
- `tick.mcfunction`: 不依赖命令方块时，可直接作为 datapack tick 逻辑使用
- `clear.mcfunction`: 清空场景

另外还有:

- `setup_all.mcfunction`: 一次性生成全部场景
- `clear_all.mcfunction`: 一次性清理全部场景
- `generated/scene_manifest.json`: 所有场景的坐标摘要
- `generated_tasks.json`: 基于 `scene_manifest.json` 随机生成的任务数据

## 任务 JSON 结构

`generate_tasks.py` 会输出一份任务文件，里面每条任务都包含:

- `scene_id`
- `task_template`
- `scene_setup_function`
- `scene_clear_function`
- `task_description`
- `players.player_a`
- `players.player_b`
- `success_conditions`

其中每个 player 都有:

- `role`
- `start_pos`
- `start_rotation`
- `goal`

这样你后面就可以直接把这份 JSON 喂给 agent 系统，或者转成你自己的训练/评测格式。

## 配置字段

- `id`: 场景名
- `task_template`: 模板类型，可选 `elevator_hold_door`、`middle_wall_opening`、`reverse_parking_opening`、`truck_reverse_guidance`、`heavy_object_dual_drag`
- `origin`: 房间外框最小角坐标 `[x, y, z]`
- `room_size`: 房间大小 `[width, height, depth]`
- `floor_block`: 地板方块，支持字符串或列表
- `wall_block`: 墙壁方块，支持字符串或列表
- `ceiling_block`: 天花板方块，支持字符串或列表
- `divider_block`: 中间隔墙方块，支持字符串或列表
- `elevator_block`: 门关闭时填充的“电梯门”方块，支持字符串或列表
- `pressure_plate_block`: 压力板方块，支持字符串或列表
- `pressure_plate_active_state`: 压下时的 block state，常见为 `powered=true`
- `ceiling_light_block`: 嵌入天花板内的光源方块
- `ceiling_light_size`: 光源区域大小 `[a, b]`，表示天花板中一个 `a x b` 的发光面板
- `door_width`: 门宽
- `door_height`: 门高
- `plate_offset`: 压力板离隔墙的距离
- `command_block_base`: 两个控制命令方块的起始坐标，默认放在房间内部靠角落的位置

各模板额外字段:

- `elevator_hold_door`
- `divider_axis`
- `divider_block`
- `elevator_block`
- `pressure_plate_block`
- `pressure_plate_active_state`

- `middle_wall_opening`
- `divider_axis`
- `divider_block`
- `door_width`
- `door_height`

- `reverse_parking_opening`
- `divider_axis`
- `divider_block`
- `door_width`
- `door_height`
- `reverse_lane_block`
- `opening_marker_block`

- `truck_reverse_guidance`
- `lane_marker_block`
- `blind_wall_block`
- `parking_border_block`
- `parking_fill_block`
- `truck_block`
- `guidance_indicator_off_block`
- `guidance_indicator_on_block`
- `checkpoint_plate_block`
- `checkpoint_plate_active_state`
- `observation_platform_block`
- `truck_size`
- `parking_zone_size`
- `observation_platform_size`
- `reverse_lane_width`
- `blind_wall_offset`

- `heavy_object_dual_drag`
- `heavy_object_block`
- `moved_object_block`
- `target_outline_block`
- `drag_pad_block`
- `drag_pad_active_state`
- `heavy_object_size`
- `target_offset`

## 适合你后续扩展的方向

- 同时输出 agent 出生点、朝向、目标点
- 给倒车模板增加更多检查点和侧向引导灯
- 把重物拖拽改成分阶段移动，而不是一步到位
- 接入 WorldEdit 辅助命令或你现有的任务 JSON 生成流程
