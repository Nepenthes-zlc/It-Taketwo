# TickGate

A NeoForge 1.21.1 mod that turns Minecraft into a **step-controlled simulator**.

The world only advances when an external controller (or an op with the in-game
command) explicitly grants tick/frame budget. Built for RL / multi-agent rollout
where every environment step must be deterministic and synchronous.

## What it does

- **Pause the server tick loop.** While paused, no entities move, no blocks
  update, no scheduled tasks run.
- **Step the world by N ticks.** Grant budget; the server runs exactly N ticks.
- **Dual barriers (MineStudio-style):**
  - server barrier: world progression completed
  - render barrier: next frame presented
- **External control over TCP.** A line-oriented localhost IPC server.
- **In-game `/tickgate` command.** Op-level 2 for debugging/admin control.

## In-game commands

```text
/tickgate pause
/tickgate resume
/tickgate step <n>
/tickgate step_wait_server <n>
/tickgate step_wait_client <n>
/tickgate step_wait_dual <n>
/tickgate rate <hz>
/tickgate set_render_cadence <n>
/tickgate set_max_step_batch <n>
/tickgate status
/tickgate render_once
```

## IPC protocol

Default bind: `127.0.0.1:25575` (configurable). One ASCII verb per line,
one JSON object per reply.

| Verb | Effect |
| --- | --- |
| `ping` | health check |
| `ready` | return current world readiness flag |
| `wait_ready` | block until world is ready |
| `pause` | freeze server tick loop |
| `resume` | unfreeze and clear pending budget |
| `step <n>` | grant n tick budget, return immediately |
| `step_wait <n>` | legacy alias of `step_wait_server <n>` |
| `step_wait_server <n>` | grant n budget and block until server barrier completes |
| `step_wait_client <n>` | block until render barrier completes by n frames |
| `step_wait_dual <n>` | `step_wait_server n` then `step_wait_client 1` |
| `observe_wait <s> <r>` | wait server barrier `s` and render barrier `r` |
| `observe_ready [r]` | pause world and wait `r` render frames before action capture (`r` default 1) |
| `advance_wait <n> [r]` | advance exactly `n` server ticks after action, wait `r` render frames, remain paused (`r` default 1) |
| `step_observe <n> [r]` | grant `n`, wait server `n`, then wait render `r` (`r` omitted uses cadence) |
| `set_render_cadence <n>` | set default cadence for `step_observe` (1 = every step waits render) |
| `set_max_step_batch <n>` | set max `n` accepted by `step*` verbs |
| `status` | return current state |
| `stats` | return telemetry counters and latency totals |
| `rate <hz>` | set desired tick rate (1..1000), applied to server tick manager |
| `render_once` | set one-shot render marker flag |
| `client_pause` / `client_resume` | toggle client tick gating |
| `quit` / `exit` | close this connection |

Every reply is one JSON line:

```json
{"ok":true,"paused":true,"pendingTicks":0,"completedServerTicks":12345,"completedRenderFrames":54321,"serverTick":12345,"renderFrame":54321,"observationFrame":54321,"tickRate":20,"clientPaused":false,"renderCadence":1,"maxStepBatch":1000000,"worldReady":true}
```

## Rollout loop with Puppet (recommended)

TickGate provides the synchronization barriers. [SocketPuppet](../Puppet/) provides the action/control channel.

```python
import json
import socket

class LineClient:
    def __init__(self, host, port):
        self.s = socket.create_connection((host, port))
        self.f = self.s.makefile("rwb", buffering=0)

    def cmd_json(self, line):
        self.f.write((line + "\n").encode())
        return json.loads(self.f.readline().decode())

    def cmd_text(self, line):
        self.s.sendall((line + "\n").encode())
        return self.s.recv(4096).decode().strip()

tickgate = LineClient("127.0.0.1", 25575)
puppet = LineClient("127.0.0.1", 12345)  # or read Puppet's run/socketpuppet_data/port.txt

tickgate.cmd_json("wait_ready")
tickgate.cmd_json("pause")

for _ in range(1000):
    tickgate.cmd_json("observe_ready 1")
    obs = grab_frame()

    action = policy(obs)
    puppet.cmd_text(action)  # e.g. "w 1.0", "look 90 0", "attack", "use"

    tickgate.cmd_json("advance_wait 10 1")
```

Use `observe_ready` before screenshot/capture. Use `advance_wait` after Puppet sends the action. The world remains paused between iterations.

`step_observe` is still available for older controllers, but `observe_ready` + Puppet action + `advance_wait` matches the MineStudio ordering more directly.

## MineStudio-style launch

MineStudio launches Minecraft under a virtual display for headless CPU rendering, or under VirtualGL for GPU rendering. TickGate provides the same style of wrapper:

```bash
./launch_tickgate.sh --device cpu
```

CPU mode requires `xvfb-run`. GPU mode requires VirtualGL:

```bash
./launch_tickgate.sh --device /dev/dri/by-path/<render-device>
```

For supervised startup, readiness waiting, Puppet discovery, and a short rollout loop:

```bash
python3 run_rollout.py --device cpu --ready-timeout 180 --rounds 3 --ticks 5 --use-puppet
```

Readiness-only smoke test:

```bash
python3 run_rollout.py --device cpu --ready-timeout 180 --no-rollout
```

Plain `./gradlew runClient` needs a real `DISPLAY`; in headless environments it can fail with `glfwInit failed`.

## Config

`config/tickgate-common.toml`:

```toml
ipcEnabled             = true
ipcHost                = "127.0.0.1"
ipcPort                = 25575
pauseOnStartup         = false
defaultTickRate        = 20
renderCadence          = 1
maxStepBatch           = 1000000
autoEnterWorldEnabled  = false
autoEnterMode          = "loadExisting"
autoWorldName          = "New World"
autoWorldSeed          = "12345"
autoWorldCreative      = false
```

One-click startup examples:

```toml
# load an existing world and auto-enter at client startup
autoEnterWorldEnabled = true
autoEnterMode = "loadExisting"
autoWorldName = "New World"
```

```toml
# create-and-enter from seed at client startup
autoEnterWorldEnabled = true
autoEnterMode = "createFromSeed"
autoWorldName = "RL-Seed-World"
autoWorldSeed = "2026"
autoWorldCreative = false
```

## Notes

- Server pause freezes server-side keepalive progression too; long pauses are
  not suitable for normal human multiplayer sessions.
- `client_pause` blocks the render thread by design; do not use it for normal
  screenshot rollouts because it prevents fresh frames.
- Render barriers require a client. On a dedicated server, use `advance_wait <n> 0`.
- TickGate does not inject actions; use Puppet or another control layer for that.
- IPC has no authentication; keep it on loopback only.

## Building

```bash
./gradlew build
./gradlew runClient
./gradlew runServer
```

Targets Java 21, NeoForge `21.1.x` on Minecraft `1.21.1`.
