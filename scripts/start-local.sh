#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -x .venv/bin/python || ! -d frontend/node_modules ]]; then
  echo "请先安装依赖：uv sync --extra dev，并在 frontend 中运行 npm install。" >&2
  exit 1
fi

.venv/bin/python - <<'PY'
import errno
import socket
for port in (8001, 5173):
    with socket.socket() as listener:
        # Match the servers' reuse setting so recently closed sockets do not
        # appear to be another running service during a quick restart.
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(("127.0.0.1", port))
        except OSError as exc:
            if exc.errno == errno.EADDRINUSE:
                raise SystemExit(f"端口 {port} 已被占用，未启动任何服务。请先检查占用情况。")
            raise SystemExit(f"无法监听端口 {port}：{exc}。未启动任何服务。")
PY

backend_command=(.venv/bin/python -m uvicorn invest_research.api:app --host 127.0.0.1 --port 8001)
if [[ -f .env ]]; then
  backend_command+=(--env-file .env)
else
  echo "提示：未找到 .env，生成报告前请填写所需密钥。"
fi

backend_pid=""
frontend_pid=""
cleanup() {
  trap - EXIT INT TERM
  [[ -z "$frontend_pid" ]] || kill "$frontend_pid" 2>/dev/null || true
  [[ -z "$backend_pid" ]] || kill "$backend_pid" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 0' INT TERM

"${backend_command[@]}" &
backend_pid=$!
node frontend/node_modules/vite/bin/vite.js frontend --host 127.0.0.1 &
frontend_pid=$!
echo "页面：http://127.0.0.1:5173  后端：http://127.0.0.1:8001"

while kill -0 "$backend_pid" 2>/dev/null && kill -0 "$frontend_pid" 2>/dev/null; do
  sleep 1
done
echo "某个服务已退出，正在关闭本次启动的另一个服务。" >&2
exit 1
