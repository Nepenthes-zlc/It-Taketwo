#!/usr/bin/env python3
"""
测试 SocketPuppet 的代理/假人命名功能。
游戏内 HUD 会显示当前代理名，如 [Puppet] (default) 或 [Puppet] (agenta)。
"""
import socket
import time
import os

DEFAULT_PORT = 12345
DATA_DIR = os.path.join("run", "socketpuppet_data")
PORT_FILE = os.path.join(DATA_DIR, "port.txt")


def get_port():
    if os.path.exists(PORT_FILE):
        try:
            with open(PORT_FILE, "r") as f:
                return int(f.read().strip())
        except Exception as e:
            print(f"读取端口失败: {e}")
    print(f"未找到 {PORT_FILE}，使用默认端口 {DEFAULT_PORT}")
    return DEFAULT_PORT


def send(sock, cmd, wait=0.3):
    sock.sendall((cmd + "\n").encode("utf-8"))
    print(f"  -> {cmd}")
    if wait > 0:
        time.sleep(wait)


def main():
    port = get_port()
    print(f"连接 SocketPuppet localhost:{port} ...")

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("localhost", port))
        print("已连接。请观察游戏内 HUD 的代理名变化。\n")

        # ---------- 1. 默认玩家 (default) ----------
        print("[1] 默认玩家 (default) 操作")
        send(s, "w 1.0", 1.2)
        send(s, "stop", 0.5)

        # ---------- 2. 方式一：指令前加代理名 ----------
        print("\n[2] 使用「agenta」前缀：agenta w / agenta look ...")
        send(s, "agenta w 1.0", 1.2)
        send(s, "agenta look 45 10", 0.8)
        send(s, "agenta stop", 0.5)

        # ---------- 3. 方式二：agent <name> 后发指令 ----------
        print("\n[3] 先 agent agenta，再发指令")
        send(s, "agent agenta")
        send(s, "w 1.0", 1.2)
        send(s, "look 0 0", 0.5)
        send(s, "stop", 0.3)

        print("\n[4] 改回默认玩家：agent default")
        send(s, "agent default")
        send(s, "w 0.5", 0.8)
        send(s, "stop", 0.3)

        # ---------- 5. 再切到另一个名字 ----------
        print("\n[5] 切换为「bot1」")
        send(s, "agent bot1")
        send(s, "jump", 0.5)
        send(s, "stop", 0.3)

        print("\n测试结束，断开连接。")
        s.close()

    except ConnectionRefusedError:
        print("连接被拒绝：请确认 Minecraft 已启动且已加载 SocketPuppet 模组并进入世界。")
    except Exception as e:
        print(f"错误: {e}")


if __name__ == "__main__":
    main()
