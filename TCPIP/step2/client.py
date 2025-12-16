import socket
import json
import base64
import os
import mss
import numpy as np
import cv2
import time
import threading

SERVER_IP = "127.0.0.1"
SERVER_PORT = 6000

streaming = False      # 是否正在串流
running = True         # 程式是否繼續執行


def send_json(sock, data):
    """將 JSON 傳送給 Server（以換行作為結尾區隔訊息）"""
    sock.sendall((json.dumps(data) + "\n").encode("utf-8"))


# ===================================================
#  串流執行緒：不斷截圖並傳送到 Server（FPS 約 5）
# ===================================================
def stream_thread(sock):
    global streaming, running

    print("[CLIENT DEBUG] stream_thread 啟動中...")

    with mss.mss() as sct:
        monitor = sct.monitors[1]    # 全螢幕

        while running:
            if streaming:
                # --- 取得原始 BGRA 影像 ---
                raw = sct.grab(monitor)

                # --- 轉成 NumPy 並複製 memory（避免殘影！！！） ---
                img = np.array(raw).copy()

                # --- 轉成 BGR（OpenCV格式） ---
                img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

                # --- 壓成 JPEG ---
                success, jpg = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 50])
                if not success:
                    continue

                encoded = base64.b64encode(jpg).decode("utf-8")

                msg = {
                    "type": "frame",
                    "data": encoded
                }
                send_json(sock, msg)

                # 控制 FPS 約 5
                time.sleep(0.18)

            else:
                time.sleep(0.05)


# ===================================================
#  處理 Server 指令
# ===================================================
def handle_command(sock, command):
    global streaming, running

    ctype = command["type"]

    # -------------------
    # open path
    # -------------------
    if ctype == "open":
        path = command["path"]
        try:
            os.startfile(path)
            send_json(sock, {"status": "ok", "message": "file opened"})
        except Exception as e:
            send_json(sock, {"status": "error", "message": str(e)})

    # -------------------
    # 單張 screenshot
    # -------------------
    elif ctype == "screenshot":
        with mss.mss() as sct:
            raw = sct.grab(sct.monitors[1])
            img = np.array(raw).copy()
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

        success, jpg = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        encoded = base64.b64encode(jpg).decode("utf-8")

        msg = {"type": "image", "data": encoded}
        send_json(sock, msg)

    # -------------------
    # stream start
    # -------------------
    elif ctype == "stream_start":
        streaming = True
        print("[CLIENT] Stream Start")
        send_json(sock, {"status": "ok", "message": "streaming started"})

    # -------------------
    # stream stop
    # -------------------
    elif ctype == "stream_stop":
        streaming = False
        print("[CLIENT] Stream Stop")
        send_json(sock, {"status": "ok", "message": "streaming stopped"})

    # -------------------
    # shutdown
    # -------------------
    elif ctype == "shutdown":
        send_json(sock, {"status": "ok", "message": "shutting down"})
        running = False
        os.system("shutdown /s /t 0")


# ===================================================
#  主程式
# ===================================================
def main():
    global running

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((SERVER_IP, SERVER_PORT))
    print("[CLIENT] 已連線到 Server")

    f = sock.makefile("r", encoding="utf-8")

    # 啟動串流執行緒
    threading.Thread(target=stream_thread, args=(sock,), daemon=True).start()

    # 不斷接收 server 的指令
    while running:
        line = f.readline()
        if not line:
            print("[CLIENT] Server 斷線")
            break

        command = json.loads(line)
        handle_command(sock, command)

    sock.close()


if __name__ == "__main__":
    main()
