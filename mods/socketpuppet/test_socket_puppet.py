import socket
import time
import os
import sys

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
        print("Connected! Recording should have started automatically.")
        
        # --- 测试序列 ---
        send_command(s, "turn 30 0 1.0")
        time.sleep(1.5)
        send_command(s, "turn 30 0 1.0")
        time.sleep(1.5)
        send_command(s, "turn 30 0 1.0")
        time.sleep(1.5)

        send_command(s, "turn -30 0 1.0")
        time.sleep(1.5)
        send_command(s, "turn -30 0 1.0")
        time.sleep(1.5)


        send_command(s, "turn 0 -30 1.0")
        time.sleep(1.5)
        send_command(s, "turn 0 -30 1.0")
        time.sleep(1.5)
        send_command(s, "turn 0 -30 1.0")
        time.sleep(1.5)

        send_command(s, "turn 0 30 1.0")
        time.sleep(1.5)
        send_command(s, "turn 0 30 1.0")
        time.sleep(1.5)
        send_command(s, "turn 0 30 1.0")
        time.sleep(1.5)
        # 1. 向前走 2 秒
        send_command(s, "w 5.0")
        time.sleep(2.0)

        # 2. 向右平移 1 秒
        send_command(s, "d 1.0")
        time.sleep(1.0)

        # 3. 跳跃一次
        send_command(s, "jump")
        time.sleep(0.5)

        # 4. 旋转视角 (Yaw=90, Pitch=0) - 面向西方
        send_command(s, "look 30 0")
        time.sleep(1.0)

        # 5. 挥手 (左键攻击)
        send_command(s, "attack")
        time.sleep(0.5)

        # 6. 打开物品栏
        send_command(s, "inventory")
        time.sleep(1.0)

        # 7. 关闭物品栏 (再次发送 inventory 或者 e)
        send_command(s, "inventory")
        time.sleep(1.0)

        # 8. 停止所有动作并重置视角
        send_command(s, "stop")

        print("Test sequence finished. Disconnecting...")
        
        # 断开连接，这将触发模组端的 stopRecording()
        s.close()
        print("Disconnected. Recording should have stopped.")

    except ConnectionRefusedError:
        print(f"Connection failed! Is Minecraft running and the mod loaded?")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
