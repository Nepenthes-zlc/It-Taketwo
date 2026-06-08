# Minecraft SocketPuppet Mod (NeoForge 1.21)

这是一个基于 NeoForge 1.21 的 Minecraft 模组，允许外部程序（如 Python 脚本）通过 TCP Socket 连接直接控制游戏内的玩家角色。支持移动、视角控制、动作执行、物品栏交互以及游戏状态查询等功能。

## 安装说明

1.  在项目根目录运行 `./gradlew build` 进行构建。
2.  将生成的 `.jar` 文件（位于 `build/libs/` 目录下）放入你的 Minecraft `mods` 文件夹中。
3.  使用 NeoForge 1.21 版本启动 Minecraft。

## 使用方法

当模组加载并进入游戏世界后，它会自动启动一个 TCP 服务器，监听端口范围 `12345` 到 `12445`。实际占用的端口号会显示在游戏聊天栏中，并写入到 `run/socketpuppet_data/port.txt` 文件里。

你可以使用任何 TCP 客户端（例如 Python 的 `socket` 库）连接该端口并发送指令。

### 数据目录
模组的数据存储在 `run/socketpuppet_data/` 目录下：
-   `port.txt`: 记录当前服务器监听的端口号。
-   `recording.csv`: 当开启录制时，存储玩家的位置日志。

### 指令列表

所有指令通过纯文本字符串发送，并以换行符 (`\n`) 结尾。大多数动作指令都支持一个可选的 `duration`（持续时间，单位：秒）参数。

#### 代理/假人命名 (Agent / Puppet Name)
所有操作都可以绑定到一个**名字**上：不写名字或使用 `default` / `player` 表示**默认玩家**；其它名字（如 `agenta`）表示**命名假人**（当前版本仍控制同一本地玩家，仅作显示与协议区分）。

*   **方式一**：每条指令前加代理名，用空格分隔。
    *   例：`agenta w 1` → 以「agenta」身份向前移动 1 秒；`agenta look 0 0` → 以「agenta」身份设置视角。
*   **方式二**：先用 `agent <name>` 设定当前代理，后续指令均视为该代理操作，直到再次 `agent default` 或换名。
    *   例：`agent agenta` → 之后发送 `w 1`、`look 0 0` 都会显示为 (agenta)；`agent default` → 改回默认玩家。

游戏内 HUD 会显示当前代理名，例如：`[Puppet] (agenta) w`。

若使用 `/spectate AgentA` 将视线附着在假人上，该假人可能处于**观察者模式**（可穿墙）。可通过 Socket 发送 `gamemode survival`（当前代理为命名假人时会对该假人执行）或 `gamemode survival AgentA`，将假人改为生存模式即可正常碰撞。

#### 移动控制 (Movement)
*   `w [duration]`: 向前移动。
*   `s [duration]`: 向后移动。
*   `a [duration]`: 向左平移。
*   `d [duration]`: 向右平移。
*   `jump [duration]`: 跳跃。
*   `sneak`: 切换潜行（蹲伏）状态。
*   `stop`: 停止所有移动。

#### 视角控制 (Camera)
*   `look <yaw> <pitch> [duration]`: 设置绝对视角朝向。
    *   `yaw`: 水平角度，-180 到 180 (0=南, -90=东, 90=西, 180/-180=北)。
    *   `pitch`: 垂直角度，-90 (上) 到 90 (下)。
    *   `duration`: 可选，秒数；若给出则在该时间内平滑插值到目标角度，不给出则瞬间完成。
*   `turn <delta_yaw> <delta_pitch> [duration]`: 相对当前视角进行转动。
    *   `duration`: 可选。如果大于 0，则在指定时间内平滑转动。

#### 动作交互 (Actions)
*   `attack` / `left_click`: 模拟左键点击（攻击/破坏）。
*   `use` / `right_click`: 模拟右键点击（使用物品/交互）。
*   `inventory` / `e`: 打开或关闭物品栏。
*   `clear_inv`: 清空玩家物品栏（需要作弊权限）。

#### 自动瞄准 (Aiming)
*   `aim <x> <y> <z> <max_dist> [max_angle] [duration]`: 瞄准指定的 3D 坐标。
    *   `max_dist`: 最大允许距离，超过则不执行。
    *   `max_angle`: 最大允许转动角度（视野限制），超过则不执行。
    *   `duration`: 转动持续时间（秒）。
*   `aim <block_id> <radius> [max_angle] [duration]`: 搜索并瞄准范围内最近的指定方块。
    *   `block_id`: 方块ID，如 `minecraft:gold_block` 或 `gold_block`。
    *   `radius`: 搜索半径。

#### 方块交互与查询 (Interaction & Queries)
*   `grab`: 抓取视线指向的方块（最大距离 10 格）。
    *   **创造模式**: 将物品添加到物品栏并移除方块。
    *   **生存模式**: 仅在客户端视觉上设置手中物品（如需实际获得物品建议用 `/give` 指令），并移除方块。
    *   **返回**: 成功时返回 `SUCCESS` 及坐标；超出距离或无方块则返回 `FAIL`。
*   `get_block <x> <y> <z>`: 查询指定坐标的方块信息。
    *   **返回**: `BLOCK <x> <y> <z> <block_id> <state>`
*   `get_hand`: 查询主手当前持有的物品。
    *   **返回**: `HAND <item_id> <count> <nbt_info>`
*   `get_sight`: 查询视线正前方的方块（最大 100 格）。
    *   **返回**: `SIGHT <block_id> <x> <y> <z>` 或 `FAIL`。
*   `get_reachable`: 查询玩家周围 3x3 范围内的可达（空气）方块。
    *   **返回**: `REACHABLE <x1> <y1> <z1> ...` (坐标列表)。
    *   **顺序**: 以玩家当前朝向为基准，从**正前方**开始**顺时针**旋转一圈 (前 -> 前右 -> 右 ... -> 前左)。

#### 系统与工具 (System)
*   `gamemode <mode> [目标名]`: 设置游戏模式。`mode` 可为 `survival`/`adventure`/`creative`/`spectator` 或数字 0–3。省略目标时，若当前代理为命名假人则对该假人执行（常用于将假人从观察者改为生存以避免穿墙）。
*   `record start`: 开始记录玩家位置到 `recording.csv`。
*   `record stop`: 停止记录。
    *   *注：当客户端连接时会自动开始记录，断开时自动停止。*
*   `cmd <command>`: 执行 Minecraft 原版指令（例如 `cmd time set day`）。
*   `chat <message>`: 发送聊天信息。
*   `f1`: 切换 GUI 显示/隐藏。
*   `f2`: 游戏截图。

## Python 客户端示例

项目根目录下提供了一个功能完善的 Python 客户端脚本 `smart_client.py`，处理了连接、缓冲和超时等问题。

基础用法示例：
```python
from smart_client import SmartClient, get_port

# 获取自动保存的端口号
port = get_port()
client = SmartClient('127.0.0.1', port)

# 发送查询指令并等待回复
response = client.send("get_hand", wait_for_response=True)
print(response)

# 发送移动指令（通常不需要等待回复）
client.send("w 1.0")
```
