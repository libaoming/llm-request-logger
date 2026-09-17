"""端到端测试：代理的上游指向假端点，两种模式互相验证，全程不出本机。"""
import contextlib, glob, http.client, io, json, os, sys, tempfile, threading, time, unittest, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import common, diff, export, fake, proxy, report

REQ = {
    "model": "claude-test-1",
    "metadata": {"user_id": "device_" + "ab" * 32},
    "tools": [{"name": "Bash", "description": "run", "input_schema": {"type": "object"}},
              {"name": "Read", "description": "read a file " * 20, "input_schema": {"type": "object"}}],
    "system": [{"type": "text", "text": "You are a test."},
               {"type": "text", "text": "intro\n# Harness\nabc\n# Memory\ndefgh\n",
                "cache_control": {"type": "ephemeral"}}],
    "messages": [{"role": "user", "content": [{"type": "text", "text": (
        "<system-reminder>\nContents of /Users/someone/.claude/CLAUDE.md (global):\n\nrule one\n\n"
        "Contents of /Users/someone/.claude/rules/x.md (global):\n\nrule two\n</system-reminder>\n"
        "<system-reminder>\n# userEmail\nme@example.org\nmemory at projects/-Users-someone-x/\n"
        "</system-reminder>\nhello")}]}],
}


def start(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


# 开着 Clash 之类代理的机器上，urllib 会把 127.0.0.1 也送去走代理，所以测试里显式不用代理
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class OddUpstream(BaseHTTPRequestHandler):
    """专门模拟各种不正常上游的小服务。"""
    seen = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        OddUpstream.seen.append(list(self.headers.items()))
        if self.path == "/204":
            self.send_response(204)
            self.end_headers()
        elif self.path == "/cut":  # 声明 100 字节，只发 5 个就断开
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", "100")
            self.end_headers()
            self.wfile.write(b"data:")
            self.wfile.flush()
            self.connection.close()
        else:
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")


def read(path):
    with open(path) as f:
        return f.read()


def post(port, path, body, headers=None):
    r = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(),
                               headers={"Content-Type": "application/json", "Authorization": "Bearer sk-secret",
                                        **(headers or {})})
    with OPENER.open(r) as resp:
        return resp.status, resp.read().decode()


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake_dir = os.path.join(self.tmp.name, "fake")
        self.proxy_dir = os.path.join(self.tmp.name, "proxy")
        self.fake_srv, fport = start(fake.make_handler(self.fake_dir, quiet=True))
        self.proxy_srv, self.pport = start(
            proxy.make_handler(f"http://127.0.0.1:{fport}", self.proxy_dir, quiet=True))

    def tearDown(self):
        for srv in (self.fake_srv, self.proxy_srv):
            srv.shutdown()
            srv.server_close()
        self.tmp.cleanup()

    def odd_proxy(self):
        OddUpstream.seen.clear()
        up, uport = start(OddUpstream)
        px, pport = start(proxy.make_handler(f"http://127.0.0.1:{uport}", self.proxy_dir, quiet=True))
        self.addCleanup(lambda: [x.shutdown() or x.server_close() for x in (up, px)])
        return pport

    def captures(self, d, expect=0):
        """代理先把回复传完再落盘，所以要等文件出现。"""
        deadline = time.time() + 3
        while True:
            found = sorted(glob.glob(os.path.join(d, "*.json")))
            if len(found) >= expect or time.time() > deadline:
                return found
            time.sleep(0.02)

    def test_proxy_relays_and_both_sides_capture_the_same_request(self):
        status, body = post(self.pport, "/v1/messages?beta=true", REQ)
        self.assertEqual(status, 200)
        self.assertIn("message_stop", body)
        (pf,), (ff,) = self.captures(self.proxy_dir, 1), self.captures(self.fake_dir, 1)
        pe, fe = common.load(pf), common.load(ff)
        self.assertEqual(pe["request"], REQ)
        self.assertEqual(fe["request"], REQ)
        self.assertEqual(pe["mode"], "proxy")
        self.assertEqual(pe["response"]["text"], "ok")
        self.assertEqual(pe["response"]["stop_reason"], "end_turn")
        self.assertEqual(pe["response"]["usage"]["output_tokens"], 1)

    def test_credentials_never_reach_disk_but_do_reach_upstream(self):
        post(self.pport, "/v1/messages?key=QUERYSECRET&beta=true", REQ,
             {"x-goog-api-key": "GOOGSECRET", "X-Amz-Security-Token": "AMZSECRET"})
        files = self.captures(self.proxy_dir, 1) + self.captures(self.fake_dir, 1)
        self.assertEqual(len(files), 2)
        for f in files:
            raw = read(f)
            for secret in ("sk-secret", "QUERYSECRET", "GOOGSECRET", "AMZSECRET"):
                self.assertNotIn(secret, raw)
            self.assertIn("beta=true", raw)
        upstream_saw = dict((k.lower(), v) for k, v in self.fake_srv.RequestHandlerClass.received[-1])
        self.assertEqual(upstream_saw["authorization"], "Bearer sk-secret")
        self.assertEqual(upstream_saw["x-goog-api-key"], "GOOGSECRET")

    def test_duplicate_request_headers_are_not_merged(self):
        port = self.odd_proxy()
        c = http.client.HTTPConnection("127.0.0.1", port)
        c.putrequest("POST", "/ok")
        c.putheader("anthropic-beta", "a")
        c.putheader("anthropic-beta", "b")
        c.putheader("Proxy-Authorization", "Basic nope")
        c.putheader("Content-Length", "2")
        c.endheaders(b"{}")
        self.assertEqual(c.getresponse().status, 200)
        c.close()
        got = [(k.lower(), v) for k, v in OddUpstream.seen[-1]]
        self.assertEqual([v for k, v in got if k == "anthropic-beta"], ["a", "b"])
        self.assertNotIn("proxy-authorization", dict(got))

    def test_204_gets_no_chunked_body(self):
        port = self.odd_proxy()
        c = http.client.HTTPConnection("127.0.0.1", port)
        c.request("POST", "/204", body=b"{}")
        r = c.getresponse()
        self.assertEqual(r.status, 204)
        self.assertIsNone(r.getheader("Transfer-Encoding"))
        self.assertEqual(r.read(), b"")
        c.close()

    def test_upstream_cut_mid_stream_is_still_captured(self):
        port = self.odd_proxy()
        with contextlib.suppress(Exception):
            post(port, "/cut", REQ)
        (f,) = self.captures(self.proxy_dir, 1)
        env = common.load(f)
        self.assertIn("上游中途断开", env["stream_error"])
        self.assertEqual(env["request"], REQ)

    def test_browser_requests_are_refused(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            post(self.pport, "/v1/messages", REQ, {"Origin": "https://evil.example"})
        self.assertEqual(cm.exception.code, 403)
        cm.exception.close()
        time.sleep(0.2)
        self.assertEqual(self.captures(self.proxy_dir), [])

    def test_housekeeping_is_forwarded_but_not_logged(self):
        status, body = post(self.pport, "/v1/messages/count_tokens", REQ)
        self.assertEqual((status, json.loads(body)), (200, {"input_tokens": 1}))
        time.sleep(0.2)
        self.assertEqual(self.captures(self.proxy_dir), [])

    def test_upstream_path_prefix_is_kept(self):
        """Kimi、GLM 这类兼容端点的地址带路径前缀（/anthropic、/api/anthropic），转发时要拼在前面。"""
        srv, port = start(proxy.make_handler(
            f"http://127.0.0.1:{self.fake_srv.server_address[1]}/api/anthropic", self.proxy_dir, quiet=True))
        post(port, "/v1/messages", REQ)
        (ff,) = self.captures(self.fake_dir, 1)
        self.assertEqual(common.load(ff)["path"], "/api/anthropic/v1/messages")
        srv.shutdown()
        srv.server_close()

    def test_upgrade_is_refused_with_426(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            post(self.pport, "/v1/messages", REQ, {"Upgrade": "websocket"})
        self.assertEqual(cm.exception.code, 426)
        cm.exception.close()

    def test_upstream_down_gives_502_json(self):
        srv, port = start(proxy.make_handler("http://127.0.0.1:1", self.proxy_dir, quiet=True))
        with self.assertRaises(urllib.error.HTTPError) as cm:
            post(port, "/v1/messages", REQ)
        self.assertEqual(cm.exception.code, 502)
        cm.exception.close()
        srv.shutdown()
        srv.server_close()


class Analysis(unittest.TestCase):
    def test_message_attribution_names_each_injected_file(self):
        rows = dict(report.merge(report.attribute_messages(REQ)))
        self.assertIn("规则文件 /Users/someone/.claude/CLAUDE.md", rows)
        self.assertIn("规则文件 /Users/someone/.claude/rules/x.md", rows)
        self.assertIn("账号邮箱", rows)
        self.assertEqual(rows["你输入的内容"], len("\nhello"))
        self.assertEqual(sum(rows.values()), len(REQ["messages"][0]["content"][0]["text"]) - 1)

    def test_sections_and_tool_ranking(self):
        a = report.analyze({"request": REQ, "response": None})
        self.assertEqual(a["tools"][0][0], "Read")
        self.assertEqual(dict(a["sections"])["# Memory"], len("# Memory") + len("\ndefgh\n"))

    def test_diff_reports_full_prefix_when_second_turn_only_appends(self):
        turn2 = json.loads(json.dumps(REQ))
        turn2["messages"] += [{"role": "assistant", "content": "ok"}, {"role": "user", "content": "more"}]
        a, b = common.prefix_segments(REQ), common.prefix_segments(turn2)
        self.assertEqual(diff.first_divergence(a, b), (len(a), None))

    def test_user_typed_marker_text_is_not_attributed_to_injection(self):
        rows = dict(report.merge(report.attribute_messages(
            {"messages": [{"role": "user", "content": "please explain # gitStatus and Contents of foo:\nbar"}]})))
        self.assertEqual(list(rows), ["你输入的内容"])

    def test_rule_file_path_with_spaces(self):
        rows = dict(report.cut_by_markers("Contents of /Users/John Smith/.claude/CLAUDE.md (global):\n\nx", "其他"))
        self.assertIn("规则文件 /Users/John Smith/.claude/CLAUDE.md", rows)

    def test_diff_ignores_the_moving_cache_breakpoint(self):
        """Claude Code 每轮把 cache_control 挪到最新的块上，这是正常的增量命中，不能报成失效。"""
        t1 = json.loads(json.dumps(REQ))
        t1["messages"][0]["content"][0]["cache_control"] = {"type": "ephemeral"}
        t2 = json.loads(json.dumps(REQ))
        t2["messages"] += [{"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
                           {"role": "user", "content": [{"type": "text", "text": "more",
                                                         "cache_control": {"type": "ephemeral"}}]}]
        a, b = common.prefix_segments(t1), common.prefix_segments(t2)
        self.assertEqual(diff.first_divergence(a, b), (len(a), None))
        self.assertEqual(common.cache_breakpoints(t2), ["system[1]", "messages[2].content[0]"])

    def test_diff_sees_model_and_role_changes(self):
        other = json.loads(json.dumps(REQ))
        other["model"] = "claude-test-2"
        self.assertEqual(diff.first_divergence(common.prefix_segments(REQ), common.prefix_segments(other))[0], 0)
        a = {"model": "m", "messages": [{"role": "user", "content": "ok"}]}
        b = {"model": "m", "messages": [{"role": "assistant", "content": "ok"}]}
        self.assertIsNotNone(diff.first_divergence(common.prefix_segments(a), common.prefix_segments(b))[1])

    def test_diff_locates_the_changed_tool(self):
        changed = json.loads(json.dumps(REQ))
        changed["tools"][1]["description"] = "read a file!"
        a_segs = common.prefix_segments(REQ)
        i, k = diff.first_divergence(a_segs, common.prefix_segments(changed))
        self.assertEqual(a_segs[i][0], "tools[1] Read")
        self.assertEqual(a_segs[i][1][k:k + 3], " re")

    def test_provider_table_is_well_formed_and_only_anthropic_gets_tool_search(self):
        import providers
        for name, (label, url, model, doc) in providers.PROVIDERS.items():
            self.assertTrue(url.startswith("https://") and not url.endswith("/"), name)
            self.assertTrue(doc.startswith("https://"), name)
            cmd = providers.agent_command(name, 8787)
            self.assertIn("ANTHROPIC_BASE_URL=http://127.0.0.1:8787", cmd)
            self.assertEqual("ENABLE_TOOL_SEARCH" in cmd, name == "anthropic", name)
            self.assertEqual("ANTHROPIC_AUTH_TOKEN" in cmd, name != "anthropic", name)

    def test_burst_guard_stops_after_threshold_then_recovers(self):
        g = proxy.BurstGuard(threshold=3, window=2.0)
        results = [g.check("POST /x 400", now=0.1 * n) for n in range(5)]
        self.assertEqual([ok for ok, _ in results], [True, True, True, False, False])
        self.assertIsNotNone(results[3][1])
        self.assertIsNone(results[4][1])
        self.assertTrue(g.check("POST /x 400", now=10.0)[0])

    def test_captures_written_in_the_same_millisecond_do_not_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            for _ in range(50):
                common.write_capture(d, "fake", "POST", "/v1/messages", 200, {}, REQ, "")
            self.assertEqual(len(os.listdir(d)), 50)

    def test_scrub_does_not_corrupt_common_words(self):
        text = common.scrub('/home/claude/p claude-opus-5 "role": "user" /home/user/x noreply@anthropic.com '
                            '-Users-johnsmith-proj /Users/johnsmith/a johnsmithson '
                            'user_' + "AB" * 32 + '_account_' + "0F" * 4 + "-" + "0F" * 2 + "-" + "0F" * 2
                            + "-" + "0F" * 2 + "-" + "0F" * 6)
        for kept in ("claude-opus-5", '"role": "user"', "noreply@anthropic.com", "johnsmithson"):
            self.assertIn(kept, text)
        for gone in ("/home/claude", "-Users-johnsmith-", "AB" * 32, "0F0F0F0F-"):
            self.assertNotIn(gone, text)

    def test_export_survives_hostile_model_ids_and_nested_private_headings(self):
        hostile = json.loads(json.dumps(REQ))
        hostile["model"] = "../escaped/kimi"
        hostile["system"][1]["text"] = ("intro\n# Harness\nvendor\n# claudeMd\nprivate\n# My Private Heading\n"
                                        "SECRET NOTES\n```\n# not a heading\n```\n# Memory\nvendor2\n")
        with tempfile.TemporaryDirectory() as d:
            cap, out = os.path.join(d, "cap"), os.path.join(d, "out")
            common.write_capture(cap, "fake", "POST", "/v1/messages", 200, {}, hostile, "")
            with contextlib.redirect_stdout(io.StringIO()):
                (dest,) = export.export_dir(cap, out)
            self.assertEqual(os.path.dirname(os.path.abspath(dest)), os.path.abspath(out))
            text = read(dest)
        self.assertNotIn("SECRET NOTES", text)
        self.assertNotIn("private", text)
        self.assertIn("vendor2", text)

    def test_full_export_is_scrubbed(self):
        with tempfile.TemporaryDirectory() as d:
            cap, out = os.path.join(d, "cap"), os.path.join(d, "out")
            common.write_capture(cap, "fake", "POST", "/v1/messages", 200, {}, REQ, fake.SSE.decode())
            with contextlib.redirect_stdout(io.StringIO()):
                (dest,) = export.export_dir(cap, out, full=True)
            text = read(dest)
        for leak in ("someone", "me@example.org", "ab" * 32):
            self.assertNotIn(leak, text)
        self.assertIn("/Users/USER/.claude/CLAUDE.md", text)


if __name__ == "__main__":
    unittest.main()
