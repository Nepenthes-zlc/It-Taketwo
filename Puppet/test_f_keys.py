import socket
import time
import os

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
        
        # --- 测试 F 键功能 ---
        


        print("\n--- Testing F1 (Hide GUI) ---")
        send_command(s, "f1") # 隐藏 UI
        time.sleep(2.0)
        
        print("\n--- Testing F2 (Screenshot) ---")
        send_command(s, "f2") # 在隐藏 UI 的状态下截图
        time.sleep(1.0)
        
        send_command(s, "f1") # 恢复 UI
        time.sleep(1.0)
        
        print("\nTest finished. Check your screenshots folder!")
        s.close()

    except ConnectionRefusedError:
        print(f"Connection failed! Is Minecraft running?")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
