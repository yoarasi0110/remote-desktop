import socket
import json
import base64
import os
import mss
import numpy as np
import cv2
import time
import threading
import ctypes
import time

SERVER_IP = "127.0.0.1"
SERVER_PORT = 6000

streaming = False
running = True

# ======================================================
# Windows API：SendInput 滑鼠 + 鍵盤
# ======================================================
user32 = ctypes.windll.user32

# 滑鼠
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_MOVE     = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP   = 0x0004

# 鍵盤
KEYEVENTF_KEYUP = 0x0002


# ---------- ASCII → Virtual-Key Code ----------
VK_CODE = {
    'a':0x41, 'b':0x42, 'c':0x43, 'd':0x44, 'e':0x45,
    'f':0x46, 'g':0x47, 'h':0x48, 'i':0x49, 'j':0x4A,
    'k':0x4B, 'l':0x4C, 'm':0x4D, 'n':0x4E, 'o':0x4F,
    'p':0x50, 'q':0x51, 'r':0x52, 's':0x53, 't':0x54,
    'u':0x55, 'v':0x56, 'w':0x57, 'x':0x58, 'y':0x59,
    'z':0x5A,
    '0':0x30, '1':0x31, '2':0x32, '3':0x33, '4':0x34,
    '5':0x35, '6':0x36, '7':0x37, '8':0x38, '9':0x39,
    ' ':0x20,
    '\n':0x0D,    # Enter
}

def press_key(char):
    """輸入單一字元"""
    if char not in VK_CODE:
        return

    vk = VK_CODE[char]

    user32.keybd_event(vk, 0, 0, 0)            # key down
    time.sleep(0.01)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)   # key up


def type_text(text):
    """輸入整段字串"""
    print(f"[CLIENT] 鍵盤輸入：{text!r}")
    for ch in text:
        press_key(ch)
        time.sleep(0.01)


# ======================================================
# 滑鼠點擊（絕對座標，不亂飛）
# ======================================================
def click_at(x, y):
    screen_w = user32.GetSystemMetrics(0)
    screen_h = user32.GetSystemMetrics(1)

    if screen_w == 0 or screen_h == 0:
        print("[CLIENT] 無螢幕大小，無法點擊")
        return

    abs_x = int(x * 65535 / screen_w)
    abs_y = int(y * 65535 / screen_h)

    user32.mouse_event(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, abs_x, abs_y, 0, 0)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    user32.mouse_event(MOUSEEVENTF_LEFTUP,   0, 0, 0, 0)

    print(f"[CLIENT] 點擊：({x},{y})")


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

    print("[CLIENT] 差分串流啟動，等待 stream_start...")
    prev_frame = None

    with mss.mss() as sct:
        monitor = sct.monitors[1]

        while running:

            if not streaming:
                time.sleep(0.03)
                continue

            raw = sct.grab(monitor)
            frame = np.array(raw)
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

            # 第一張完整畫面
            if prev_frame is None:
                prev_frame = frame.copy()

                ok, jpg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 40])
                encoded = base64.b64encode(jpg).decode("utf-8")

                send_json(sock, {
                    "type": "frame_full",
                    "data": encoded,
                    "screen": [
                        user32.GetSystemMetrics(0),
                        user32.GetSystemMetrics(1)
                    ]
                })
                continue

            # 差分
            diff = cv2.absdiff(frame, prev_frame)
            gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
            _, th = cv2.threshold(gray, 25, 255, cv2.THRESH_BINARY)
            coords = cv2.findNonZero(th)

            if coords is None:
                send_json(sock, {"type": "frame_none"})
                prev_frame = frame
                time.sleep(0.02)
                continue

            x, y, w, h = cv2.boundingRect(coords)
            patch = frame[y:y+h, x:x+w]

            ok, jpg = cv2.imencode(".jpg", patch, [int(cv2.IMWRITE_JPEG_QUALITY), 40])
            encoded = base64.b64encode(jpg).decode("utf-8")

            send_json(sock, {
                "type": "frame_patch",
                "pos": [x, y, w, h],
                "data": encoded
            })

            prev_frame = frame
            time.sleep(0.02)


# ======================================================
# 處理從 Server 收到的指令
# ======================================================
def handle_command(sock, command):
    global streaming, running

    ctype = command["type"]

    # open
    if ctype == "open":
        try:
            os.startfile(command["path"])
            send_json(sock, {"status": "ok"})
        except Exception as e:
            send_json(sock, {"status": "error", "message": str(e)})

    # screenshot
    elif ctype == "screenshot":
        with mss.mss() as sct:
            raw = sct.grab(sct.monitors[1])
            img = np.array(raw)
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

        ok, jpg = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        encoded = base64.b64encode(jpg).decode("utf-8")
        send_json(sock, {"type": "image", "data": encoded})

    # stream 開關
    elif ctype == "stream_start":
        streaming = True
        send_json(sock, {"status": "ok"})

    elif ctype == "stream_stop":
        streaming = False
        send_json(sock, {"status": "ok"})

    # 🔥 滑鼠點擊（比例座標）
    elif ctype == "mouse_click":
        nx = command["nx"]
        ny = command["ny"]

        screen_w = user32.GetSystemMetrics(0)
        screen_h = user32.GetSystemMetrics(1)

        x = int(nx * screen_w)
        y = int(ny * screen_h)

        print(f"[CLIENT] 滑鼠：比例({nx:.3f},{ny:.3f}) → 實際({x},{y})")
        click_at(x, y)

        send_json(sock, {"status": "ok"})

    # 🔥🔥 鍵盤輸入文字 🔥🔥
    elif ctype == "keyboard":
        text = command["text"]
        type_text(text)
        send_json(sock, {"status": "ok"})

    # shutdown
    elif ctype == "shutdown":
        running = False
        send_json(sock, {"status": "ok"})
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
