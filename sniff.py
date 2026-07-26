#!/usr/bin/env python3
"""最小假 Anthropic API 端点：落盘请求体，回一个合法 SSE 响应让 CLI 正常收场。"""
import json, os, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

OUT = sys.argv[2] if len(sys.argv) > 2 else "/tmp/capture"
os.makedirs(OUT, exist_ok=True)
N = [0]

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

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        N[0] += 1
        path = os.path.join(OUT, f"req-{N[0]:03d}.json")
        with open(path, "wb") as f:
            f.write(body)
        print(f"[{N[0]:03d}] {self.path} -> {path} ({len(body)} bytes)", flush=True)

        if "count_tokens" in self.path:
            r = json.dumps({"input_tokens": 1}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(r))); self.end_headers()
            self.wfile.write(r); return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(SSE)

    def do_GET(self):
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.end_headers(); self.wfile.write(b"{}")

HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
