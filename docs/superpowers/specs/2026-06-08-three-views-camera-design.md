# 三视角录制：A/B 第一人称 + 观察者同框 — 设计

日期：2026-06-08
状态：待用户审阅

## 背景与问题

`record_three_views.py` 录制一个 ConstructScene 任务里三个视角的朝向(yaw/pitch)+截图：
- **A 视角** = player_a 的第一人称
- **B 视角** = player_b 的第一人称
- **观察者** = 第三人称，同框看到 A 和 B

首次实测(`runs/three_views_task0_20260608-032936/`)发现视角错误：
- `pov Dev` 录出来的 A 视角里**糊着 AgentB 的身体/脑袋**，不是干净的第一人称。
- A 视角 与 观察者视角 **完全相同**(yaw/pitch/pos/画面一致)。

## 根因

视角由 SocketPuppet 模组的 `mc.setCameraEntity(...)` + `mc.options.setCameraType(...)` 控制；TickGate 只抓主渲染目标(`getMainRenderTarget`)，不参与相机决策。

两个缺陷在 `SocketPuppet.java` 的 `pov` 处理(约 424-451 行)：
1. `pov` 把相机挂到实体后**没有强制 `CameraType.FIRST_PERSON`**。
2. 原版渲染器只在「相机实体 == 本地玩家 且 第一人称」时隐藏玩家模型。相机挂到**别的**玩家实体(假人)上时，原版按旁观逻辑**渲染该实体自身模型** → 这就是糊在 A 视角里的身体。
3. 对 `pov Dev`(本地玩家自己)，等价于 `pov self`，所以 A 视角 == 观察者视角。

## 目标方案(方案 1，已确认)

让 A 和 B 都是**独立假人实体**(AgentA + AgentB)，各自用 `pov` 取真第一人称；观察者用自由旁观相机站固定机位，同框拍两人。

需要改三处：模组 Java、录制脚本、重新编译部署。

### 组件 1：模组 Java — `pov <entity>` 真第一人称

文件：`mods/socketpuppet/src/main/java/com/example/socketpuppet/SocketPuppet.java`

- 在 `pendingCameraEntityName` 处理块里，`setCameraEntity(best)` 成功后，**强制** `mc.options.setCameraType(CameraType.FIRST_PERSON)`。
- 新增字段 `public static volatile Entity hiddenCameraEntity`(或记录当前相机实体)，在 `pov` 成功时设为该实体；切回 `pov self` 时清空。
- 新增 `RenderPlayerEvent.Pre` 监听：若 `event.getEntity() == hiddenCameraEntity`(且当前是第一人称相机)则 `event.setCanceled(true)`，隐藏挡脸的自身模型。

依据：vanilla 对非本地玩家的相机实体不抑制模型；用 `RenderPlayerEvent.Pre` 取消渲染是 NeoForge 标准做法。

### 组件 2：模组 Java — 观察者自由相机指令

文件：`PuppetServer.java` + `SocketPuppet.java`

- 复用已验证的模式：观察者 = 旁观者自由相机(参考 `test_two_dummies_move.py` 用 `/spectate`)。
- 录制脚本侧把 Dev 切 `gamemode spectator`，`pov self` + 第一人称，再 `tp Dev <固定机位> <朝向>` 看向 A、B 中点。
- 此时 AgentA、AgentB 都是真实体、都在相机前方 → 同框可见。Dev 作为旁观相机不渲染自身。
- 结论：观察者**不需要新模组指令**，用现有 `pov self` + `cmd gamemode spectator` + `cmd tp Dev ...` 即可。组件 2 退化为纯脚本逻辑(见组件 3)。

### 组件 3：录制脚本 — 三视角流程

文件：`scripts/record_three_views.py`

1. 场景 setup(clear → setup → 命令方块)。
2. spawn 两个假人：`player AgentA spawn`、`player AgentB spawn`，各设 `gamemode creative`。
3. 摆位：`tp AgentA <A目标位> <A start_rotation>`、`tp AgentB <B目标位> <B start_rotation>`。
4. 读 pose：`query_entity AgentA`、`query_entity AgentB` → yaw/pitch/pos。
5. **A 视角**：`pov AgentA`(第一人称)→ 截图。
6. **B 视角**：`pov AgentB`(第一人称)→ 截图。
7. **观察者**：`cmd gamemode spectator Dev` → `pov self` → 计算 A/B 中点与退后机位 → `tp Dev <机位> <朝向>` → 截图。机位算法复用 `qwen_lowlevel_task_rollout.py:observer_camera_pose` 的思路(取两人包围盒中心、上方退后、看向中心)。
8. 输出 `views.json` + 三张 png，沿用现有格式。

注意：Dev 不再扮演 player_a，仅作观察相机。player_a = AgentA、player_b = AgentB，A/B 对称。

### 组件 4：编译与部署

- `cd Puppet && ./gradlew build`(JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64)。
- jar 在 `mods/socketpuppet/build/libs/socketpuppet-1.0.0.jar`。
- 拷到 `mc_runtime/EnvMine/envs/qwen-batch-1/run/mods/`(覆盖旧 jar)。
- 版本兼容：构建针对 NeoForge 21.1.60，运行时 21.1.230，依赖范围 `[21,)` / `[1.21,1.22)`，同为 MC 1.21.1，jar 跨 21.1.x 可加载(现有部署 jar 同理)。

## 数据流

```
脚本 --TCP--> PuppetServer.processCommand --> SocketPuppet 静态标志
                                              |
                          ClientTick 主线程读取标志:
                          - pov AgentA: setCameraEntity(AgentA)+FIRST_PERSON+hidden=AgentA
                          - RenderPlayerEvent.Pre: 取消渲染 AgentA 自身模型
                                              |
TickGate advance_image --> 抓主渲染目标 --> png --> 脚本写盘
```

## 测试与验收

- **A 视角**：第一人称，画面里**看不到自己的身体/脑袋**。
- **B 视角**：同上。
- **观察者**：一张图里**同时**能看到 AgentA 和 AgentB 两个假人。
- 三个 yaw/pitch 与各自 `start_rotation` / 机位算法吻合。
- 人工看三张 png 确认(Read 工具)。

## 不做(YAGNI)

- 不做平滑插值视角修复(那是另一个 bug，本次不碰)。
- 不改 TickGate。
- 不为观察者加新模组指令(脚本侧即可)。
- 不动训练/verl 流程。
