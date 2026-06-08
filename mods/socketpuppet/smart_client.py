import socket
import time
import select
import os

# 默认配置
DEFAULT_PORT = 12345
HOST = 'localhost'
DATA_DIR = os.path.join("run", "socketpuppet_data")
PORT_FILE = os.path.join(DATA_DIR, "port.txt")

class MinecraftClient:
    def __init__(self):
        self.sock = None
        self.port = self._get_port()

    def _get_port(self):
        if os.path.exists(PORT_FILE):
            try:
                with open(PORT_FILE, 'r') as f:
                    return int(f.read().strip())
            except:
                pass
        return DEFAULT_PORT

    def connect(self):
        print(f"Connecting to {HOST}:{self.port}...")
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((HOST, self.port))
        # 设置超时时间，防止 recv 卡死
        self.sock.settimeout(2.0) 
        print("Connected!")

    def close(self):
        if self.sock:
            self.sock.close()

    def _flush_input(self):
        """
        清空缓冲区里积压的旧消息。
        在发送新指令前调用这个，可以防止读到上一次指令的残留回复。
        """
        try:
            # 使用 select 检查是否有数据可读，超时为 0 (非阻塞)
            while True:
                ready = select.select([self.sock], [], [], 0.0)
                if ready[0]:
                    data = self.sock.recv(4096)
                    if not data: break # 连接断开
                    # print(f"(Debug) Ignored stale data: {data}")
                else:
                    break
        except Exception:
            pass

    def send(self, cmd, wait_for_response=False):
        """
        发送指令。
        :param cmd: 指令字符串
        :param wait_for_response: 是否等待服务器回复。
                                  对于 w, a, s, d 这种不回消息的指令设为 False。
                                  对于 get_block, aim 这种会回消息的指令设为 True。
        :return: 服务器的回复 (如果 wait_for_response=True)，否则 None
        """
        if not self.sock:
            print("Error: Not connected")
            return None

        # 1. 发送前先清空旧消息，确保收到的是针对这条指令的回复
        self._flush_input()

        # 2. 发送指令
        try:
            # print(f"Sending: {cmd}")
            self.sock.sendall((cmd + "\n").encode('utf-8'))
        except Exception as e:
            print(f"Send Error: {e}")
            return None

        # 3. 如果不需要回复，直接返回
        if not wait_for_response:
            return None

        # 4. 如果需要回复，尝试读取
        try:
            # 因为设置了 settimeout，如果服务器迟迟不回，这里会抛出 timeout 异常
            data = self.sock.recv(4096)
            if not data:
                print("Server closed connection.")
                return None
            
            response = data.decode('utf-8').strip()
            return response
            
        except socket.timeout:
            print(f"Warning: Timed out waiting for response to '{cmd}'")
            return None
        except Exception as e:
            print(f"Receive Error: {e}")
            return None

def main():
    client = MinecraftClient()
    try:
        client.connect()

        # 场景 1: 发送不需要回复的指令 (wait_for_response=False)
        print(">>> Walking forward (no response expected)")
        client.send("w 1", wait_for_response=False)
        time.sleep(1)

        # 场景 2: 发送需要回复的指令 (wait_for_response=True)
        print(">>> Querying block (response expected)")
        # 假设查询脚下
        res = client.send("get_block ~ ~-1 ~", wait_for_response=True)
        print(f"Result: {res}")

        # 场景 3: 自动瞄准 (aim 会返回 SUCCESS 或 FAIL)
        print(">>> Aiming (response expected)")
        res = client.send("aim gold_block 10", wait_for_response=True)
        print(f"Aim Result: {res}")

        # 场景 4: 抓取方块 (grab 会返回 SUCCESS 或 FAIL)
        # 注意: 这会移除你面前的方块!
        print(">>> Grabbing block (response expected)")
        res = client.send("grab", wait_for_response=True)
        print(f"Grab Result: {res}")

        # 场景 5: 查询手持物品
        print(">>> Querying hand item (response expected)")
        res = client.send("get_hand", wait_for_response=True)
        print(f"Hand Item: {res}")
        
        # 场景 6: 清空物品栏
        print(">>> Clearing inventory (response expected)")
        res = client.send("clear_inv", wait_for_response=True)
        print(f"Clear Result: {res}")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        client.close()

if __name__ == "__main__":
    main()
