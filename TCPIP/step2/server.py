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
#  可靠傳送 JSON
# ======================================================
def send_json(sock, data):
    sock.sendall((json.dumps(data) + "\n").encode("utf-8"))


# ======================================================
#  可靠接收一行 JSON（含黏包防護）
# ======================================================
def recv_json_line(conn, buffer):
    while True:
        # 檢查 buffer 裡是否已有完整的一行
        if "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            return line, buffer

        # 尚未收到完整 JSON → 持續接收
        chunk = conn.recv(4096).decode("utf-8")
        if not chunk:
            return None, buffer  # 連線中斷
        buffer += chunk


# ======================================================
#  主程式
# ======================================================
def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((SERVER_IP, SERVER_PORT))
    sock.listen(1)

    print(f"[SERVER] 等待 Client 連線中 {SERVER_IP}:{SERVER_PORT} ...")
    conn, addr = sock.accept()
    print(f"[SERVER] Client 已連線：{addr}")

    buffer = ""  # ← 處理黏包的關鍵

    while True:
        cmd = input("[指令] open / screenshot / shutdown / stream / stop > ").strip()

        # ==================================================
        #  STREAM 模式
        # ==================================================
        if cmd == "stream":
            send_json(conn, {"type": "stream_start"})
            print("[SERVER] 進入串流模式（按 Q 離開）")

            while True:
                line, buffer = recv_json_line(conn, buffer)
                if not line:
                    print("[SERVER] Client 離線")
                    return

                # ---------- 空字串（TCP 部分包）忽略 ----------
                if not line.strip():
                    continue

                # ---------- JSON 安全解析 ----------
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    print("[SERVER] ⚠ 收到不完整 JSON，已忽略")
                    continue

                # ---------- 一般回覆（不是影像 frame） ----------
                if msg.get("type") != "frame":
                    print("[SERVER 回覆]", msg)
                    continue

                # ---------- FRAME ----------
                imgdata = base64.b64decode(msg["data"])
                jpg = np.frombuffer(imgdata, dtype=np.uint8)
                frame = cv2.imdecode(jpg, cv2.IMREAD_COLOR)

                # 修正殘影、縮小顯示
                frame = cv2.resize(frame, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)

                cv2.imshow("Remote Desktop", frame)

                if cv2.waitKey(1) & 0xFF == ord("q"):
                    cv2.destroyAllWindows()
                    send_json(conn, {"type": "stream_stop"})
                    break

            continue  # 不進入下方一般指令處理

        # ==================================================
        #  一般指令（open / screenshot / shutdown / stop）
        # ==================================================
        parts = cmd.split(" ", 1)

        if parts[0] == "open":
            if len(parts) < 2:
                print("open 使用方式：open <檔案路徑>")
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

        # 送出指令
        send_json(conn, msg)

        # 等待回覆
        line, buffer = recv_json_line(conn, buffer)
        if not line:
            print("[SERVER] Client 已斷線")
            break

        if not line.strip():
            continue

        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            print("[SERVER] ⚠ 收到不完整 JSON，已忽略")
            continue

        # ------------------- screenshot image -------------------
        if msg.get("type") == "image":
            imgdata = base64.b64decode(msg["data"])
            filepath = os.path.join(BASE_DIR, "screenshot.jpg")

            with open(filepath, "wb") as f:
                f.write(imgdata)

            print("[SERVER] 已儲存截圖：", filepath)

        else:
            print("[SERVER 回應]", msg)

    conn.close()


if __name__ == "__main__":
    main()
