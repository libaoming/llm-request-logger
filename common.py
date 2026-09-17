"""两种抓包模式共用的部分：抓包文件格式、SSE 解析、脱敏、请求切段。只用标准库。"""
import json, os, re, time

PROBE_VERSION = 2

# 名字里带这些词的请求头和网址参数都当作凭证，任何模式都不落盘。
# 按词匹配而不是列白名单：Gemini 用 x-goog-api-key 和 ?key=，AWS 用 x-amz-security-token，列不全。
SECRET_NAME = re.compile(r"key|token|secret|auth|cookie|signature|credential|password", re.I)
REDACTED = "[REDACTED]"

HEX = r"(?<![0-9A-Fa-f])"
SCRUB = [
    (re.compile(r"/private/tmp/claude-\d+/[^\s`'\"\\]*"), "/tmp/workdir"),
    (re.compile(r"/(Users|home)/[A-Za-z0-9._-]+"), r"/\1/USER"),
    (re.compile(HEX + r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}(?![0-9A-Fa-f])"), "<uuid>"),
    (re.compile(HEX + r"[0-9A-Fa-f]{32,}(?![0-9A-Fa-f])"), "<hash>"),
]
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# 厂商文本里的公共地址不是个人信息，保留原样
PUBLIC_EMAIL_LOCAL = {"noreply", "no-reply", "git", "support", "security"}
HOME_USER = re.compile(r"/(?:Users|home)/([A-Za-z0-9._-]{3,})")
# 这些用户名同时是常见单词，全文替换会把 "role": "user"、claude-opus-5 这类内容改坏
COMMON_WORDS = {"user", "users", "claude", "node", "ubuntu", "runner", "admin", "dev", "root", "home",
                "shared", "guest", "test", "app", "docker", "vscode", "codespace", "work"}


def scrub(text):
    """抹掉路径、邮箱和标识。用户名还会以别的形式出现（比如路径被压成目录名 -Users-name-），
    所以从路径和 $HOME 里认出用户名之后，把它在「路径样」位置上的出现也替换掉。"""
    users = set(HOME_USER.findall(text)) | {os.path.basename(os.path.expanduser("~"))}
    users = {u for u in users if len(u) >= 3 and u.lower() not in COMMON_WORDS and u != "USER"}
    for pat, rep in SCRUB:
        text = pat.sub(rep, text)
    text = EMAIL.sub(lambda m: m.group(0) if m.group(0).split("@")[0].lower() in PUBLIC_EMAIL_LOCAL
                     else "user@example.com", text)
    for u in sorted(users, key=len, reverse=True):
        text = re.sub(r"(?<![A-Za-z0-9])" + re.escape(u) + r"(?![A-Za-z0-9])", "USER", text)
    return text


def redact_headers(headers):
    """headers 可以是 dict，也可以是 (名字, 值) 的列表。"""
    items = headers.items() if hasattr(headers, "items") else headers
    return {k: (REDACTED if SECRET_NAME.search(k) else v) for k, v in items}


def redact_path(path):
    """网址参数里的凭证（比如 ?key=...）同样不落盘。"""
    if "?" not in path:
        return path
    base, query = path.split("?", 1)
    parts = []
    for pair in query.split("&"):
        name, sep, _ = pair.partition("=")
        parts.append(f"{name}={REDACTED}" if sep and SECRET_NAME.search(name) else pair)
    return base + "?" + "&".join(parts)


def read_body(handler):
    h = handler.headers
    if "chunked" in (h.get("Transfer-Encoding") or "").lower():
        chunks = []
        while True:
            size = int(handler.rfile.readline().split(b";")[0].strip() or b"0", 16)
            if size == 0:
                handler.rfile.readline()
                break
            chunks.append(handler.rfile.read(size))
            handler.rfile.readline()
        return b"".join(chunks)
    return handler.rfile.read(int(h.get("Content-Length") or 0))


# ---------- 抓包文件 ----------

def safe_name(text):
    return re.sub(r"[^A-Za-z0-9._-]", "_", text or "unknown").strip(".") or "unknown"


def capture_name(mode, model, n=0):
    t = time.time()
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime(t)) + f"-{int(t * 1000) % 1000:03d}"
    return f"{stamp}_{mode}_{safe_name(model)}{f'-{n}' if n else ''}.json"


def write_capture(out_dir, mode, method, path, status, headers, request, response_raw, stream_error=None):
    os.makedirs(out_dir, exist_ok=True)
    env = {
        "probe_version": PROBE_VERSION,
        "mode": mode,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "method": method,
        "path": redact_path(path),
        "status": status,
        "headers": redact_headers(headers),
        "request": request,
        "response": parse_response(response_raw),
    }
    if stream_error:
        env["stream_error"] = stream_error
    model = request.get("model") if isinstance(request, dict) else None
    for n in range(1000):
        dest = os.path.join(out_dir, capture_name(mode, model, n))
        try:
            # "x"：同一毫秒里的并发请求（子 agent、重试）不能互相覆盖
            with open(dest, "x") as f:
                json.dump(env, f, ensure_ascii=False, indent=1)
            return dest, env
        except FileExistsError:
            continue
    raise OSError(f"无法在 {out_dir} 里找到可用的文件名")


def load(path):
    """读一份抓包。v2 信封、v1 的裸请求体、别的工具存下的请求体 JSON 都认。"""
    with open(path) as f:
        d = json.load(f)
    if isinstance(d, dict) and d.get("probe_version") and "request" in d:
        return d
    return {"probe_version": 0, "mode": "raw", "timestamp": None, "method": "POST", "path": None,
            "status": None, "headers": {}, "request": d, "response": None}


# ---------- 回复解析 ----------

def parse_response(raw):
    """从 SSE 流或普通 JSON 回复里取文本、停止原因和 token 用量。"""
    if not raw:
        return None
    out = {"text": "", "blocks": [], "stop_reason": None, "usage": {}, "error": None, "raw": raw}
    stripped = raw.lstrip()
    if stripped.startswith("{"):
        try:
            j = json.loads(stripped)
        except ValueError:
            return {**out, "error": raw[:500]}
        if j.get("type") == "error" or "error" in j:
            out["error"] = j.get("error")
        out["usage"] = j.get("usage") or {}
        out["stop_reason"] = j.get("stop_reason")
        content = [b for b in j.get("content") or [] if isinstance(b, dict)]
        out["text"] = "".join(b.get("text", "") for b in content)
        out["blocks"] = [b.get("type") + (f":{b['name']}" if b.get("name") else "") for b in content]
        return out
    for line in raw.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            ev = json.loads(line[5:].strip())
        except ValueError:
            continue
        kind = ev.get("type")
        if kind == "message_start":
            out["usage"].update(ev.get("message", {}).get("usage") or {})
        elif kind == "content_block_start":
            b = ev.get("content_block") or {}
            out["blocks"].append(str(b.get("type")) + (f":{b['name']}" if b.get("name") else ""))
        elif kind == "content_block_delta":
            out["text"] += ev.get("delta", {}).get("text", "")
        elif kind == "message_delta":
            out["usage"].update(ev.get("usage") or {})
            out["stop_reason"] = ev.get("delta", {}).get("stop_reason") or out["stop_reason"]
        elif kind == "error":
            out["error"] = ev.get("error")
    return out


# ---------- 请求结构 ----------

def system_blocks(req):
    s = req.get("system")
    if isinstance(s, str):
        return [{"type": "text", "text": s}]
    return s or []


def main_system_text(req):
    """最长的那个 system 块就是提示词正文，其余是计费头和一句话身份声明。"""
    return max((b.get("text", "") for b in system_blocks(req)), key=len, default="")


def iter_sections(body):
    """按一级标题切正文，返回 [(标题或 None, 文本)]。代码围栏里的 "# 注释" 不算标题。"""
    out, head, buf, fenced = [], None, [], False
    for line in body.splitlines(keepends=True):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        if not fenced and line.startswith("# ") and line.strip() != "#":
            out.append((head, "".join(buf)))
            head, buf = line.rstrip("\n"), [line[len(line.rstrip("\n")):]]
        else:
            buf.append(line)
    out.append((head, "".join(buf)))
    return [(h, t) for h, t in out if h is not None or t.strip()]


def split_sections(body):
    """返回 [(标题, 字符数)]，标题前的部分记作 (前言)。同名标题合并计数。"""
    sizes = {}
    for h, t in iter_sections(body):
        key = h.strip() if h else "(前言)"
        sizes[key] = sizes.get(key, 0) + len(h or "") + len(t)
    return list(sizes.items())


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False)


def _content(block):
    """cache_control 只是断点标记，不属于被缓存的内容。Claude Code 每轮都把它挪到最新的块上，
    带着它比较，正常的增量命中会被误判成失效。"""
    return dumps({k: v for k, v in block.items() if k != "cache_control"}) if isinstance(block, dict) else dumps(block)


def prefix_segments(req):
    """按缓存前缀的顺序（tools → system → messages）把请求切成带标签的段。换模型缓存整个失效，所以模型排最前。"""
    segs = [("model", str(req.get("model")))]
    for i, t in enumerate(req.get("tools") or []):
        segs.append((f"tools[{i}] {t.get('name', '?')}", _content(t)))
    for i, b in enumerate(system_blocks(req)):
        segs.append((f"system[{i}]", _content(b)))
    for i, m in enumerate(req.get("messages") or []):
        content = m.get("content")
        if isinstance(content, str):
            segs.append((f"messages[{i}] {m.get('role')}", f"{m.get('role')}\x00{content}"))
            continue
        for j, b in enumerate(content or []):
            kind = b.get("type") if isinstance(b, dict) else "?"
            segs.append((f"messages[{i}].content[{j}] {m.get('role')}/{kind}", f"{m.get('role')}\x00{_content(b)}"))
    return segs


def cache_breakpoints(req):
    """带 cache_control 的块的位置，单独报告，不参与前缀比较。"""
    out = [f"tools[{i}]" for i, t in enumerate(req.get("tools") or []) if t.get("cache_control")]
    out += [f"system[{i}]" for i, b in enumerate(system_blocks(req)) if b.get("cache_control")]
    for i, m in enumerate(req.get("messages") or []):
        if isinstance(m.get("content"), list):
            out += [f"messages[{i}].content[{j}]" for j, b in enumerate(m["content"])
                    if isinstance(b, dict) and b.get("cache_control")]
    return out
