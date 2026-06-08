#!/usr/bin/env python3
"""
双假人：无规律移动 + 轮流 /spectate 切换视角（与「谁先动」同步轮流）。

前提
----
1) Carpet 等已生成与 DUMMY_A / DUMMY_B 同名的假人；spawn 逻辑同前。
2) SocketPuppet 单槽位移：同一时刻只积累一个命名代理的移动，故两人仍须「轮流」发移动。
3) /spectate 通常要求执行者已是旁观者；若无效可先在游戏里切旁观者，或传 --enter-spectator（会对你
   本体执行 gamemode spectator，慎用）。

用法
----
  py -3 test_two_dummies_move.py
  py -3 test_two_dummies_move.py --skip-spawn -n 50
  py -3 test_two_dummies_move.py --enter-spectator   # 开局把你切旁观者便于 spectate

环境变量 PUPPET_SPAWN_CMD_A / PUPPET_SPAWN_CMD_B 同前。
"""
import argparse
import os
import random
import socket
import sys
import time

DEFAULT_PORT = 12345
DATA_DIR = os.path.join("run", "socketpuppet_data")
PORT_FILE = os.path.join(DATA_DIR, "port.txt")

DUMMY_A = "PuppetBotA"
DUMMY_B = "PuppetBotB"

# 随机移动：时长范围（秒）
DUR_MIN = 0.12
DUR_MAX = 0.52
# spectate 后给客户端一帧时间附着相机
SPECTATE_SETTLE_MIN = 0.22
SPECTATE_SETTLE_MAX = 0.55


def get_port():
    if os.path.exists(PORT_FILE):
        try:
            with open(PORT_FILE, "r") as f:
                return int(f.read().strip())
        except OSError:
            pass
    msg = f"[WARN] port file missing, using default {DEFAULT_PORT}: {PORT_FILE}"
    print(msg, file=sys.stderr, flush=True)
    try:
        print(f"未找到 {PORT_FILE}，使用默认端口 {DEFAULT_PORT}", file=sys.stderr, flush=True)
    except UnicodeEncodeError:
        pass
    return DEFAULT_PORT


def send(sock, cmd, wait=0.0):
    sock.sendall((cmd + "\n").encode("utf-8"))
    print(f"  -> {cmd}", flush=True)
    if wait > 0:
        time.sleep(wait)


def spawn_dummies(sock):
    cmd_a = os.environ.get("PUPPET_SPAWN_CMD_A", f"player {DUMMY_A} spawn").strip()
    cmd_b = os.environ.get("PUPPET_SPAWN_CMD_B", f"player {DUMMY_B} spawn").strip()
    print("spawning dummies via cmd (Carpet /player ...) ...", flush=True)
    send(sock, f"cmd {cmd_a}", 0.6)
    send(sock, f"cmd {cmd_b}", 0.6)
    send(sock, f"cmd gamemode survival {DUMMY_A}", 0.35)
    send(sock, f"cmd gamemode survival {DUMMY_B}", 0.35)
    print("if spawn fails: check Carpet, cheats, bot name rules.\n", flush=True)


def spectate(sock, dummy_name):
    """原版: /spectate <目标>，一般需在旁观者模式下。"""
    settle = random.uniform(SPECTATE_SETTLE_MIN, SPECTATE_SETTLE_MAX)
    send(sock, f"cmd spectate {dummy_name}", settle)


def random_move_line(dummy_name):
    """返回 (socket 行, 建议 sleep 秒)。无规律：方向、时长、偶尔跳跃或 stop。"""
    r = random.random()
    if r < 0.08:
        return f"{dummy_name} stop", random.uniform(0.08, 0.2)
    if r < 0.22:
        dur = random.uniform(0.18, 0.42)
        return f"{dummy_name} jump {dur}", dur + random.uniform(0.08, 0.2)
    move = random.choice(["w", "s", "a", "d"])
    dur = random.uniform(DUR_MIN, DUR_MAX)
    tail = dur + random.uniform(0.06, 0.2)
    return f"{dummy_name} {move} {dur}", tail


def chaotic_round(sock, first_dummy, second_dummy):
    """
    一轮内：先观战 first 并让其乱动，再观战 second 并让其乱动。
    first_dummy / second_dummy 每轮交替为 A/B，实现视线与移动的轮流。
    """
    spectate(sock, first_dummy)
    line, w = random_move_line(first_dummy)
    send(sock, line, w)

    # 小概率多蹭一步同一人，打破完全对称
    if random.random() < 0.18:
        line2, w2 = random_move_line(first_dummy)
        send(sock, line2, w2)

    spectate(sock, second_dummy)
    line, w = random_move_line(second_dummy)
    send(sock, line, w)

    if random.random() < 0.14:
        line2, w2 = random_move_line(second_dummy)
        send(sock, line2, w2)

    # 轮与轮之间的无规律停顿
    time.sleep(random.uniform(0.02, 0.28))


def parse_args():
    p = argparse.ArgumentParser(description="双假人无规律移动 + 轮流 spectate")
    p.add_argument("--skip-spawn", action="store_true", help="不发送 spawn / gamemode")
    p.add_argument("-n", "--cycles", type=int, default=0, help="轮数，0=无限")
    p.add_argument(
        "--enter-spectator",
        action="store_true",
        help="开局 cmd gamemode spectator（仅本地玩家），便于 /spectate 附着假人",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=None,
        help="随机种子，便于复现；默认每次不同",
    )
    return p.parse_args()


def main():
    print("[test_two_dummies_move] starting (use: py -3 script.py if python shows nothing)", flush=True)
    args = parse_args()
    if args.seed is not None:
        random.seed(args.seed)
        print(f"random seed = {args.seed}", flush=True)

    port = get_port()
    print(f"connecting localhost:{port} ...", flush=True)

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("localhost", port))
    except ConnectionRefusedError:
        err = (
            "ERROR: connection refused. Start Minecraft, enter a world, SocketPuppet must listen. "
            "Also try: py -3 .\\test_two_dummies_move.py"
        )
        print(err, file=sys.stderr, flush=True)
        try:
            print("连接被拒绝：请确认游戏已启动、已进入世界且 SocketPuppet 已监听。", file=sys.stderr, flush=True)
        except UnicodeEncodeError:
            pass
        sys.exit(1)

    try:
        if not args.skip_spawn:
            spawn_dummies(s)
        else:
            print("skip-spawn: movement only.\n", flush=True)

        if args.enter_spectator:
            print("enter-spectator: gamemode spectator for @s ...", flush=True)
            send(s, "cmd gamemode spectator @s", random.uniform(0.35, 0.6))

        n = args.cycles
        i = 0
        print("chaotic moves + alternating spectate A/B (Ctrl+C stop) ...", flush=True)
        while True:
            # 轮流：偶数轮先 A 后 B，奇数轮先 B 后 A（视线与「谁先动」一起换）
            if i % 2 == 0:
                chaotic_round(s, DUMMY_A, DUMMY_B)
            else:
                chaotic_round(s, DUMMY_B, DUMMY_A)
            i += 1
            if n > 0 and i >= n:
                print(f"done {n} rounds, stop both.", flush=True)
                send(s, f"{DUMMY_B} stop", 0.1)
                send(s, f"{DUMMY_A} stop", 0.1)
                break
    except KeyboardInterrupt:
        print("\ninterrupt: stop both dummies ...", flush=True)
        try:
            send(s, f"{DUMMY_B} stop", 0.05)
            send(s, f"{DUMMY_A} stop", 0.05)
        except OSError:
            pass
    finally:
        s.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        print("FATAL:", repr(ex), file=sys.stderr, flush=True)
        sys.exit(1)
