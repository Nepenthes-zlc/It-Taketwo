import socket
import time
import sys
import re

# Configuration
HOST = '127.0.0.1'
PORT = 0 # Will be read from file

def get_port():
    try:
        with open('run/socketpuppet_data/port.txt', 'r') as f:
            return int(f.read().strip())
    except FileNotFoundError:
        print("Error: run/socketpuppet_data/port.txt not found.")
        print("Make sure the mod is running and has initialized.")
        sys.exit(1)
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
                self.socket.settimeout(5.0) # 5 seconds timeout
                self.socket.connect((self.host, self.port))
                self.connected = True
                print(f"Connected to {self.host}:{self.port}")
                # Consume any welcome message or initial buffer if necessary
                self.flush_buffer()
            except ConnectionRefusedError:
                print("Connection refused. Retrying in 2 seconds...")
                time.sleep(2)
            except Exception as e:
                print(f"Connection error: {e}")
                time.sleep(2)

    def flush_buffer(self):
        """Read and discard any pending data in the buffer."""
        try:
            self.socket.settimeout(0.1)
            while True:
                data = self.socket.recv(4096)
                if not data: break
        except socket.timeout:
            pass
        except Exception as e:
            print(f"Error flushing buffer: {e}")
        finally:
            self.socket.settimeout(5.0) # Restore timeout

    def send(self, command, wait_for_response=False):
        if not self.connected:
            self.connect()
        
        try:
            # Clear buffer before sending to ensure response matches command
            if wait_for_response:
                self.flush_buffer()

            print(f"Sending: {command}")
            self.socket.sendall((command + "\n").encode('utf-8'))
            
            if wait_for_response:
                try:
                    response = self.socket.recv(4096).decode('utf-8').strip()
                    return response
                except socket.timeout:
                    return "TIMEOUT"
            return None
        except BrokenPipeError:
            print("Connection lost. Reconnecting...")
            self.connected = False
            self.socket.close()
            return self.send(command, wait_for_response)
        except Exception as e:
            print(f"Send error: {e}")
            return None

    def close(self):
        if self.socket:
            self.socket.close()

def main():
    global PORT
    PORT = get_port()
    client = SmartClient(HOST, PORT)
    
    try:
        print("\n--- Testing Aim Pos ---")
        time.sleep(1.0)

        # Test 1: Aim at decimal coordinates
        target_x = 5.5
        target_y = 60.5
        target_z = 5.5
        
        print(f"Test 1: Aiming at decimal coords {target_x} {target_y} {target_z} (Dist 10, Angle 360, Time 1.0s)")
        res = client.send(f"aim {target_x} {target_y} {target_z} 10 360 1.0", wait_for_response=True)
        print(f"Response: {res}")
        time.sleep(1.5)

        # Test 2: Aim at another decimal coord
        target_x = 0.2
        target_y = 65.8
        target_z = 0.2
        
        print(f"Test 2: Aiming at decimal coords {target_x} {target_y} {target_z} (Dist 10, Angle 360, Time 0.5s)")
        res = client.send(f"aim {target_x} {target_y} {target_z} 10 360 0.5", wait_for_response=True)
        print(f"Response: {res}")
        time.sleep(1.0)

        # Test 3: Aim with max_angle constraint
        print("\n--- Test 3: Aim with Max Angle ---")
        # Reset look to 0 0
        client.send("look 0 0", wait_for_response=False)
        time.sleep(0.5)
        
        # Player at roughly (0, 60, 0) looking South (+Z). Target behind (-Z) at (0, 60, -10).
        # This is ~180 degrees.
        
        # Try with max_angle=90 (Should FAIL)
        print("Attempting 180 degree turn with max_angle=90 (Should FAIL)...")
        res = client.send("aim 0 60 -10 100 90 0.5", wait_for_response=True)
        print(f"Response: {res}")
        if "FAIL" in res and "Angle" in res:
            print("Pass: Correctly rejected due to angle.")
        else:
            print("Fail: Should have been rejected.")

        time.sleep(1)

        # Try with max_angle=180 (Should SUCCESS)
        print("Attempting 180 degree turn with max_angle=180 (Should SUCCESS)...")
        res = client.send("aim 0 60 -10 100 180 0.5", wait_for_response=True)
        print(f"Response: {res}")
        if "SUCCESS" in res:
            print("Pass: Aim successful.")
        else:
            print("Fail: Should have succeeded.")


    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        client.close()

if __name__ == "__main__":
    main()
