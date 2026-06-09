#!/usr/bin/env python3
"""
测试「同一套逻辑」：默认玩家与命名假人使用完全相同的指令序列。
验证 applyMovement / applyLookAbsolute / applyTurnRelative / applyStop 对两种目标均生效。
默认静默（无动作输出）。加 -v 或 --verbose 可显示每条指令与阶段说明。
"""
import socket
import time
import os
import sys

DEFAULT_PORT = 12345
DATA_DIR = os.path.join("run", "socketpuppet_data")
PORT_FILE = os.path.join(DATA_DIR, "port.txt")
QUIET = "-v" not in sys.argv and "--verbose" not in sys.argv


def get_port():
    if os.path.exists(PORT_FILE):
        try:
            with open(PORT_FILE, "r") as f:
                return int(f.read().strip())
        except Exception as e:
            if not QUIET:
                print(f"读取端口失败: {e}")
    if not QUIET:
        print(f"未找到 {PORT_FILE}，使用默认端口 {DEFAULT_PORT}")
    return DEFAULT_PORT


def send(sock, cmd, wait=0.3):
    sock.sendall((cmd + "\n").encode("utf-8"))
    if not QUIET:
        print(f"  -> {cmd}")
    if wait > 0:
        time.sleep(wait)


def run_same_sequence(sock, agent_label, duration=0.8):
    """对当前代理执行同一套移动/视角/停止序列。agent_label 仅用于打印。"""
    if not QUIET:
        print(f"  [{agent_label}] 前移 {duration}s")
    send(sock, f"w {duration}", duration + 0.3)
    if not QUIET:
        print(f"  [{agent_label}] 左移 {duration}s")
    send(sock, f"a {duration}", duration + 0.3)
    if not QUIET:
        print(f"  [{agent_label}] 停止")
    send(sock, "stop", 0.3)
    if not QUIET:
        print(f"  [{agent_label}] 绝对视角 look 90 0")
    send(sock, "look 90 0", 0.5)
    if not QUIET:
        print(f"  [{agent_label}] 相对视角 turn 45 -10 0.5")
    send(sock, "turn 45 -10 0.5", 0.8)
    if not QUIET:
        print(f"  [{agent_label}] 后移 + 停止")
    send(sock, f"s {duration}", duration + 0.3)
    send(sock, "stop", 0.3)
    if not QUIET:
        print(f"  [{agent_label}] 跳跃一次")
    send(sock, "jump", 0.5)
    send(sock, "stop", 0.2)


def main():
    port = get_port()
    if not QUIET:
        print(f"连接 SocketPuppet localhost:{port} ...")
        print("测试：默认玩家与命名假人使用同一套指令逻辑。\n")

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("localhost", port))
        if not QUIET:
            print("已连接。观察游戏内 HUD：先以 default 执行，再以 agenta 执行相同序列。\n")

        # ---------- 2. 命名假人：完全相同的指令序列 ----------
        if not QUIET:
            print("\n========== 2. 命名假人 (agenta)，相同序列 ==========")
        send(s, "agent agenta")
        run_same_sequence(s, "agenta", duration=0.6)

        # ---------- 3. 方式二：指令前加代理名，再跑一遍短序列 ----------
        if not QUIET:
            print("\n========== 3. 前缀形式：agenta w / agenta stop ==========")
        send(s, "agenta w 0.5", 0.9)
        send(s, "agenta stop", 0.3)
        send(s, "agenta look -90 5", 0.5)
        send(s, "agenta stop", 0.2)

        # ---------- 4. 切回 default 并做一次 stop ----------
        if not QUIET:
            print("\n========== 4. 切回 default 并 stop ==========")
        send(s, "agent default")
        send(s, "stop", 0.2)

        if not QUIET:
            print("\n测试结束，断开连接。")
        s.close()

    except ConnectionRefusedError:
        print("连接被拒绝：请确认 Minecraft 已启动、已加载 SocketPuppet 并进入世界。")
    except Exception as e:
        print(f"错误: {e}")


if __name__ == "__main__":
    main()
