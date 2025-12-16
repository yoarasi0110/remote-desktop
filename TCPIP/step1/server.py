import socket
import json
import base64
import os

SERVER_IP = "0.0.0.0"
SERVER_PORT = 6000

# 固定儲存到 server.py 的資料夾
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def send_command(sock, cmd):
    parts = cmd.split(" ", 1)

    if parts[0] == "open":
        msg = {"type": "open", "path": parts[1]}
    elif parts[0] == "screenshot":
        msg = {"type": "screenshot"}
    elif parts[0] == "shutdown":
        msg = {"type": "shutdown"}
    else:
        print("未知指令")
        return

    sock.sendall((json.dumps(msg) + "\n").encode("utf-8"))

# 可靠接收長行 JSON
def recv_json_line(conn):
    buffer = ""
    while True:
        chunk = conn.recv(4096).decode("utf-8")
        if not chunk:
            return None

        buffer += chunk
        if "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            return line

def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((SERVER_IP, SERVER_PORT))
    sock.listen(1)

    print(f"[SERVER] 等待 Client 連線中 {SERVER_IP}:{SERVER_PORT} ...")
    conn, addr = sock.accept()
    print(f"[SERVER] Client 已連線：{addr}")

    while True:
        cmd = input("[指令] open / screenshot / shutdown > ")
        send_command(conn, cmd)

        response = recv_json_line(conn)
        if not response:
            print("[SERVER] Client 已斷線")
            break

        msg = json.loads(response)

        if msg.get("type") == "image":
            print("[SERVER] 收到截圖，正在儲存到目錄：", os.getcwd())

            imgdata = base64.b64decode(msg["data"])
            filepath = os.path.join(BASE_DIR, "screenshot.jpg")

            with open(filepath, "wb") as f2:
                f2.write(imgdata)
            print("[SERVER] 已儲存：", filepath)

        else:
            print("[SERVER 回應]", msg)

    conn.close()


if __name__ == "__main__":
    main()
