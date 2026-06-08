#!/usr/bin/env python3
"""测试 look 命令：瞬间朝向与带 duration 的平滑插值。"""

import socket
import time
import sys
import os

HOST = "127.0.0.1"
DATA_DIR = os.path.join("run", "socketpuppet_data")
PORT_FILE = os.path.join(DATA_DIR, "port.txt")


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

    def send(self, command):
        if not self.connected:
            self.connect()
        try:
            self.socket.sendall((command + "\n").encode("utf-8"))
            print(f"  Sent: {command}")
        except BrokenPipeError:
            print("Connection lost.")
            self.connected = False

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
        print("\n--- 1. 瞬间 look (无 duration) ---")
        client.send("look 90 0")
        time.sleep(1)
        print("  预期: 视角立刻转到 yaw=90, pitch=0\n")

        print("--- 2. 平滑 look (duration=0.5 秒) ---")
        client.send("look 0 0 2.5")
        print("  预期: 约 0.5 秒内平滑转到 yaw=0, pitch=0")
        time.sleep(3)
        print()

        print("--- 3. 平滑 look (duration=1.0 秒) ---")
        client.send("look -90 20 2.0")
        print("  预期: 约 1 秒内平滑转到 yaw=-90, pitch=20")
        time.sleep(3.2)
        print()

        print("--- 4. 再次瞬间 look ---")
        client.send("look 180 0")
        time.sleep(0.3)
        print("  预期: 立刻转到 yaw=180, pitch=0\n")

        print("Test finished. Disconnecting...")
    finally:
        client.close()


if __name__ == "__main__":
    main()
