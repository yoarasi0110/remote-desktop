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

streaming = False
running = True


def send_json(sock, data):
    sock.sendall((json.dumps(data) + "\n").encode("utf-8"))


# ======================================================
#  差分串流執行緒（會保持等待，直到 stream_start）
# ======================================================
def stream_thread(sock):
    global streaming, running

    print("[CLIENT] 串流執行緒啟動（等待 stream_start）")

    prev = None

    with mss.mss() as sct:
        mon = sct.monitors[1]

        while running:

            if not streaming:
                time.sleep(0.02)
                continue

            raw = sct.grab(mon)
            frame = np.array(raw)[:, :, :3]
            frame = cv2.resize(frame, None, fx=0.7, fy=0.7)

            # ===== 第一張完整畫面 =====
            if prev is None:
                prev = frame.copy()
                ok, jpg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 40])
                send_json(sock, {"type": "frame_full", "data": base64.b64encode(jpg).decode()})
                continue

            # ===== 差分 =====
            diff = cv2.absdiff(frame, prev)
            gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
            _, thresh = cv2.threshold(gray, 25, 255, cv2.THRESH_BINARY)
            coords = cv2.findNonZero(thresh)

            if coords is None:
                send_json(sock, {"type": "frame_none"})
                prev = frame
                continue

            x, y, w, h = cv2.boundingRect(coords)
            patch = frame[y:y+h, x:x+w]

            ok, jpg = cv2.imencode(".jpg", patch, [int(cv2.IMWRITE_JPEG_QUALITY), 40])
            encoded = base64.b64encode(jpg).decode()

            send_json(sock, {
                "type": "frame_patch",
                "pos": [x, y, w, h],
                "data": encoded
            })

            prev = frame
            time.sleep(0.02)


# ======================================================
#  處理 server 指令
# ======================================================
def handle_command(sock, cmd):
    global streaming, running

    t = cmd["type"]

    if t == "open":
        os.startfile(cmd["path"])
        send_json(sock, {"status": "ok"})

    elif t == "screenshot":
        with mss.mss() as s:
            img = np.array(s.grab(s.monitors[1]))[:, :, :3]
        ok, jpg = cv2.imencode(".jpg", img)
        send_json(sock, {"type": "image", "data": base64.b64encode(jpg).decode()})

    elif t == "shutdown":
        send_json(sock, {"status": "ok"})
        running = False
        os.system("shutdown /s /t 0")

    elif t == "stream_start":
        streaming = True
        send_json(sock, {"status": "ok"})

    elif t == "stream_stop":
        streaming = False
        send_json(sock, {"status": "ok"})


# ======================================================
#  主程式
# ======================================================
def main():
    global running

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((SERVER_IP, SERVER_PORT))
    print("[CLIENT] 已連線到 Server")

    f = sock.makefile("r", encoding="utf-8")

    threading.Thread(target=stream_thread, args=(sock,), daemon=True).start()

    while running:
        line = f.readline()
        if not line:
            break

        try:
            cmd = json.loads(line)
            handle_command(sock, cmd)
        except json.JSONDecodeError:
            # 忽略所有不是 JSON 的資料（例如影像）
            continue

    sock.close()


if __name__ == "__main__":
    main()
