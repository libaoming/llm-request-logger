"""真代理模式：请求原样转发到真服务器，回复边到边传回，同时在本地存一份。

凭证照常透传但不落盘。会花真实额度，换来真实会话里的回复、token 用量和缓存读写。
"""
import gzip, http.client, json, os, threading, time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import base64
import urllib.request
from urllib.parse import unquote, urlsplit

from common import dumps, read_body, system_blocks, write_capture

# 逐跳头不转发；accept-encoding 去掉是为了让上游回不压缩的内容，抄下来的回复能直接读
HOP_BY_HOP = {"host", "connection", "proxy-connection", "proxy-authorization", "keep-alive", "te", "trailer",
              "accept-encoding", "transfer-encoding", "content-length", "upgrade"}
NO_BODY_STATUS = {204, 304}
BURST_THRESHOLD = 20
BURST_WINDOW = 2.0


class BurstGuard:
    """同一类请求短时间内反复出现（agent 配错后的重试死循环），就停止逐条落盘。"""

    def __init__(self, threshold=BURST_THRESHOLD, window=BURST_WINDOW):
        self.threshold, self.window = threshold, window
        self.seen = defaultdict(deque)
        self.suppressed = defaultdict(int)
        self.lock = threading.Lock()

    def check(self, key, now=None):
        """返回 (是否落盘, 要打印的提示或 None)。"""
        now = time.time() if now is None else now
        with self.lock:
            if len(self.seen) > 1000:  # 路径一直变的话，别让这张表无限长
                self.seen.clear()
                self.suppressed.clear()
            q = self.seen[key]
            q.append(now)
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) <= self.threshold:
                self.suppressed[key] = 0
                return True, None
            self.suppressed[key] += 1
            n = self.suppressed[key]
            if n == 1:
                return False, (f"⚠ {key} 在 {self.window:g} 秒内重复超过 {self.threshold} 次，已停止逐条落盘。"
                               "请求仍在照常转发。多半是地址、模型名或凭证配错了，agent 在无间隔重试。")
            if n % 500 == 0:
                return False, f"⚠ {key} 仍在重复，已跳过 {n} 条。"
            return False, None


def should_log(method, path):
    """只记真正产出回复的调用。数 token 这类杂务请求照常转发，但不落盘。"""
    return method == "POST" and "count_tokens" not in path and "countTokens" not in path


def open_upstream(up):
    """连上游。环境变量里配了 http:// 代理就走 CONNECT 隧道，认 NO_PROXY 和代理地址里的用户名密码。"""
    https = up.scheme == "https"
    port = up.port or (443 if https else 80)
    via = urllib.request.getproxies_environment().get("https") if https else None
    if via and not urllib.request.proxy_bypass_environment(up.hostname):
        p = urlsplit(via if "//" in via else "http://" + via)
        if p.scheme == "http":
            conn = http.client.HTTPSConnection(p.hostname, p.port or 80, timeout=600)
            auth = {}
            if p.username:
                cred = f"{unquote(p.username)}:{unquote(p.password or '')}".encode()
                auth = {"Proxy-Authorization": "Basic " + base64.b64encode(cred).decode()}
            conn.set_tunnel(up.hostname, port, headers=auth)
            return conn
        print(f"[proxy] 不支持 {p.scheme}:// 类型的上游代理，改为直连", flush=True)
    cls = http.client.HTTPSConnection if https else http.client.HTTPConnection
    return cls(up.hostname, port, timeout=600)


def summarize(env):
    req = env["request"] if isinstance(env["request"], dict) else {}
    sizes = (len(dumps(req.get("tools") or [])), len(dumps(system_blocks(req))),
             len(dumps(req.get("messages") or [])))
    u = (env.get("response") or {}).get("usage") or {}
    usage = "  ".join(f"{k.replace('_input_tokens', '')}={u[k]}" for k in
                      ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
                       "output_tokens") if k in u)
    return (f"{req.get('model', '?')}  tools {sizes[0]:,} / system {sizes[1]:,} / "
            f"messages {sizes[2]:,} 字符  {usage}")


def make_handler(upstream, out_dir, quiet=False):
    up = urlsplit(upstream)
    guard = BurstGuard()

    def say(msg):
        if not quiet:
            print(msg, flush=True)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _reply(self, status, obj=None):
            body = json.dumps(obj).encode() if obj is not None else b""
            self.send_response_only(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True

        def _relay(self):
            if self.headers.get("Origin"):
                # 命令行工具不带 Origin，带的是浏览器里的网页。不让本机上随便一个网页往这里发请求
                return self._reply(403, {"error": "browser requests are refused"})
            if self.headers.get("Upgrade"):
                # 本代理只读 HTTP。立刻回 426，agent 会马上退回普通 HTTP，不回的话它会一直挂着等
                return self._reply(426)
            body = read_body(self)
            chunks, status, stream_error, conn = [], 0, None, None
            try:
                conn = open_upstream(up)
                conn.putrequest(self.command, up.path.rstrip("/") + self.path, skip_host=True,
                                skip_accept_encoding=True)
                conn.putheader("Host", up.hostname + (f":{up.port}" if up.port else ""))
                for k, v in self.headers.items():  # 逐条转发，同名的多条头不合并
                    if k.lower() not in HOP_BY_HOP:
                        conn.putheader(k, v)
                if body:
                    conn.putheader("Content-Length", str(len(body)))
                conn.endheaders(body or None)
                resp = conn.getresponse()
            except Exception as e:
                say(f"[proxy] 上游连接失败: {e}")
                if conn:
                    conn.close()
                return self._reply(502, {"type": "error", "error": {"type": "proxy_error",
                                                                    "message": f"upstream: {e}"}})
            status = resp.status
            has_body = self.command != "HEAD" and status >= 200 and status not in NO_BODY_STATUS
            try:
                self.send_response_only(status)
                for k, v in resp.getheaders():
                    if k.lower() not in ("transfer-encoding", "connection") and (
                            k.lower() != "content-length" or not has_body):
                        self.send_header(k, v)
                if has_body:
                    self.send_header("Transfer-Encoding", "chunked")
                self.send_header("Connection", "close")
                self.end_headers()
                while has_body:
                    chunk = resp.read1(65536)
                    if not chunk:
                        if resp.length:  # 上游声明的长度没发完就断了；read1 遇到这种情况不会自己报错
                            raise http.client.IncompleteRead(b"", resp.length)
                        self.wfile.write(b"0\r\n\r\n")
                        break
                    chunks.append(chunk)
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                stream_error = "agent 提前断开了连接"
            except (http.client.HTTPException, OSError) as e:
                # 上游中途断流。这恰恰是最想留档的一轮，已收到的部分照常落盘
                stream_error = f"上游中途断开: {type(e).__name__}: {e}"
                say(f"[proxy] {stream_error}")
            finally:
                conn.close()
            self.close_connection = True

            if not should_log(self.command, self.path):
                say(f"[proxy] {self.command} {self.path.split('?')[0]} -> {status}  (杂务请求，未记录)")
                return
            ok, warn = guard.check(f"{self.command} {self.path.split('?')[0]} {status}")
            if warn:
                say(warn)
            if not ok:
                return
            raw = b"".join(chunks)
            if (resp.getheader("Content-Encoding") or "").lower() == "gzip":
                try:
                    raw = gzip.decompress(raw)
                except (OSError, EOFError):
                    pass
            if (self.headers.get("Content-Encoding") or "").lower() == "gzip":
                try:
                    body = gzip.decompress(body)
                except (OSError, EOFError):
                    pass
            try:
                req = json.loads(body)
            except ValueError:
                req = {"_unparsed": body.decode("utf8", "replace")}
            dest, env = write_capture(out_dir, "proxy", self.command, self.path, status,
                                      self.headers.items(), req, raw.decode("utf8", "replace"), stream_error)
            say(f"[proxy] {status}  {summarize(env)}\n        -> {dest}")

        do_GET = do_POST = do_HEAD = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _relay

    return Handler


def serve(port, out_dir, upstream, provider=None):
    from providers import PROVIDERS, agent_command
    if provider:
        label, upstream, _, doc = PROVIDERS[provider]
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(upstream, out_dir))
    print(f"代理已启动  http://127.0.0.1:{port}  ->  {upstream}   抓包目录 {out_dir}")
    print("凭证原样透传、不落盘。另开一个终端运行：\n")
    print("  " + agent_command(provider or "anthropic", port).replace("\n", "\n  ") + "\n")
    if provider and provider != "anthropic":
        print(f"{label}：模型名是示例，以官方文档为准 {doc}")
        print("如果平时已经在 ~/.claude/settings.json 的 env 里配好了这家服务，"
              f"把那里的 ANTHROPIC_BASE_URL 改成 http://127.0.0.1:{port} 再直接运行 claude 即可。")
    else:
        print("ENABLE_TOOL_SEARCH=true 不能省：Claude Code 发现地址不是官方的，会关掉工具按需加载，\n"
              "把全部工具定义写进请求，抓到的包就比真实的大。")
    print("用完按 Ctrl+C 停止，之后把 ANTHROPIC_BASE_URL 改回去。", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
