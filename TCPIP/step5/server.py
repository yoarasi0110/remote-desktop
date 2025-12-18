import socket
import json
import base64
import os
import cv2
import numpy as np
from pynput import keyboard    # 用 pynput 捕捉鍵盤事件
import threading

SERVER_IP = "0.0.0.0"
SERVER_PORT = 6000
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ======================================================
# JSON 傳送
# ======================================================
def send_json(sock, data):
    sock.sendall((json.dumps(data) + "\n").encode("utf-8"))


# ======================================================
# 安全接收 JSON（處理 TCP 黏包 / 拆包）
# ======================================================
def recv_json_line(conn, buffer):
    while True:
        if "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            return line, buffer
        chunk = conn.recv(4096).decode("utf-8")
        if not chunk:
            return None, buffer
        buffer += chunk


# ======================================================
# 滑鼠 callback（傳回比例座標）
# ======================================================
mouse_norm = None
disp_w, disp_h = 1, 1

def mouse_callback(event, x, y, flags, param):
    global mouse_norm, disp_w, disp_h
    if event == cv2.EVENT_LBUTTONDOWN:
        nx = x / disp_w
        ny = y / disp_h
        mouse_norm = (nx, ny)
        print(f"[SERVER] 點擊顯示座標 ({x},{y}) → 比例座標 ({nx:.3f}, {ny:.3f})")


# ======================================================
# 鍵盤模式
# ======================================================
keyboard_mode = False      # 按下 ` 進入鍵盤輸入模式
keyboard_buffer = ""       # 可一次輸入多個字再送出
conn_global = None         # 提供 listener 使用（避免 UnboundLocalError）

def on_press(key):
    global keyboard_mode, keyboard_buffer, conn_global

    # ───────────────────────────────────────────
    # 切換鍵盤模式（按下 `）
    # ───────────────────────────────────────────
    try:
        if key.char == '`':
            keyboard_mode = not keyboard_mode
            print(f"[SERVER] 鍵盤模式 → {keyboard_mode}")
            return
    except:
        pass

    # ───────────────────────────────────────────
    # 若鍵盤模式沒開 → 忽略所有輸入
    # ───────────────────────────────────────────
    if not keyboard_mode:
        return

    # ───────────────────────────────────────────
    # 處理文字鍵
    # ───────────────────────────────────────────
    try:
        ch = key.char
        keyboard_buffer += ch
        print(f"[SERVER] 輸入中：{keyboard_buffer}")
        return
    except:
        pass

    # ───────────────────────────────────────────
    # 特殊鍵：SPACE
    # ───────────────────────────────────────────
    if key == keyboard.Key.space:
        keyboard_buffer += " "
        print(f"[SERVER] 輸入中：{keyboard_buffer}")
        return

    # ───────────────────────────────────────────
    # ENTER → 送出整段文字
    # ───────────────────────────────────────────
    if key == keyboard.Key.enter:
        if keyboard_buffer.strip() != "":
            send_json(conn_global, {
                "type": "keyboard",
                "text": keyboard_buffer
            })
            print(f"[SERVER] >>> 已送出文字：{keyboard_buffer}")
        keyboard_buffer = ""
        return

    # ───────────────────────────────────────────
    # BACKSPACE
    # ───────────────────────────────────────────
    if key == keyboard.Key.backspace:
        keyboard_buffer = keyboard_buffer[:-1]
        print(f"[SERVER] 輸入中：{keyboard_buffer}")
        return


# ======================================================
# 啟動鍵盤監聽（獨立執行緒）
# ======================================================
def start_keyboard_listener():
    listener = keyboard.Listener(on_press=on_press)
    listener.start()


# ======================================================
# 主程式
# ======================================================
def main():
    global mouse_norm, disp_w, disp_h, conn_global

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((SERVER_IP, SERVER_PORT))
    sock.listen(1)

    print(f"[SERVER] 等待 Client 連線 {SERVER_IP}:{SERVER_PORT} ...")
    conn, addr = sock.accept()
    conn_global = conn     # 提供給鍵盤 listener 使用
    print(f"[SERVER] Client 已連線：{addr}")

    # 啟動全域鍵盤監聽
    start_keyboard_listener()

    buffer = ""
    full_frame = None

    while True:

        cmd = input("[指令] open / screenshot / shutdown / stream > ").strip()

        # ======================================================
        # STREAM 模式
        # ======================================================
        if cmd == "stream":
            send_json(conn, {"type": "stream_start"})
            print("[SERVER] 進入串流模式（按 Q 離開）")

            win_name = "Remote Desktop (Differential Stream)"
            cv2.namedWindow(win_name, cv2.WINDOW_NORMAL)

            while True:

                line, buffer = recv_json_line(conn, buffer)
                if not line:
                    print("[SERVER] Client 離線")
                    return

                line = line.strip()
                if not line:
                    continue

                try:
                    msg = json.loads(line)
                except:
                    print("[SERVER] ⚠ 壞掉 JSON → 忽略")
                    continue

                if "type" not in msg:
                    print("[SERVER] 非 frame 訊息 →", msg)
                    continue

                mtype = msg["type"]

                if mtype == "frame_full":
                    imgdata = base64.b64decode(msg["data"])
                    jpg = np.frombuffer(imgdata, dtype=np.uint8)
                    full_frame = cv2.imdecode(jpg, cv2.IMREAD_COLOR)

                elif mtype == "frame_patch":
                    x, y, w, h = msg["pos"]
                    imgdata = base64.b64decode(msg["data"])
                    jpg = np.frombuffer(imgdata, dtype=np.uint8)
                    patch = cv2.imdecode(jpg, cv2.IMREAD_COLOR)
                    full_frame[y:y+h, x:x+w] = patch

                if full_frame is not None:
                    frame_h, frame_w = full_frame.shape[:2]
                    target_w = 1280
                    scale = target_w / frame_w
                    target_h = int(frame_h * scale)

                    show = cv2.resize(full_frame, (target_w, target_h))
                    disp_w, disp_h = show.shape[1], show.shape[0]

                    cv2.imshow(win_name, show)
                    cv2.setMouseCallback(win_name, mouse_callback)

                # 滑鼠事件
                if mouse_norm is not None:
                    nx, ny = mouse_norm
                    send_json(conn, {
                        "type": "mouse_click",
                        "nx": nx,
                        "ny": ny
                    })
                    print(f"[SERVER] 已送出 mouse_click({nx:.3f}, {ny:.3f})")
                    mouse_norm = None

                if cv2.waitKey(1) & 0xFF == ord('q'):
                    cv2.destroyAllWindows()
                    send_json(conn, {"type": "stream_stop"})
                    break
            continue

        # ======================================================
        # 一般指令
        # ======================================================
        parts = cmd.split(" ", 1)

        if parts[0] == "open":
            if len(parts) < 2:
                print("用法：open <檔案路徑>")
                continue
            msg = {"type": "open", "path": parts[1]}

        elif parts[0] == "screenshot":
            msg = {"type": "screenshot"}

        elif parts[0] == "shutdown":
            msg = {"type": "shutdown"}

        elif parts[0] == "stop":
            msg = {"type": "stream_stop"}

        else:
            print("未知指令")
            continue

        send_json(conn, msg)

        line, buffer = recv_json_line(conn, buffer)
        if not line:
            print("[SERVER] client 斷線")
            break

        try:
            reply = json.loads(line)
        except:
            print("[SERVER] 回覆 JSON 壞掉")
            continue

        print("[SERVER 回覆]", reply)

    conn.close()


if __name__ == "__main__":
    main()

