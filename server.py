import socket
import json
import base64
import os
import cv2
import numpy as np

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
disp_w, disp_h = 1, 1     # 避免除以 0

def mouse_callback(event, x, y, flags, param):
    global mouse_norm, disp_w, disp_h
    if event == cv2.EVENT_LBUTTONDOWN:
        nx = x / disp_w
        ny = y / disp_h
        mouse_norm = (nx, ny)
        print(f"[SERVER] 在視窗點擊 ({x},{y}) → 比例座標 ({nx:.3f}, {ny:.3f})")


# ======================================================
# 主程式
# ======================================================
def main():
    global mouse_norm, disp_w, disp_h

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((SERVER_IP, SERVER_PORT))
    sock.listen(1)
    print(f"[SERVER] 等待 Client 連線 {SERVER_IP}:{SERVER_PORT} ...")

    conn, addr = sock.accept()
    print(f"[SERVER] Client 已連線：{addr}")

    buffer = ""
    full_frame = None

    while True:

        cmd = input("[指令] open / screenshot / shutdown / stream > ").strip()

        # ======================================================
        # STREAM 模式（差分串流 + 精準滑鼠控制）
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

                # ===== 第一張完整畫面 =====
                if mtype == "frame_full":
                    imgdata = base64.b64decode(msg["data"])
                    jpg = np.frombuffer(imgdata, dtype=np.uint8)
                    full_frame = cv2.imdecode(jpg, cv2.IMREAD_COLOR)

                # ===== 沒變化 =====
                elif mtype == "frame_none":
                    pass

                # ===== Patch 更新 =====
                elif mtype == "frame_patch":
                    x, y, w, h = msg["pos"]

                    imgdata = base64.b64decode(msg["data"])
                    jpg = np.frombuffer(imgdata, dtype=np.uint8)
                    patch = cv2.imdecode(jpg, cv2.IMREAD_COLOR)

                    if full_frame is not None:
                        full_frame[y:y+h, x:x+w] = patch

                # ===== 顯示畫面 =====
                if full_frame is not None:
                    # 自動依寬度縮放，避免畫面太大
                    frame_h, frame_w = full_frame.shape[:2]
                    target_w = 1280
                    scale = target_w / frame_w
                    target_h = int(frame_h * scale)

                    show = cv2.resize(full_frame, (target_w, target_h))
                    disp_w, disp_h = show.shape[1], show.shape[0]

                    cv2.imshow(win_name, show)
                    cv2.setMouseCallback(win_name, mouse_callback)

                # ===== 滑鼠事件傳給 Client =====
                if mouse_norm is not None:
                    nx, ny = mouse_norm
                    send_json(conn, {
                        "type": "mouse_click",
                        "nx": nx,
                        "ny": ny
                    })
                    print(f"[SERVER] 已送出 mouse_click ({nx:.3f}, {ny:.3f})")
                    mouse_norm = None

                # 按 Q 離開串流
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

        # ----- 接收回覆 -----
        line, buffer = recv_json_line(conn, buffer)
        if not line:
            print("[SERVER] Client 斷線")
            break

        try:
            reply = json.loads(line)
        except:
            print("[SERVER] ⚠ 回覆 JSON 壞掉")
            continue

        # 截圖
        if reply.get("type") == "image":
            imgdata = base64.b64decode(reply["data"])
            filepath = os.path.join(BASE_DIR, "screenshot.jpg")
            with open(filepath, "wb") as f:
                f.write(imgdata)
            print("[SERVER] 已儲存截圖：", filepath)

        else:
            print("[SERVER 回覆]", reply)

    conn.close()


if __name__ == "__main__":
    main()
