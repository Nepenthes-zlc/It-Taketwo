# It-Taketwo

It-Taketwo 是用于 verl GRPO 在线 EnvMine Minecraft rollout 的训练打包工程。它把训练 adapter、场景构建代码、生成的 datapack/任务、两个自研 Minecraft mod 源码,以及创建批量 worker 所需的 Minecraft 运行时模板,统一放在一个仓库里。模型权重、`verl`、日志和生成的 rollout 输出都不纳入常规 git 跟踪。

> **实现契约 —— 请先阅读。**
> 下面的 `<details>` 折叠块是本系统当前真实行为的权威描述,是所有**跨模块契约**的唯一可信来源
> (动作集合、奖励整形、成功判定标记、TickGate/Puppet 协议、verl 数据行、实例锁池)。
> **今后所有改动都必须符合本文档。** 如果某次改动需要修改其中任一契约,必须在同一个 commit 里
> 同步更新本块,并把这次编辑当作一次**有意的契约变更**,而不是普通实现细节。
> 绝不允许代码和本文档发生漂移。
> **本 README 全文以中文为准;命令、文件路径、配置键名、动作名等代码标识符保留英文原文,翻译它们会与代码对不上。**

<details>
<summary><b>每位开发者都必须了解的实现细节(点击展开)</b></summary>

### 1. 工作区布局与路径发现
- `adapter/envmine_verl/paths.py::discover_workspace()` 从模块文件向上逐级查找,直到找到一个
  **同时包含** `adapter/` 以及 `mc_runtime/EnvMine/`(或旧版顶层 `EnvMine/`)的目录,该目录即为
  `root`。其余路径(`envmine`、`verl`、`adapter`、`configs`、`scripts`)都由它派生。
- `configs/*.yaml` 中的相对路径**以工作区根目录解析**,而非当前工作目录
  (`agent_loop.py::_path_from_config`,`base=self.workspace.root`)。配置里请保持仓库相对路径,
  不要硬编码机器绝对路径。
- `mc_runtime/EnvMine` 由 `instance_pool.ensure_envmine_on_path()` 在运行时**延迟加入 `sys.path`**,
  以便导入 `envmine.*` 运行时包。adapter 包本身**不声明任何第三方依赖**
  (`pyproject.toml` 中 `dependencies = []`);PIL/omegaconf/verl 全部来自训练环境。

### 2. verl AgentLoop 入口
- 通过 `EnvMineLowLevelAgentLoop`(`agent_loop.py`)上的 `@register("envmine_lowlevel")` 注册为
  `envmine_lowlevel`。`configs/envmine_agent_loop.yaml` 把该名字映射到类,并提供 `envmine:` 配置块。
  冒烟测试变体是 `configs/envmine_agent_loop_smoke.yaml`(`max_steps=2`,settle/capture 参数更小)。
- 一次 `run()` 调用 == 对一条 prompt 行执行**一个完整的 Minecraft episode**。它要求存在视觉语言
  `processor`;若 `self.processor is None` 会直接抛错。
- 所有可调参数都在 YAML 的 `envmine:` 块里,在 `__init__` 中读取。基准默认值(生产 yaml):
  `max_steps=20`、`action_ticks=4`、`capture_ticks=2`、`pov_camera_settle_ticks=16`、
  `pov_extra_settle_ticks=8`、`pov_settle_render_frames=10`、`acquire_timeout=600`、
  `hide_hud=true`、`refresh_pack=false`、`randomize_starts=false`。

### 3. 动作空间(封闭集合 —— 不得私自扩展)
- **唯一合法**的动作就是 `env_episode.py` 中 `ACTION_TO_PUPPET` 的键:
  `wait, forward, backward, strafe_left, strafe_right, jump, turn_left, turn_right,
  look_up, look_down`。`ALLOWED_ACTIONS = list(ACTION_TO_PUPPET)`,是唯一来源。
- 每个动作映射到一条底层 Puppet 命令(如 `forward -> "w 0.12"`、`turn_left -> "turn -20 0 0.1"`)。
  **禁止 teleport / 禁止任何坐标级动作** —— prompt 已向策略做出此承诺,奖励的有效性依赖于此。
  若要新增动作,必须同时:① 加入 `ACTION_TO_PUPPET`(会自动更新 `ALLOWED_ACTIONS`),
  ② 在 `build_observation_message` 的 "Action meanings" 行里描述它;否则模型被告知的契约与代码不符。

### 4. 策略输入/输出契约
- 模型必须返回**一个紧凑的 JSON 对象**:
  `{"agent_a":"action","agent_b":"action","reason":"short reason"}`。
- 解析流程:`extract_first_json_object()` 扫描第一个配平的 `{...}`(感知字符串/转义),
  随后 `parse_actions()` 接受 `agent_a`/`AgentA`(以及 `_b`/`B`)键。任何未知或缺失的动作都被
  强制改成 `"wait"`。只要任一原始动作不在 `ALLOWED_ACTIONS` 中,`valid_actions` 即为 False;
  每个非法步会让 `invalid_actions` 加一。
- 观测消息(`build_observation_message`)顺序为:图A、图B、然后文本。**第一张图永远是 AgentA 视角,
  第二张永远是 AgentB 视角** —— prompt 文本和 `agent_loop.run()` 都依赖这个顺序。

### 5. Episode 生命周期(`EnvMineLowLevelEpisode`)
`start()` 严格按以下顺序执行(顺序至关重要,全部经 TickGate+Puppet 由 `game_cmd` 下发):
1. `_sync_datapack()` —— 把 `pack_src` 复制到世界的
   `saves/New World/datapacks/multiagent_scene_pack`。`refresh_pack=true` 时先删后拷;否则仅在缺失时拷贝。
2. `reload` → 关闭命令反馈相关 gamerule → 运行任务的 `scene_clear_function`,再运行
   `scene_setup_function`(名字来自 task JSON)→ `gamemode spectator Dev` + 夜视
   (Dev 是观察者/摄像玩家)。
3. `camera first_person`,可选 `f1` 隐藏 HUD。
4. 生成 `AgentA`/`AgentB` 假人玩家,设为创造模式,赋予 `glowing`。
5. 把两者传送到 task 中的 `start_pos`(当 `randomize_starts=true` 时按 `random_seed` 加抖动)。
随后返回 `observe(0)`。**改变此顺序(尤其是 clear 与 setup 的先后,或在 setup 前生成 agent)会破坏场景状态。**
- `observe()` 查询两者位姿(`query_agent_pose`),分别采集两个视角
  (`capture_agent_pov`:设置 `pov <agent>` + `camera first_person`,稳定
  `pov_camera_settle_ticks + pov_extra_settle_ticks` 个 tick,再抓一张 PNG),
  每个 agent 返回原始 PNG 字节。
- `step()` 下发两个 agent 的 Puppet 动作,推进 `action_ticks` 个 tick,然后评估成功标记。
  单步奖励为二值:全部标记为 true 时取 `1.0`。

### 6. 成功标记与奖励(奖励的权威定义)
- `query_success_markers()` 产出三个布尔值:
  - `pressure_plate_powered`:每步发出一个带唯一时间戳的标记,通过
    `execute if block <plate> minecraft:stone_pressure_plate[powered=true] run say <marker>`,
    再在服务器日志中检索该带戳字符串来判定。
  - `door_block_air`:对门所在格是否为 `air`,采用同样的「带戳 say + 抓日志」方式。
  - `agent_b_fully_in_second_room`:几何判定 —— `agent_fully_inside_second_room()` 要求 AgentB
    身体(中心 ± `PLAYER_HALF_WIDTH = 0.3`)越过门平面达 `SECOND_ROOM_ENTRY_DEPTH = 1.0`,
    阈值由 task 的 `target_region` 推出。
- **当且仅当 `all(markers.values())` 时 episode 结束。** 该标记机制依赖带戳日志抓取
  (UTC 时间戳 + `say` + 读日志);`start()` 中之所以关闭命令反馈 gamerule,正是为了避免其它输出
  污染日志匹配。**不要重新开启这些 gamerule。**
- `agent_loop.run()` 中最终 `reward_score`:
  `成功取 success_reward (1.0),否则取 failure_reward (0.0)`
  `− invalid_actions × invalid_action_penalty (0.05)`
  `− 步数 × step_penalty (0.0)`。
  环境自身的单步奖励是二值的;非法动作惩罚与步数整形由 AgentLoop 层施加。保持这两层职责分离。

### 7. token / 序列记账(verl 正确性)
- `_add_observation_tokens()`:第 0 步构建 prompt(含 system prompt);后续步以
  `remove_system_prompt=True` 追加观测,并**将其 mask 掉**(`response_mask` 补 `0`,logprobs 补 `0.0`)。
  生成的动作 token 则 `response_mask = 1`。
- 所有内容都截断到 `response_length`。若某次观测会超出 `response_length`,循环提前结束。
  若整个 episode 没有产生任何 response token,则编码一个兜底
  `{"agent_a":"wait",...}`,保证 verl 始终拿到非空 response。
- `num_turns = max(2, 2 * len(turn_records))`。`prompt_ids`/`response_ids` 按最终 `response_mask`
  长度切分。**必须保持这套 mask 纪律** —— GRPO 的优势分配恰恰依赖于「只有生成的动作 token 不被 mask」。

### 8. 实例池 / 并发(硬性不变量)
- `instance_pool.acquire_instance()` 使用 **`fcntl.flock` 建议锁**,在 `runs/locks/<instance>.lock`
  下每个实例一个文件。它遍历 `qwen_batch_lowlevel.json` 中的实例,抢占第一个空闲实例
  (非阻塞 `LOCK_EX|LOCK_NB`),每 1 秒轮询一次,直到 `acquire_timeout`。
- **因此:并发 rollout 数必须与 EnvMine 实例数同步扩展。** 如果 `AGENT_LOOP_WORKERS` /
  `ROLLOUT_N` / `TRAIN_BATCH_SIZE` 隐含的并发 episode 数超过实例数,多出的 worker 会阻塞在锁上
  直到有实例释放(或超时)。用 `mc_runtime/EnvMine/prepare_qwen_batch_envs.py` 创建更多 worker。
- 租约始终在 `finally` 中释放(`episode.close(); lease.release()`);**绝不能绕过它**,否则实例会
  以「永久锁定」状态泄漏。

### 9. 运行时传输(TickGate + Puppet)
- `InstanceRunner`(`mc_runtime/EnvMine/envmine/runner.py`)启动 `launch_tickgate.sh`,连接一个
  **JSON 行 TickGate 客户端**(确定性 tick 控制:`pause`、`wait_ready`、
  `advance_wait <ticks> <frames>`、返回 `png_base64` 的 `advance_image ...`)和一个
  **文本行 Puppet 客户端**(假人控制)。世界被显式暂停并按 tick 步进 —— rollout 是按 tick 确定性的,
  而非按墙钟时间。
- 当 `puppet_port=0` 时,Puppet 端口从 `run/socketpuppet_data/port.txt` 发现
  (`clients.discover_puppet_port`)。图像帧以 base64-PNG 返回,在 `cmd_image` 中解码为字节。

### 10. 任务与数据
- 任务文件:`ConstructScene/generated/generated_tasks.json`(`{"tasks":[...]}`);每个任务包含
  `id`、`scene_id`、`scene_setup_function`、`scene_clear_function`,以及
  `players.player_a/player_b`,其中含 `start_pos` 和 `goal`(压力板用 `target_pos`,
  门口用 `target_region`)。`load_task()` 按 `task_index` 索引此列表。
- verl prompt 行(`data/envmine_lowlevel/*.jsonl`):每行含 `agent_name="envmine_lowlevel"`、
  一个 `task_index`、可选 `random_seed`,以及 `reward_model.ground_truth.task_index`。
  `_task_index()` 按优先级从 `task_index` → `extra_info` → `reward_model.ground_truth` 解析索引。
  `_random_seed()` 优先用显式 seed,否则用 `(task_index, uid)` 的 **稳定** sha1 ——
  同一行 → 同一 seed,因此 episode 可复现。
- 默认训练数据格式为 **JSONL**(verl 可读,且避免在基础 shell 里依赖 `pyarrow`);
  在 `envmine-verl` conda 环境中 `DATA_FORMAT=parquet` 也可用。

### 11. Git 卫生(哪些跟踪、哪些不跟踪)
- 跟踪:adapter、configs、scripts、场景构建器 + 生成的 datapack/tasks、小体量数据,
  以及**运行时模板** `mc_runtime/EnvMine/envs/qwen-runtime-task12-purevision`。
- 永不提交(`.gitignore`):`verl/`、生成的 `mc_runtime/EnvMine/envs/qwen-batch-*` worker、
  `runs/ outputs/ logs/ test_results/`、世界的 `session.lock`、socketpuppet 数据(`.gitkeep` 除外),
  以及旧版顶层 `/EnvMine` 符号链接。worker 由 `prepare_qwen_batch_envs.py` 从模板生成,**不要提交**。

</details>

## 包含哪些内容

```text
It-Taketwo/
  adapter/envmine_verl/        # verl AgentLoop 与 EnvMine rollout adapter
  configs/                     # AgentLoop 配置,使用仓库相对路径
  ConstructScene/              # 场景构建代码、场景规格、生成的 datapack/任务
  data/envmine_lowlevel/       # 用于 train/test 冒烟的小体量 JSONL prompt 数据
  mc_runtime/EnvMine/          # 本地 MC/TickGate/Puppet 运行时模板与 EnvMine runner 代码
  mods/socketpuppet/           # SocketPuppet mod 源码(角色控制,NeoForge,独立 gradle 构建)
  mods/tickgate/               # TickGate mod 源码(确定性 tick + 截图,独立 gradle 构建)
  scripts/                     # 安装、数据准备、rollout、GRPO 与打包命令
  pyproject.toml               # 可编辑安装的 adapter 包
  ONLINE_GRPO.md               # 更简短的在线 GRPO 说明
```

以下运行时产物默认有意不提交:

- `verl` 是上游 verl 的 checkout。
- `mc_runtime/EnvMine/envs/qwen-batch-*` 是生成的 worker 副本。
- `runs/`、`outputs/`、`logs/`、`test_results/` 以及运行时日志都是生成的输出。

## 快速开始

```bash
cd /home/zlc/Multiagent/EnvMineVerl

# 1. 有网络时,拉取或修复上游 verl checkout。
./scripts/bootstrap_verl.sh

# 2. 把 adapter 与 verl 依赖安装进本地训练环境。
./scripts/install_verl_env.sh

# 3. 从已提交的模板创建本地 Minecraft 批量 worker 目录。
python3 mc_runtime/EnvMine/prepare_qwen_batch_envs.py --count 2 --base-port 25590 --parallel 2 --force

# 4. 检查 Python 导入与本地路径。
/home/zlc/.conda/envs/envmine-verl/bin/python scripts/check_verl_env.py
```

已提交的 Minecraft 运行时模板是:

```text
mc_runtime/EnvMine/envs/qwen-runtime-task12-purevision
```

`prepare_qwen_batch_envs.py` 会把该模板复制成运行时 worker,例如:

```text
mc_runtime/EnvMine/envs/qwen-batch-1
mc_runtime/EnvMine/envs/qwen-batch-2
```

并写出 `mc_runtime/EnvMine/configs/qwen_batch_lowlevel.json`,这正是训练 adapter 读取的文件。

## 场景构建

场景构建器在 `ConstructScene/` 中。它可以重新生成训练所用的 Minecraft datapack 与任务 JSON:

```bash
cd /home/zlc/Multiagent/EnvMineVerl/ConstructScene
python3 generate_scenes.py --spec scene_specs/elevator_time_dependency_batch.json --out generated --namespace multiagent_scene
python3 generate_tasks.py --task-category elevator --num-tasks 20 --manifest generated/scene_manifest.json --out generated/generated_tasks.json
```

训练 adapter 默认读取以下仓库内文件:

- `ConstructScene/generated/generated_tasks.json`
- `ConstructScene/generated/datapacks/multiagent_scene_pack`

当运行时世界需要刷新时,把生成的 datapack 部署到各 Minecraft env 槽位:

```bash
python3 ConstructScene/deploy_datapack_to_envs.py \
  --src-pack ConstructScene/generated/datapacks/multiagent_scene_pack \
  --env-root /path/to/env/root \
  --count 4 \
  --overwrite
```

## 准备训练数据

从仓库内的场景任务生成 verl prompt 行:

```bash
python3 scripts/prepare_envmine_verl_data.py \
  --task-indices 0 \
  --episodes-per-task 1 \
  --output-dir data/envmine_lowlevel \
  --format jsonl
```

默认训练启动器会在 `train.jsonl` 与 `test.jsonl` 缺失时,自动从 `ConstructScene/generated/generated_tasks.json` 创建它们。

## 冒烟 rollout

不启动 Minecraft,空跑 EnvMine 批量包装器:

```bash
python3 scripts/run_envmine_rollout.py --dry-run --policy fixed --episodes-per-task 2 --parallel 2
```

运行一次简短的固定策略 Minecraft 冒烟:

```bash
python3 scripts/run_envmine_rollout.py --policy fixed --max-steps 2 --parallel 2
```

通过 Qwen 兼容端点运行:

```bash
python3 scripts/run_envmine_rollout.py --policy qwen --task-indices 0 --episodes-per-task 1 --max-steps 20 --parallel 2
```

## 在线 GRPO 训练

只校验 Hydra 作业配置而不启动训练:

```bash
bash scripts/run_envmine_grpo_smoke.sh --cfg job
```

启动小规模在线冒烟 profile:

```bash
MODEL_PATH=/path/to/Qwen2.5-VL-3B-Instruct bash scripts/run_envmine_grpo_smoke.sh
```

启动常规 profile:

```bash
MODEL_PATH=/path/to/Qwen2.5-VL-7B-Instruct bash scripts/run_envmine_grpo.sh
```

常用覆盖项:

```bash
TASK_INDICES=0,1 EPISODES_PER_TASK=2 ROLLOUT_N=2 AGENT_LOOP_WORKERS=2 bash scripts/run_envmine_grpo.sh
DATA_FORMAT=parquet bash scripts/run_envmine_grpo.sh
LOGGER='["console","wandb"]' bash scripts/run_envmine_grpo.sh
```

AgentLoop 在 `configs/envmine_agent_loop.yaml` 中注册为 `envmine_lowlevel`。它读取 `mc_runtime/EnvMine/configs/qwen_batch_lowlevel.json`。每次 rollout 会获取一个本地 EnvMine 实例锁,刷新或复用场景 datapack,为 AgentA 和 AgentB 采集第一人称截图,向策略请求 JSON 低层动作,经 Puppet/TickGate 执行,并把在线奖励返回给 verl。

为更大的 rollout 并行度创建更多 worker:

```bash
python3 mc_runtime/EnvMine/prepare_qwen_batch_envs.py \
  --count 8 \
  --base-port 25590 \
  --parallel 8 \
  --force
```

## 打包

从 git 可见文件创建一个源码训练包:

```bash
./scripts/package_training_bundle.sh
```

归档路径会被打印出来,通常位于 `dist/` 下。该默认包包含 adapter、configs、scripts、场景构建器、生成的 datapack/任务、小体量数据文件,以及已提交的 `mc_runtime/EnvMine` 运行时模板。它**不**包含生成的 `qwen-batch-*` worker、`verl`、模型权重或输出。

若需要一个更重、且在存在时也包含 `verl` 的离线归档:

```bash
INCLUDE_RUNTIME=1 ./scripts/package_training_bundle.sh /tmp/envmine_verl_full_runtime.tar.gz
```

## Git 卫生

跟踪这些部分:

```bash
git add .gitignore README.md ONLINE_GRPO.md pyproject.toml adapter configs scripts data ConstructScene
git status --short
```

按设计被忽略:旧版外部 `EnvMine` 符号链接、`verl`、生成的 `mc_runtime/EnvMine/envs/qwen-batch-*` worker、`runs`、`outputs`、`logs`、`test_results`、各类缓存,以及包元数据。这样可以让提交聚焦于可复现的训练代码、场景资产和可复用的 MC 运行时模板,同时避免纳入生成的输出。
