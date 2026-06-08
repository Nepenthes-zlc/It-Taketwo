import socket
import time
import os
import threading

# 默认端口，如果 port.txt 不存在
DEFAULT_PORT = 12345
# 数据目录路径 (根据你的实际路径修改，这里假设在 run/socketpuppet_data)
DATA_DIR = os.path.join("run", "socketpuppet_data")
PORT_FILE = os.path.join(DATA_DIR, "port.txt")

def get_server_port():
    """尝试从 port.txt 读取端口，失败则返回默认值"""
    if os.path.exists(PORT_FILE):
        try:
            with open(PORT_FILE, "r") as f:
                port_str = f.read().strip()
                return int(port_str)
        except Exception as e:
            print(f"Error reading port file: {e}")
    else:
        print(f"Port file not found at {PORT_FILE}, using default port.")
    return DEFAULT_PORT

def listen_for_responses(sock):
    """监听并打印服务器返回的消息"""
    try:
        # 设置读取超时，避免阻塞太久
        sock.settimeout(5.0)
        while True:
            try:
                data = sock.recv(4096)
                if not data:
                    break
                # 解码并打印每一行
                messages = data.decode('utf-8').strip().split('\n')
                for msg in messages:
                    if msg:
                        print(f"[Server Response] {msg}")
            except socket.timeout:
                continue
            except Exception as e:
                print(f"Error receiving data: {e}")
                break
    except Exception as e:
        print(f"Listener thread stopped: {e}")

def send_command(sock, cmd):
    """发送指令并打印"""
    try:
        sock.sendall((cmd + "\n").encode('utf-8'))
        print(f"Sent: {cmd}")
    except Exception as e:
        print(f"Failed to send '{cmd}': {e}")

def main():
    port = get_server_port()
    print(f"Connecting to SocketPuppet on port {port}...")

    try:
        # 建立连接
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(('localhost', port))
        print("Connected!")
        
        # 启动监听线程来接收返回数据
        listener = threading.Thread(target=listen_for_responses, args=(s,))
        listener.daemon = True # 设置为守护线程，主线程退出时自动退出
        listener.start()
        
        # --- 测试方块查询 ---
        
        # 1. 查询脚下的方块 (假设玩家在地面)
        # 坐标可以根据你的实际情况修改，这里只是示例
        print("\n--- Querying blocks ---")
        send_command(s, "get_block 0 60 0")
        time.sleep(0.5)
        
        send_command(s, "get_block 1001 87 1002")
        time.sleep(0.5)

        # 2. 查询一个空气方块 (高空)
        send_command(s, "get_block 0 200 0")
        time.sleep(0.5)

        # 3. 动态放置一个方块然后查询它 (需要作弊权限)
        print("\n--- Placing and querying ---")
        send_command(s, "cmd setblock 1000 88 1002 minecraft:gold_block")
        time.sleep(0.5) # 等待执行
        send_command(s, "get_block 1000 88 1002")
        time.sleep(1.0)
        
        # 4. 清理
        send_command(s, "cmd setblock 1000 88 1002 air")
        
        print("\nTest finished. Disconnecting...")
        s.close()

    except ConnectionRefusedError:
        print(f"Connection failed! Is Minecraft running and the mod loaded?")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
