import socket
import json
import base64
import os
import mss                 # ← 使用 mss
import numpy as np         # ← mss 截圖後用 numpy
import cv2                 # ← 壓成 JPEG

SERVER_IP = "127.0.0.1"
SERVER_PORT = 6000

def send_json(sock, data):
    sock.sendall((json.dumps(data) + "\n").encode("utf-8"))

def handle_command(sock, command):
    ctype = command["type"]

    # ========================
    # 1. 開啟檔案
    # ========================
    if ctype == "open":
        path = command["path"]
        try:
            os.startfile(path)
            send_json(sock, {"status": "ok", "message": "file opened"})
        except Exception as e:
            send_json(sock, {"status": "error", "message": str(e)})

    # ========================
    # 2. 單張截圖（mss 版本）
    # ========================
    elif ctype == "screenshot":
        with mss.mss() as sct:
            monitor = sct.monitors[1]       # 全螢幕
            img = np.array(sct.grab(monitor))[:, :, :3]  # 取 RGB

        # 轉成 JPEG 格式（比 PNG 小很多）
        success, jpeg = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        if not success:
            send_json(sock, {"status": "error", "message": "JPEG encode failed"})
            return

        # base64 編碼送回 server
        encoded = base64.b64encode(jpeg).decode("utf-8")

        msg = {
            "type": "image",
            "data": encoded
        }
        send_json(sock, msg)

    # ========================
    # 3. 關機
    # ========================
    elif ctype == "shutdown":
        send_json(sock, {"status": "ok", "message": "shutting down"})
        os.system("shutdown /s /t 0")


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((SERVER_IP, SERVER_PORT))
    print("[CLIENT] 已連線到 Server")

    f = sock.makefile("r", encoding="utf-8")

    while True:
        line = f.readline()
        if not line:
            print("[CLIENT] Server 斷線")
            break

        command = json.loads(line)
        handle_command(sock, command)

    sock.close()


if __name__ == "__main__":
    main()
