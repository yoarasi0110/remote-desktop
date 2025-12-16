import socket
import json
import base64
import os
import mss
import numpy as np
import cv2
import time
import threading
import ctypes   # 使用 Win32 API 點擊

SERVER_IP = "127.0.0.1"
SERVER_PORT = 6000

streaming = False
running = True

# ======================================================
# Windows API：SendInput 滑鼠點擊
# ======================================================
user32 = ctypes.windll.user32

# 按鍵代碼
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

def click_at(x, y):
   #在 (x, y) 執行滑鼠點擊

    screen_w = user32.GetSystemMetrics(0)
    screen_h = user32.GetSystemMetrics(1)

    if screen_w == 0 or screen_h == 0:
        print("[CLIENT] 無法取得螢幕大小")
        return

    # 轉換成 0~65535 絕對座標
    abs_x = int(x * 65535 / screen_w)
    abs_y = int(y * 65535 / screen_h)

    # 移動到指定位置
    user32.mouse_event(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, abs_x, abs_y, 0, 0)

    # 點擊
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    user32.mouse_event(MOUSEEVENTF_LEFTUP,   0, 0, 0, 0)

    print(f"[CLIENT] 已點擊：({x},{y})")


# ======================================================
# 傳送 JSON
# ======================================================
def send_json(sock, data):
    sock.sendall((json.dumps(data) + "\n").encode("utf-8"))


# ======================================================
# 差分串流執行緒
# ======================================================
def stream_thread(sock):
    global streaming, running

    print("[CLIENT] 差分串流執行緒啟動，等待 stream_start...")
    prev_frame = None

    with mss.mss() as sct:
        monitor = sct.monitors[1]  # 主螢幕

        while running:

            if not streaming:
                time.sleep(0.03)
                continue

            # ---- 截圖 ----
            raw = sct.grab(monitor)
            frame = np.array(raw)
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

            # ---- 第一張完整畫面 ----
            if prev_frame is None:
                prev_frame = frame.copy()

                ok, jpg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 40])
                encoded = base64.b64encode(jpg).decode("utf-8")

                send_json(sock, {
                    "type": "frame_full",
                    "data": encoded,

                    # 保留解析度資訊（server 現在不一定需要，但放著沒關係）
                    "screen": [
                        user32.GetSystemMetrics(0),
                        user32.GetSystemMetrics(1)
                    ]
                })
                continue

            # ---- 差分 ----
            diff = cv2.absdiff(frame, prev_frame)
            gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
            _, thresh = cv2.threshold(gray, 25, 255, cv2.THRESH_BINARY)
            coords = cv2.findNonZero(thresh)

            if coords is None:
                send_json(sock, {"type": "frame_none"})
                prev_frame = frame
                time.sleep(0.02)
                continue

            x, y, w, h = cv2.boundingRect(coords)
            patch = frame[y:y+h, x:x+w]

            ok, jpg = cv2.imencode(".jpg", patch, [int(cv2.IMWRITE_JPEG_QUALITY), 40])
            if not ok:
                prev_frame = frame
                continue

            encoded = base64.b64encode(jpg).decode("utf-8")

            send_json(sock, {
                "type": "frame_patch",
                "pos": [x, y, w, h],
                "data": encoded
            })

            prev_frame = frame
            time.sleep(0.02)


# ======================================================
# 指令處理
# ======================================================
def handle_command(sock, command):
    global streaming, running

    ctype = command["type"]

    # ---------- open ----------
    if ctype == "open":
        try:
            os.startfile(command["path"])
            send_json(sock, {"status": "ok"})
        except Exception as e:
            send_json(sock, {"status": "error", "message": str(e)})

    # ---------- screenshot ----------
    elif ctype == "screenshot":
        with mss.mss() as sct:
            raw = sct.grab(sct.monitors[1])
            img = np.array(raw)
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

        ok, jpg = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        encoded = base64.b64encode(jpg).decode("utf-8")

        send_json(sock, {"type": "image", "data": encoded})

    # ---------- stream_start ----------
    elif ctype == "stream_start":
        print("[CLIENT] stream_start → streaming=True")
        streaming = True
        send_json(sock, {"status": "ok"})

    # ---------- stream_stop ----------
    elif ctype == "stream_stop":
        print("[CLIENT] stream_stop → streaming=False")
        streaming = False
        send_json(sock, {"status": "ok"})

    # --------------------------------------------------
    # 比例座標滑鼠點擊
    # --------------------------------------------------
    elif ctype == "mouse_click":
        nx = command["nx"]
        ny = command["ny"]

        screen_w = user32.GetSystemMetrics(0)
        screen_h = user32.GetSystemMetrics(1)

        # 換算成實際座標
        x = int(nx * screen_w)
        y = int(ny * screen_h)

        print(f"[CLIENT] 比例({nx:.3f},{ny:.3f}) → 轉換({x},{y})")

        click_at(x, y)

        send_json(sock, {"status": "ok"})

    # ---------- shutdown ----------
    elif ctype == "shutdown":
        send_json(sock, {"status": "ok"})
        running = False
        os.system("shutdown /s /t 0")


# ======================================================
# 主程式
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
            print("[CLIENT] Server 離線")
            break

        line = line.strip()
        if not line:
            continue

        try:
            command = json.loads(line)
        except:
            print("[CLIENT] 壞掉 JSON → 忽略")
            continue

        if "type" in command:
            handle_command(sock, command)

    sock.close()


if __name__ == "__main__":
    main()


