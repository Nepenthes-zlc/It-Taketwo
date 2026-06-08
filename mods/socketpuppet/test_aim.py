import socket
import time
import os
import threading

# 默认端口
DEFAULT_PORT = 12345
# 数据目录路径
DATA_DIR = os.path.join("run", "socketpuppet_data")
PORT_FILE = os.path.join(DATA_DIR, "port.txt")

def get_server_port():
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
        sock.settimeout(5.0)
        while True:
            try:
                data = sock.recv(4096)
                if not data:
                    break
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
    try:
        sock.sendall((cmd + "\n").encode('utf-8'))
        print(f"Sent: {cmd}")
    except Exception as e:
        print(f"Failed to send '{cmd}': {e}")

def main():
    port = get_server_port()
    print(f"Connecting to SocketPuppet on port {port}...")

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(('localhost', port))
        print("Connected!")
        
        # 启动监听线程
        listener = threading.Thread(target=listen_for_responses, args=(s,))
        listener.daemon = True
        listener.start()
        
        # --- 测试自动瞄准 ---
        
        # 1. 放置一个目标方块 (金块)
        # 坐标是相对于玩家的，这里假设玩家附近有空地
        # 注意: setblock使用的是绝对坐标或相对坐标(~)，这里用 ~
        print("\n--- Placing target ---")
        send_command(s, "cmd setblock ~3 ~1 ~3 minecraft:gold_block")
        time.sleep(1.0)

        # 2. 尝试瞄准它 (5格内)
        print("\n--- Aiming at gold_block ---")
        send_command(s, "aim minecraft:oak_button 5 90 0.5")
        time.sleep(1.0)
        send_command(s, "use")
        
#         # 3. 放置另一个目标 (钻石块) 在身后
#         print("\n--- Placing target behind ---")
#         send_command(s, "cmd setblock ~-3 ~1 ~-3 minecraft:diamond_block")
#         time.sleep(0.5)
#
#         # 4. 尝试瞄准身后的方块 (限制视角 90度，应该失败)
#         print("\n--- Aiming behind (limited FOV) ---")
#         send_command(s, "aim diamond_block 5 90")
#         time.sleep(1.0)
#
#         # 5. 尝试瞄准身后的方块 (允许 180度，应该成功)
#         print("\n--- Aiming behind (full FOV) ---")
#         send_command(s, "aim diamond_block 5 180")
#         time.sleep(1.0)
#
#         # 6. 清理现场
#         send_command(s, "cmd setblock ~3 ~1 ~3 air")
#         send_command(s, "cmd setblock ~-3 ~1 ~-3 air")
        
        print("\nTest finished. Disconnecting...")
        s.close()

    except ConnectionRefusedError:
        print(f"Connection failed! Is Minecraft running?")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
