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
#  傳送 JSON
# ======================================================
def send_json(sock, data):
    sock.sendall((json.dumps(data) + "\n").encode("utf-8"))


# ======================================================
#  可靠接收（處理 TCP 黏包 / 拆包）
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
#  主程式
# ======================================================
def main():
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

        # ==================================================
        #  STREAM 模式（差分串流）
        # ==================================================
        if cmd == "stream":
            send_json(conn, {"type": "stream_start"})
            print("[SERVER] 進入差分串流模式（按 Q 離開）")

            while True:
                line, buffer = recv_json_line(conn, buffer)
                if not line:
                    print("[SERVER] Client 離線")
                    return

                line = line.strip()
                if not line:
                    continue

                # ---------- 安全解析 ----------
                try:
                    msg = json.loads(line)
                except:
                    print("[SERVER] ⚠ 收到不完整 JSON，忽略")
                    continue

                # ---------- 若不是影像 frame ----------
                if "type" not in msg:
                    print("[SERVER 回覆]", msg)
                    continue

                # ==================================================
                #  處理 Full frame（第一張畫面）
                # ==================================================
                if msg["type"] == "frame_full":
                    imgdata = base64.b64decode(msg["data"])
                    jpg = np.frombuffer(imgdata, dtype=np.uint8)
                    full_frame = cv2.imdecode(jpg, cv2.IMREAD_COLOR)

                # ==================================================
                #  沒變動 → 不更新畫面
                # ==================================================
                elif msg["type"] == "frame_none":
                    pass

                # ==================================================
                #  Patch（變動區域）
                # ==================================================
                elif msg["type"] == "frame_patch":
                    x, y, w, h = msg["pos"]

                    imgdata = base64.b64decode(msg["data"])
                    jpg = np.frombuffer(imgdata, dtype=np.uint8)
                    patch = cv2.imdecode(jpg, cv2.IMREAD_COLOR)

                    if full_frame is not None:
                        full_frame[y:y+h, x:x+w] = patch

                # ==================================================
                #  顯示完整畫面
                # ==================================================
                if full_frame is not None:
                    show = cv2.resize(full_frame, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
                    cv2.imshow("Remote Desktop (Differential Stream)", show)

                # 按 Q 離開串流
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    cv2.destroyAllWindows()
                    send_json(conn, {"type": "stream_stop"})
                    break

            continue

        # ==================================================
        #  一般指令（open / screenshot / shutdown / stop）
        # ==================================================
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

        # 傳送指令到 client
        send_json(conn, msg)

        # 等回覆
        line, buffer = recv_json_line(conn, buffer)
        if not line:
            print("[SERVER] Client 已斷線")
            break

        try:
            reply = json.loads(line)
        except:
            print("[SERVER] ⚠ 回覆 JSON 解析失敗")
            continue

        # screenshot 回傳圖片
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
