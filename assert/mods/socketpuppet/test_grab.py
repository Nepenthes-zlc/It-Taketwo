#!/usr/bin/env python3
"""测试 grab 命令：抓取准心对准的方块到手上，方块直接消失（无破碎效果）。全自动：tp → 放块 → 对准 → grab → 验证。"""

import socket
import time
import sys
import os

HOST = "127.0.0.1"
DATA_DIR = os.path.join("run", "socketpuppet_data")
PORT_FILE = os.path.join(DATA_DIR, "port.txt")

# 固定流程坐标：玩家 tp 到此，金块放在正前方一格
PLAYER_X, PLAYER_Y, PLAYER_Z = 1000, 64, 1000
BLOCK_X, BLOCK_Y, BLOCK_Z = 1001, 64, 1000  # 玩家面前一格


def get_port():
    if not os.path.exists(PORT_FILE):
        print("Error: run/socketpuppet_data/port.txt not found.")
        print("Make sure the mod is running and has initialized.")
        sys.exit(1)
    try:
        with open(PORT_FILE, "r") as f:
            return int(f.read().strip())
    except ValueError:
        print("Error: Invalid port number in port.txt")
        sys.exit(1)


class SmartClient:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.socket = None
        self.connected = False

    def connect(self):
        while not self.connected:
            try:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.settimeout(5.0)
                self.socket.connect((self.host, self.port))
                self.connected = True
                print(f"Connected to {self.host}:{self.port}")
                self._flush_buffer()
            except ConnectionRefusedError:
                print("Connection refused. Retrying in 2 seconds...")
                time.sleep(2)
            except Exception as e:
                print(f"Connection error: {e}")
                time.sleep(2)

    def _flush_buffer(self):
        try:
            self.socket.settimeout(0.1)
            while True:
                data = self.socket.recv(4096)
                if not data:
                    break
        except socket.timeout:
            pass
        except Exception:
            pass
        finally:
            self.socket.settimeout(5.0)

    def send(self, command, wait_for_response=False):
        if not self.connected:
            self.connect()
        try:
            if wait_for_response:
                self._flush_buffer()
            self.socket.sendall((command + "\n").encode("utf-8"))
            print(f"  Sent: {command}")
            if wait_for_response:
                data = self.socket.recv(4096).decode("utf-8").strip()
                return data
            return None
        except socket.timeout:
            print("  (timeout waiting for response)")
            return None
        except BrokenPipeError:
            print("Connection lost.")
            self.connected = False
            return None

    def close(self):
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
        self.connected = False


def main():
    port = get_port()
    client = SmartClient(HOST, port)
    client.connect()

    try:
        print("\n--- Grab 全自动测试（需开启作弊）---")
        print(f"  流程: tp → 放金块 ({BLOCK_X},{BLOCK_Y},{BLOCK_Z}) → 对准 → grab → 验证\n")

        # 1. 传送到固定位置，面向金块将放置的方向
        client.send(f"cmd tp @s {PLAYER_X} {PLAYER_Y} {PLAYER_Z} 0 0")
        time.sleep(0.5)

        # 2. 在面前放金块（replace 无破坏效果）
        client.send(f"cmd setblock {BLOCK_X} {BLOCK_Y} {BLOCK_Z} minecraft:gold_block replace")
        time.sleep(0.3)

        # 3. 对准方块中心，5 格内，0.5 秒平滑
        cx, cy, cz = BLOCK_X + 0.5, BLOCK_Y + 0.5, BLOCK_Z + 0.5
        client.send(f"aim {cx} {cy} {cz} 5 180 0.5")
        time.sleep(0.7)

        # 4. 抓取（方块应直接消失，无破碎动画）
        res = client.send("grab", wait_for_response=True)
        print(f"  Grab: {res}")
        time.sleep(0.2)

        # 5. 验证该格已为空气
        block_res = client.send(f"get_block {BLOCK_X} {BLOCK_Y} {BLOCK_Z}", wait_for_response=True)
        print(f"  get_block: {block_res}")
        if block_res and "air" in block_res.lower():
            print("  验证: 通过，该格已为空气。\n")
        else:
            print("  验证: 未通过（仍非空气或超时）。\n")

        print("Test finished. Disconnecting...")
    finally:
        client.close()


if __name__ == "__main__":
    main()
