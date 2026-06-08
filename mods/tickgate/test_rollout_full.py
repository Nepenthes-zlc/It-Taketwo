import argparse
import json
import socket
import sys
import time
from dataclasses import dataclass


HOST = "127.0.0.1"
PORT = 25575


@dataclass
class TGStatus:
    paused: bool
    pendingTicks: int
    completedServerTicks: int
    completedRenderFrames: int
    tickRate: int
    clientPaused: bool
    renderCadence: int
    maxStepBatch: int
    worldReady: bool

    @staticmethod
    def from_dict(d: dict) -> "TGStatus":
        return TGStatus(
            paused=bool(d.get("paused", False)),
            pendingTicks=int(d.get("pendingTicks", 0)),
            completedServerTicks=int(d.get("completedServerTicks", 0)),
            completedRenderFrames=int(d.get("completedRenderFrames", 0)),
            tickRate=int(d.get("tickRate", 0)),
            clientPaused=bool(d.get("clientPaused", False)),
            renderCadence=int(d.get("renderCadence", 1)),
            maxStepBatch=int(d.get("maxStepBatch", 1_000_000)),
            worldReady=bool(d.get("worldReady", False)),
        )


class TickGateClient:
    def __init__(self, host: str, port: int, conn_timeout: float = 5.0):
        self.host = host
        self.port = port
        self.conn_timeout = conn_timeout
        self.sock = None
        self.f = None

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=self.conn_timeout)
        self.f = self.sock.makefile("rwb", buffering=0)

    def close(self):
        try:
            if self.f:
                self.f.close()
        finally:
            self.f = None
            if self.sock:
                self.sock.close()
            self.sock = None

    def cmd(self, command: str, timeout: float = 20.0) -> dict:
        self.sock.settimeout(timeout)
        self.f.write((command + "\n").encode("utf-8"))
        line = self.f.readline()
        if not line:
            raise RuntimeError(f"empty response for command: {command}")
        text = line.decode("utf-8", "ignore").strip()
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            raise RuntimeError(f"non-json response for {command}: {text}")
        print(f"{command:>24} => {obj}")
        return obj

    def status(self, timeout: float = 5.0) -> TGStatus:
        obj = self.cmd("status", timeout=timeout)
        if not obj.get("ok", False):
            raise RuntimeError(f"status returned not ok: {obj}")
        return TGStatus.from_dict(obj)

    def observe_ready(self, frames: int = 1, timeout: float = 10.0) -> TGStatus:
        obj = self.cmd(f"observe_ready {frames}", timeout=timeout)
        if not obj.get("ok", False):
            raise RuntimeError(f"observe_ready returned not ok: {obj}")
        return TGStatus.from_dict(obj)

    def advance_wait(self, ticks: int, frames: int = 1, timeout: float = 20.0) -> TGStatus:
        obj = self.cmd(f"advance_wait {ticks} {frames}", timeout=timeout)
        if not obj.get("ok", False):
            raise RuntimeError(f"advance_wait returned not ok: {obj}")
        return TGStatus.from_dict(obj)


class PuppetClient:
    def __init__(self, host: str, port: int, conn_timeout: float = 5.0):
        self.host = host
        self.port = port
        self.conn_timeout = conn_timeout
        self.sock = None

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=self.conn_timeout)
        self.sock.settimeout(2.0)

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = None

    def send(self, command: str, wait_for_response: bool = True) -> str | None:
        if not self.sock:
            raise RuntimeError("Puppet client is not connected")
        self.sock.sendall((command + "\n").encode("utf-8"))
        if not wait_for_response:
            return None
        data = self.sock.recv(4096)
        return data.decode("utf-8", "ignore").strip() if data else None


def require(cond: bool, msg: str):
    if not cond:
        raise AssertionError(msg)


def test_pause_freeze_server_only(cli: TickGateClient):
    print("\n[TEST 1] pause 后 server 冻结、render 可继续")
    cli.cmd("resume", timeout=5)
    cli.cmd("pause", timeout=5)
    s1 = cli.status(timeout=5)
    time.sleep(1.0)
    s2 = cli.status(timeout=5)

    require(
        s2.completedServerTicks <= s1.completedServerTicks + 1,
        f"paused 后 server 漂移超过 1 tick: {s1.completedServerTicks} -> {s2.completedServerTicks}"
    )

    if s2.completedRenderFrames > s1.completedRenderFrames:
        print("  [INFO] render 计数增长是正常的（渲染帧与 server tick 解耦）")
    else:
        print("  [INFO] render 计数未增长，也可接受")


def test_step_wait_server(cli: TickGateClient, n: int):
    print("\n[TEST 2] step_wait_server")
    cli.cmd("pause", timeout=5)
    before = cli.status(timeout=5)

    cli.cmd(f"step_wait_server {n}", timeout=max(15, n * 2))
    after = cli.status(timeout=5)

    require(
        after.completedServerTicks >= before.completedServerTicks + n,
        f"server barrier 未达到预期: before={before.completedServerTicks}, after={after.completedServerTicks}, n={n}"
    )


def test_step_wait_client(cli: TickGateClient, n: int = 1):
    print("\n[TEST 3] step_wait_client")
    before = cli.status(timeout=5)
    cli.cmd(f"step_wait_client {n}", timeout=10)
    after = cli.status(timeout=5)

    require(
        after.completedRenderFrames >= before.completedRenderFrames + n,
        f"render barrier 未达到预期: before={before.completedRenderFrames}, after={after.completedRenderFrames}, n={n}"
    )


def test_step_wait_dual(cli: TickGateClient, n: int):
    print("\n[TEST 4] step_wait_dual")
    cli.cmd("pause", timeout=5)
    before = cli.status(timeout=5)
    cli.cmd(f"step_wait_dual {n}", timeout=max(20, n * 2))
    after = cli.status(timeout=5)

    require(
        after.completedServerTicks >= before.completedServerTicks + n,
        f"dual: server barrier 未达到预期: before={before.completedServerTicks}, after={after.completedServerTicks}, n={n}"
    )
    require(
        after.completedRenderFrames >= before.completedRenderFrames + 1,
        f"dual: render barrier 未达到预期: before={before.completedRenderFrames}, after={after.completedRenderFrames}"
    )


def rollout_loop(cli: TickGateClient, rounds: int, ticks_per_step: int):
    print("\n[TEST 5] legacy rollout 循环: render-ready -> action -> step_observe -> grab(status)")
    cli.cmd("pause", timeout=5)
    cli.cmd("step_wait_client 1", timeout=10)
    last = cli.status(timeout=5)

    for i in range(1, rounds + 1):
        print(f"\n  [ROUND {i}] action(sent)")

        cli.cmd(f"step_observe {ticks_per_step}", timeout=max(20, ticks_per_step * 2))
        s_after = cli.status(timeout=5)
        require(
            s_after.completedServerTicks >= last.completedServerTicks + ticks_per_step,
            f"round {i}: server 未按预期推进"
        )
        require(
            s_after.completedRenderFrames >= last.completedRenderFrames,
            f"round {i}: render 计数异常回退"
        )

        print(
            f"  [ROUND {i}] grab obs: "
            f"server={s_after.completedServerTicks}, render={s_after.completedRenderFrames}"
        )
        last = s_after


def minestudio_like_rollout(cli: TickGateClient, rounds: int, ticks_per_step: int, puppet: PuppetClient | None):
    print("\n[TEST 6] MineStudio-like rollout: observe_ready -> Puppet action -> advance_wait")
    cli.cmd("pause", timeout=5)
    last = cli.observe_ready(1, timeout=10)
    require(last.paused, "observe_ready 后世界应保持暂停")
    require(last.pendingTicks == 0, "observe_ready 后不应有 pending tick")

    for i in range(1, rounds + 1):
        before = cli.observe_ready(1, timeout=10)
        require(before.paused, f"round {i}: action 前世界应暂停")
        require(before.pendingTicks == 0, f"round {i}: action 前不应有 pending tick")

        if puppet:
            reply = puppet.send("w 1.0", wait_for_response=True)
            print(f"  [ROUND {i}] Puppet action reply: {reply}")
        else:
            print(f"  [ROUND {i}] Puppet action skipped (--puppet-port not set)")

        after = cli.advance_wait(ticks_per_step, 1, timeout=max(20, ticks_per_step * 2))
        require(after.paused, f"round {i}: advance_wait 后世界应暂停")
        require(after.pendingTicks == 0, f"round {i}: advance_wait 后不应有 pending tick")
        require(
            after.completedServerTicks >= before.completedServerTicks + ticks_per_step,
            f"round {i}: server 未按预期推进"
        )
        require(
            after.completedServerTicks <= before.completedServerTicks + ticks_per_step + 1,
            f"round {i}: server 推进过多: before={before.completedServerTicks}, after={after.completedServerTicks}"
        )
        require(
            after.completedRenderFrames >= before.completedRenderFrames + 1,
            f"round {i}: post-step render frame 未就绪"
        )
        last = after

    if puppet:
        puppet.send("stop", wait_for_response=True)


def test_rate_consistency(cli: TickGateClient):
    print("\n[TEST 7] rate 一致性（IPC 设置后状态一致）")
    cli.cmd("rate 40", timeout=5)
    s = cli.status(timeout=5)
    require(s.tickRate == 40, f"tickRate 不一致: {s.tickRate}")


def test_cadence_and_composite(cli: TickGateClient, ticks: int):
    print("\n[TEST 8] cadence + step_observe + observe_wait")
    cli.cmd("pause", timeout=5)
    cli.cmd("set_render_cadence 2", timeout=5)
    s0 = cli.status(timeout=5)
    require(s0.renderCadence == 2, f"renderCadence 设置失败: {s0.renderCadence}")

    before = cli.status(timeout=5)
    cli.cmd(f"step_observe {ticks}", timeout=max(20, ticks * 2))
    after = cli.status(timeout=5)

    require(
        after.completedServerTicks >= before.completedServerTicks + ticks,
        "step_observe 未推进足够 server ticks"
    )

    if (before.completedServerTicks // 1 + 1) % 2 == 0:
        require(
            after.completedRenderFrames >= before.completedRenderFrames + 1,
            "step_observe 在 cadence 触发点未等待 render"
        )

    b2 = cli.status(timeout=5)
    cli.cmd("step 1", timeout=10)
    cli.cmd("observe_wait 1 1", timeout=20)
    a2 = cli.status(timeout=5)
    require(a2.completedServerTicks >= b2.completedServerTicks + 1, "observe_wait server 条件未满足")
    require(a2.completedRenderFrames >= b2.completedRenderFrames + 1, "observe_wait render 条件未满足")


def test_max_step_batch(cli: TickGateClient):
    print("\n[TEST 9] max_step_batch 限制")
    cli.cmd("set_max_step_batch 3", timeout=5)
    s = cli.status(timeout=5)
    require(s.maxStepBatch == 3, f"maxStepBatch 设置失败: {s.maxStepBatch}")

    resp = cli.cmd("step 5", timeout=5)
    require(resp.get("ok") is False, "超过 maxStepBatch 的 step 应失败")

    cli.cmd("set_max_step_batch 1000000", timeout=5)


def test_stats(cli: TickGateClient):
    print("\n[TEST 10] stats telemetry")
    st = cli.cmd("stats", timeout=5)
    require(st.get("ok") is True, "stats 返回失败")
    require("commands" in st and st["commands"] > 0, "stats commands 无效")
    require("verbs" in st and isinstance(st["verbs"], dict), "stats verbs 无效")


def benchmark_cadence(cli: TickGateClient, cadences: list[int], rounds: int, ticks: int):
    print("\n[BENCH] renderCadence 对比")
    rows = []

    for cadence in cadences:
        cli.cmd("pause", timeout=5)
        cli.cmd(f"set_render_cadence {cadence}", timeout=5)

        start = time.perf_counter()
        for _ in range(rounds):
            cli.cmd(f"step_observe {ticks}", timeout=max(20, ticks * 2))
        elapsed = time.perf_counter() - start

        st = cli.cmd("stats", timeout=5)
        steps_total = rounds * ticks
        steps_per_sec = steps_total / elapsed if elapsed > 0 else 0.0
        rows.append({
            "cadence": cadence,
            "rounds": rounds,
            "ticks": ticks,
            "elapsed_sec": elapsed,
            "steps_per_sec": steps_per_sec,
            "commands": st.get("commands", 0),
            "avg_cmd_latency_ns": st.get("avgCommandLatencyNanos", 0),
        })

    print("\n[BENCH RESULT]")
    print("cadence | rounds | ticks | elapsed(s) | steps/s | avg_cmd_latency(ns)")
    for r in rows:
        print(
            f"{r['cadence']:>7} | {r['rounds']:>6} | {r['ticks']:>5} | "
            f"{r['elapsed_sec']:>9.3f} | {r['steps_per_sec']:>7.2f} | {r['avg_cmd_latency_ns']:>18}"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--ticks", type=int, default=5)
    parser.add_argument("--benchmark", action="store_true", help="run cadence benchmark")
    parser.add_argument("--bench-cadences", default="1,2,4", help="comma-separated cadence list")
    parser.add_argument("--bench-rounds", type=int, default=30)
    parser.add_argument("--bench-ticks", type=int, default=5)
    parser.add_argument("--wait-ready", action=argparse.BooleanOptionalAction, default=True, help="wait for world readiness before tests")
    parser.add_argument("--ready-timeout", type=float, default=180.0, help="timeout seconds for wait_ready")
    parser.add_argument("--puppet-host", default="127.0.0.1", help="SocketPuppet host for optional action injection")
    parser.add_argument("--puppet-port", type=int, default=0, help="SocketPuppet port; 0 disables Puppet action injection")
    args = parser.parse_args()

    cli = TickGateClient(args.host, args.port)
    puppet = None
    try:
        print("2 秒后开始测试，请切回游戏主画面（不要停在 ESC 菜单）...")
        time.sleep(2)

        cli.connect()
        if args.puppet_port:
            puppet = PuppetClient(args.puppet_host, args.puppet_port)
            puppet.connect()
            print(f"[INIT] connected Puppet: {args.puppet_host}:{args.puppet_port}")

        if args.wait_ready:
            print(f"[INIT] waiting world ready (timeout={args.ready_timeout}s)...")
            cli.cmd("wait_ready", timeout=args.ready_timeout)

        s0 = cli.status(timeout=5)
        print(
            f"[INIT] connected: paused={s0.paused}, server={s0.completedServerTicks}, "
            f"render={s0.completedRenderFrames}, worldReady={s0.worldReady}"
        )

        if args.benchmark:
            cadences = [int(x.strip()) for x in args.bench_cadences.split(",") if x.strip()]
            benchmark_cadence(cli, cadences, args.bench_rounds, args.bench_ticks)
        else:
            test_pause_freeze_server_only(cli)
            test_step_wait_server(cli, args.ticks)
            test_step_wait_client(cli, 1)
            test_step_wait_dual(cli, args.ticks)
            rollout_loop(cli, args.rounds, args.ticks)
            minestudio_like_rollout(cli, args.rounds, args.ticks, puppet)
            test_rate_consistency(cli)
            test_cadence_and_composite(cli, args.ticks)
            test_max_step_batch(cli)
            test_stats(cli)

        cli.cmd("set_render_cadence 1", timeout=5)
        cli.cmd("set_max_step_batch 1000000", timeout=5)
        cli.cmd("resume", timeout=5)
        print("\nALL TESTS PASSED")
    except Exception as e:
        print(f"\nTEST FAILED: {e}")
        print("提示：若 step_wait_server 超时，通常是你还在 ESC 菜单或未回到游戏主画面。")
        try:
            cli.cmd("set_render_cadence 1", timeout=5)
            cli.cmd("set_max_step_batch 1000000", timeout=5)
            cli.cmd("resume", timeout=5)
        except Exception:
            pass
        sys.exit(1)
    finally:
        if puppet:
            puppet.close()
        cli.close()


if __name__ == "__main__":
    main()
