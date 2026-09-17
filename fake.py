"""假端点模式：请求不出本机，落盘后回一个合法的 SSE 回复，让 CLI 正常收场。不花额度，不碰凭证。"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from common import read_body, redact_path, write_capture

SSE = b"""event: message_start
data: {"type":"message_start","message":{"id":"msg_x","type":"message","role":"assistant","model":"m","content":[],"stop_reason":null,"stop_sequence":null,"usage":{"input_tokens":1,"output_tokens":1}}}

event: content_block_start
data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"ok"}}

event: content_block_stop
data: {"type":"content_block_stop","index":0}

event: message_delta
data: {"type":"message_delta","delta":{"stop_reason":"end_turn","stop_sequence":null},"usage":{"output_tokens":1}}

event: message_stop
data: {"type":"message_stop"}

"""


def make_handler(out_dir, quiet=False):
    class Handler(BaseHTTPRequestHandler):
        received = []  # 最近收到的请求头，只在内存里，给测试核对「凭证确实传到了上游」用

        def log_message(self, *a):
            pass

        def _json(self, obj):
            r = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(r)))
            self.end_headers()
            self.wfile.write(r)

        def do_POST(self):
            if self.headers.get("Origin"):
                self.send_response(403)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            body = read_body(self)
            Handler.received.append(list(self.headers.items()))
            del Handler.received[:-20]
            if "count_tokens" in self.path:
                return self._json({"input_tokens": 1})
            try:
                req = json.loads(body)
            except ValueError:
                req = {"_unparsed": body.decode("utf8", "replace")}
            dest, _ = write_capture(out_dir, "fake", "POST", self.path, 200, self.headers.items(), req,
                                    SSE.decode())
            if not quiet:
                print(f"[fake] {redact_path(self.path)} -> {dest} ({len(body):,} bytes)", flush=True)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(SSE)

        def do_GET(self):
            self._json({})

        def do_HEAD(self):
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

    return Handler


def serve(port, out_dir):
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(out_dir))
    print(f"""假端点已启动  http://127.0.0.1:{port}   抓包目录 {out_dir}
请求不会离开本机。另开一个终端运行：

  mkdir -p /tmp/clean_cfg /tmp/workdir && cd /tmp/workdir
  CLAUDE_CONFIG_DIR=/tmp/clean_cfg ANTHROPIC_API_KEY=sk-dummy \\
  ANTHROPIC_BASE_URL=http://127.0.0.1:{port} ENABLE_TOOL_SEARCH=true \\
  CLAUDE_CODE_DISABLE_LEGACY_MODEL_REMAP=1 \\
    claude -p "hi" --model claude-opus-5

Ctrl+C 停止。""", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
