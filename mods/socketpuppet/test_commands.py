import socket
import time
import os

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
        print("Connected! Recording started.")
        
        # --- 新功能测试 ---
        
        # 1. 发送聊天消息
        send_command(s, "chat Hello from Python script!")
        time.sleep(1.0)

        # 2. 设置时间为中午 (需要作弊权限)
        send_command(s, "cmd time set 6000")
        time.sleep(1.0)

        # 3. 设置天气为晴朗 (需要作弊权限)
        send_command(s, "cmd weather clear")
        time.sleep(1.0)

        # 4. 给予自己一个钻石 (需要作弊权限)
        # 注意: @s 在客户端执行时可能无效，建议用自己的名字，或者不带目标选择器让服务器判断
        # 这里演示给自己消息提示
        send_command(s, "cmd tellraw @s {\"text\":\"Socket command executed!\",\"color\":\"green\"}")
        time.sleep(1.0)

        # 5. 组合动作：跳跃的同时喊话
        send_command(s, "jump")
        send_command(s, "chat I am jumping!")
        time.sleep(1.0)

        # 3. 设置天气为晴朗 (需要作弊权限)
        send_command(s, "cmd tp @s 1000 1000 1000 0 0")
        time.sleep(1.0)

        # 6. 停止
        send_command(s, "stop")
        
        print("Test finished. Disconnecting...")
        s.close()

    except ConnectionRefusedError:
        print(f"Connection failed! Is Minecraft running and the mod loaded?")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
