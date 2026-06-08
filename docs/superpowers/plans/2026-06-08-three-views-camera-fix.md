# Three-Views Camera Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `pov <entity>` render a clean first-person view (no camera entity's own body in frame) so player A (AgentA) and player B (AgentB) each get correct first-person screenshots, and make the observer a fixed free-camera that frames both dummies.

**Architecture:** Fix the SocketPuppet mod's `pov` handler to force `FIRST_PERSON` and cancel rendering of the camera entity's own model via `RenderPlayerEvent.Pre`. Rebuild and redeploy the jar. Rewrite `record_three_views.py` so A and B are symmetric Carpet dummies captured via `pov`, and the observer is Dev in spectator mode teleported to a backed-off overhead pose looking at the A/B midpoint.

**Tech Stack:** Java 21 / NeoForge 21.1.x (MC 1.21.1), Gradle (moddev plugin), Python 3 (envmine runner + tickgate/puppet clients).

**Build note:** Always build with `JAVA_HOME=/home/azvm/.gradle/jdks/eclipse_adoptium-21-amd64-linux.2` — the only JDK with `javac` on this box. `chmod +x gradlew` if needed.

**Verification note:** Mod camera behavior is not unit-testable. Verification = compile succeeds, the live test renders screenshots, and a human (Read tool) inspects the PNGs. Each task states its concrete check.

---

## Task 1: Add first-person forcing + camera-entity model hiding to the mod

**Files:**
- Modify: `mods/socketpuppet/src/main/java/com/example/socketpuppet/SocketPuppet.java`
  - imports near top (after existing `net.minecraft.*` imports)
  - new static field near the other camera state (~line 94)
  - `pov` handler block (lines 424-451)
  - new `@SubscribeEvent` method (after `onPlayerTick`, ~line 935)

- [ ] **Step 1: Add the import and tracking field**

Add import alongside the other `net.neoforged.neoforge.client.event.*` imports (the file already imports `ClientTickEvent` and `MovementInputUpdateEvent` from that package, near line 24-25):

```java
import net.neoforged.neoforge.client.event.RenderPlayerEvent;
```

Add a static field next to `pendingCameraEntityName` (~line 95):

```java
    /** 当前被相机附着的实体（命名假人）：渲染时取消其自身模型，避免第一人称里挡脸。null 表示相机在本地玩家或未附着。 */
    public static volatile Entity hiddenCameraEntity = null;
```

- [ ] **Step 2: Force FIRST_PERSON and set/clear hiddenCameraEntity in the pov handler**

Replace the `pendingCameraEntityName` block (lines 424-451) with:

```java
        if (pendingCameraEntityName != null) {
            String cameraEntityName = pendingCameraEntityName;
            pendingCameraEntityName = null;
            if ("default".equalsIgnoreCase(cameraEntityName) || "player".equalsIgnoreCase(cameraEntityName) || "self".equalsIgnoreCase(cameraEntityName)) {
                mc.setCameraEntity(mc.player);
                hiddenCameraEntity = null;
                mc.options.setCameraType(net.minecraft.client.CameraType.FIRST_PERSON);
                currentAction = "POV: self";
            } else if (mc.level != null) {
                Vec3 c = mc.player.position();
                AABB box = new AABB(c, c).inflate(160.0);
                List<Entity> matches = mc.level.getEntitiesOfClass(Entity.class, box,
                        e -> entityPoseNameMatches(e, cameraEntityName));
                Entity best = null;
                double bestD = Double.MAX_VALUE;
                for (Entity e : matches) {
                    double d = e.distanceToSqr(mc.player);
                    if (d < bestD) {
                        bestD = d;
                        best = e;
                    }
                }
                if (best != null) {
                    mc.setCameraEntity(best);
                    hiddenCameraEntity = best;
                    mc.options.setCameraType(net.minecraft.client.CameraType.FIRST_PERSON);
                    currentAction = "POV: " + cameraEntityName;
                } else {
                    currentAction = "POV failed: " + cameraEntityName;
                }
            }
        }
```

- [ ] **Step 3: Add the RenderPlayerEvent.Pre handler to hide the camera entity's own model**

Add this method right after `onPlayerTick` (after line ~935, before the `entityPoseNameMatches` helper):

```java
    /** 第一人称下，取消渲染「当前相机所附着的那个假人」自身模型，避免挡住视野。 */
    @SubscribeEvent
    public void onRenderPlayerPre(RenderPlayerEvent.Pre event) {
        Entity hidden = hiddenCameraEntity;
        if (hidden == null) return;
        Minecraft mc = Minecraft.getInstance();
        if (mc.options.getCameraType() != net.minecraft.client.CameraType.FIRST_PERSON) return;
        if (event.getEntity() == hidden) {
            event.setCanceled(true);
        }
    }
```

- [ ] **Step 4: Compile to verify it builds**

Run:
```bash
cd /local_nvme/zhanglechao/EnvMineVerl/Puppet && chmod +x gradlew && JAVA_HOME=/home/azvm/.gradle/jdks/eclipse_adoptium-21-amd64-linux.2 ./gradlew compileJava --no-daemon
```
Expected: `BUILD SUCCESSFUL`. If it fails on `getCameraType()`/`getEntity()` symbol, check the exact method name with `javap` against the cached neoforge jar and adjust.

- [ ] **Step 5: Commit**

```bash
cd /local_nvme/zhanglechao/EnvMineVerl
git add mods/socketpuppet/src/main/java/com/example/socketpuppet/SocketPuppet.java
git commit -m "fix(puppet): pov <entity> renders true first-person (force FIRST_PERSON, hide camera entity model)"
```

---

## Task 2: Build and deploy the jar

**Files:**
- Build output: `mods/socketpuppet/build/libs/socketpuppet-1.0.0.jar`
- Deploy target: `mc_runtime/EnvMine/envs/qwen-batch-1/run/mods/socketpuppet-1.0.0.jar`

- [ ] **Step 1: Full build**

Run:
```bash
cd /local_nvme/zhanglechao/EnvMineVerl/Puppet && JAVA_HOME=/home/azvm/.gradle/jdks/eclipse_adoptium-21-amd64-linux.2 ./gradlew build --no-daemon
```
Expected: `BUILD SUCCESSFUL`, jar present at `build/libs/socketpuppet-1.0.0.jar`.

- [ ] **Step 2: Verify jar timestamp is fresh and contains the new class**

Run:
```bash
ls -la /local_nvme/zhanglechao/EnvMineVerl/mods/socketpuppet/build/libs/socketpuppet-1.0.0.jar
unzip -l /local_nvme/zhanglechao/EnvMineVerl/mods/socketpuppet/build/libs/socketpuppet-1.0.0.jar | grep SocketPuppet.class
```
Expected: jar mtime is now; `SocketPuppet.class` listed.

- [ ] **Step 3: Deploy (overwrite the running env's jar)**

Run:
```bash
cp /local_nvme/zhanglechao/EnvMineVerl/mods/socketpuppet/build/libs/socketpuppet-1.0.0.jar /local_nvme/zhanglechao/EnvMineVerl/mc_runtime/EnvMine/envs/qwen-batch-1/run/mods/socketpuppet-1.0.0.jar
ls -la /local_nvme/zhanglechao/EnvMineVerl/mc_runtime/EnvMine/envs/qwen-batch-1/run/mods/socketpuppet-1.0.0.jar
```
Expected: deployed jar mtime is now.

- [ ] **Step 4: Commit (no code change — just note in plan; skip if nothing tracked changed)**

No source change in this task; nothing to commit. The jar and `build/` are gitignored.

---

## Task 3: Rewrite record_three_views.py for symmetric A/B dummies + fixed observer

**Files:**
- Modify: `scripts/record_three_views.py`

This task replaces the body of `run()` and the capture helpers. A is no longer Dev; A = AgentA dummy. Observer = Dev in spectator mode at an overhead backed-off pose.

- [ ] **Step 1: Replace the observer capture + add a midpoint camera helper**

Replace the `capture_observer` function with a version that computes a pose framing both dummies. Add a helper above it:

```python
def _observer_pose(pose_a: dict, pose_b: dict) -> tuple[list[float], float, float]:
    """Overhead, backed-off camera looking at the midpoint of A and B."""
    pa = pose_a.get("pos") or [0.0, 0.0, 0.0]
    pb = pose_b.get("pos") or [0.0, 0.0, 0.0]
    mid = [(pa[0] + pb[0]) / 2.0, (pa[1] + pb[1]) / 2.0, (pa[2] + pb[2]) / 2.0]
    span = max(2.0, abs(pa[0] - pb[0]), abs(pa[2] - pb[2]))
    back = span + 4.0
    camera = [mid[0], mid[1] + 3.0, mid[2] - back]
    dx = mid[0] - camera[0]
    dy = (mid[1] + 0.9) - (camera[1] + 1.62)
    dz = mid[2] - camera[2]
    import math
    horiz = math.hypot(dx, dz)
    yaw = math.degrees(math.atan2(-dx, dz))
    pitch = math.degrees(-math.atan2(dy, horiz))
    return camera, yaw, pitch


def capture_observer(runner: InstanceRunner, pose_a: dict, pose_b: dict, args: SimpleNamespace) -> tuple[dict, dict]:
    """Observer: Dev as a spectator free-camera at an overhead pose framing both dummies."""
    camera, yaw, pitch = _observer_pose(pose_a, pose_b)
    if runner.puppet is not None:
        runner.puppet.send("pov self", wait=False)
        runner.puppet.send("camera first_person", wait=False)
    game_cmd(runner, "gamemode spectator Dev", 5)
    game_cmd(runner, f"tp Dev {camera[0]:.3f} {camera[1]:.3f} {camera[2]:.3f} {yaw:.3f} {pitch:.3f}", args.pov_camera_settle_ticks)
    if runner.tickgate is not None:
        settle = args.pov_extra_settle_ticks
        runner.tickgate.cmd(f"advance_wait {settle} {args.pov_settle_render_frames}", timeout=30.0)
    image = runner.capture_image(
        ticks=args.capture_ticks,
        render_frames=args.capture_render_frames,
        timeout=args.capture_timeout,
    )
    image["camera_entity"] = "observer"
    obs_pose = {"pos": camera, "yaw": yaw, "pitch": pitch, "type": "observer_camera"}
    return image, obs_pose
```

- [ ] **Step 2: Rewrite the body of run() to spawn AgentA + AgentB and capture symmetrically**

Replace the block from `runner.start()` through the `capture_observer` call (the `try:` body up to `time.sleep(0.5)`) with:

```python
    runner = InstanceRunner(config, WORKSPACE / "scripts" / "logs")
    views: list[dict[str, Any]] = []
    try:
        runner.start()
        game_cmd(runner, "reload", 40)
        game_cmd(runner, "gamerule commandBlockOutput false", 5)

        # Scene.
        game_cmd(runner, f"function {scene_clear}", 20)
        game_cmd(runner, f"function {scene_setup}", 40)

        # A and B are symmetric Carpet dummies.
        game_cmd(runner, "player AgentA spawn", 40)
        game_cmd(runner, "gamemode creative AgentA", 5)
        game_cmd(runner, "player AgentB spawn", 40)
        game_cmd(runner, "gamemode creative AgentB", 5)

        a_pos = player_a["goal"]["target_pos"]
        game_cmd(
            runner,
            f"tp AgentA {a_pos[0] + 0.5:.3f} {a_pos[1]:.3f} {a_pos[2] + 0.5:.3f} {a_start_rot[0]:.3f} {a_start_rot[1]:.3f}",
            30,
        )
        game_cmd(
            runner,
            f"tp AgentB {b_target[0]:.3f} {b_target[1]:.3f} {b_target[2]:.3f} {b_start_rot[0]:.3f} {b_start_rot[1]:.3f}",
            30,
        )
        runner.tickgate.cmd("advance_wait 20 1", timeout=90.0)

        pose_a = query_agent_pose(runner, "AgentA")
        pose_b = query_agent_pose(runner, "AgentB")

        # View A: first-person from AgentA.
        image_a = capture_agent_pov(runner, "AgentA", pose_a, pov_args)
        views.append(write_view(out_dir, "player_a_AgentA", pose_a, image_a))

        # View B: first-person from AgentB.
        image_b = capture_agent_pov(runner, "AgentB", pose_b, pov_args)
        views.append(write_view(out_dir, "player_b_AgentB", pose_b, image_b))

        # Observer: Dev spectator free-cam framing both.
        image_obs, pose_obs = capture_observer(runner, pose_a, pose_b, pov_args)
        views.append(write_view(out_dir, "observer", pose_obs, image_obs))

        time.sleep(0.5)
        log_path = str(runner.log_path) if runner.log_path else None
    finally:
        runner.close()
```

- [ ] **Step 3: Byte-compile to catch syntax errors**

Run:
```bash
cd /local_nvme/zhanglechao/EnvMineVerl && python3 -m py_compile scripts/record_three_views.py && echo OK
```
Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
cd /local_nvme/zhanglechao/EnvMineVerl
git add scripts/record_three_views.py
git commit -m "feat(record_three_views): symmetric AgentA/AgentB first-person + fixed observer framing both"
```

---

## Task 4: Run end-to-end and verify the three views

**Files:** none (run + inspect).

- [ ] **Step 1: Run the recorder on task 0**

Run (background, ~5-10 min for world boot + capture):
```bash
cd /local_nvme/zhanglechao/EnvMineVerl && JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64 timeout 700 python3 scripts/record_three_views.py --task-index 0 > /tmp/three_views_run2.log 2>&1; echo "EXIT=$?"
```
Note: the *runtime launcher* uses the JRE fine (it only runs java, not javac); only the gradle build needs the Temurin JDK.
Expected: EXIT=0.

- [ ] **Step 2: Read the views.json**

```bash
LATEST=$(ls -dt /local_nvme/zhanglechao/EnvMineVerl/runs/three_views_task0_* | head -1); cat "$LATEST/views.json"
```
Expected: three views with non-error poses; A and B yaw match their `start_rotation`.

- [ ] **Step 3: Inspect the three PNGs (Read tool)**

Read `player_a_AgentA.png`, `player_b_AgentB.png`, `observer.png` from the latest run dir.
Expected:
- A: first-person, NO own body/head in frame.
- B: first-person, NO own body/head in frame.
- observer: BOTH AgentA and AgentB visible in one frame.

- [ ] **Step 4: If a view is wrong, debug before claiming done**

- A/B still shows own body → the `RenderPlayerEvent.Pre` cancel isn't matching; verify `hiddenCameraEntity` equality (entity identity vs. the rendered Player) and that camera type is FIRST_PERSON. Adjust mod, rebuild (Task 2), rerun.
- Observer doesn't frame both → tune `_observer_pose` back/height, rerun (Python only, no rebuild).

- [ ] **Step 5: Final commit (only if files changed during debug)**

```bash
cd /local_nvme/zhanglechao/EnvMineVerl
git add -A && git commit -m "fix: tune three-views camera after live verification"
```

---

## Self-Review Notes

- **Spec coverage:** Component 1 (first-person pov) → Task 1. Component 2 (observer, degraded to script-only per spec) → Task 3 Step 1. Component 3 (script flow) → Task 3 Step 2. Component 4 (build/deploy) → Task 2. Verification → Task 4.
- **Symbol consistency:** `hiddenCameraEntity` defined Task 1 Step 1, used Steps 2-3. `capture_observer` signature changed to `(runner, pose_a, pose_b, args)` and called that way in Task 3 Step 2. `_observer_pose` defined and used in Task 3 Step 1.
- **Known risk:** `RenderPlayerEvent.Pre` fires on the game bus (`NeoForge.EVENT_BUS`), which this class is already registered to (`NeoForge.EVENT_BUS.register(this)` in constructor). Good — no separate registration needed.
