import socket
import time

HOST = "127.0.0.1"
PORT = 25575


def send(cmd: str, timeout: float = 20.0):
    with socket.create_connection((HOST, PORT), timeout=5) as s:
        s.settimeout(timeout)
        s.sendall((cmd + "\n").encode("utf-8"))
        data = s.recv(4096).decode("utf-8", "ignore").strip()
        print(f"{cmd:>20} => {data}")
        return data


if __name__ == "__main__":
    print("2秒后开始测试，请切回游戏主画面（不要停在ESC菜单）...")
    time.sleep(2)

    send("resume", timeout=5)
    send("status", timeout=5)
    send("step_wait_server 1", timeout=20)
    send("status", timeout=5)
    send("step_wait_client 1", timeout=10)
    send("status", timeout=5)
