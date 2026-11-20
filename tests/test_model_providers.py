from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

from astra import Reviewer, _ask, _packet
from llm_config import ModelSettings


ANSWER = {"posture": "wait", "summary": "观察", "risk": "波动", "refs": ["M", "E99"]}
INDEX = {"id": "sh000300", "kind": "index"}
MARKET = {"evidence": [], "meta": {"quote_status": "latest", "history_status": "latest"}}
ANALYSIS = {"status": "ok", "horizon": 5, "strategy": {"action": "观察"}, "as_of": "2026-11-19"}


@contextmanager
def endpoint(answer=ANSWER, redirect=False):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, self.headers.get("Authorization"), body))
            if redirect:
                self.send_response(302)
                self.send_header("Location", "/other")
                self.end_headers()
                return
            payload = {"choices": [{"message": {"content": json.dumps(answer, ensure_ascii=False)}}]}
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())

        def do_GET(self):
            requests.append((self.path, self.headers.get("Authorization"), None))
            self.send_error(405)

        def log_message(self, *args):
            pass

    with HTTPServer(("127.0.0.1", 0), Handler) as service:
        worker = threading.Thread(target=service.serve_forever, kwargs={"poll_interval": .03})
        worker.start()
        try:
            yield f"http://127.0.0.1:{service.server_port}/v1", requests
        finally:
            service.shutdown()
            worker.join()


class Models(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "model-settings.json"
        affected = ("LILAC_OBSERVER_", "HENGJIAN_", "ASTRA_", "http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")
        env = {k: v for k, v in os.environ.items() if not k.startswith(affected)}
        env["NO_PROXY"] = "127.0.0.1,localhost"
        patcher = patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_key_scope_and_persistence(self):
        base = "https://example.com/v1"
        os.environ.update(HENGJIAN_PROVIDER="api", HENGJIAN_API_MODEL="original",
                          HENGJIAN_API_BASE_URL=base, HENGJIAN_API_KEY=secrets.token_hex(16))
        settings = ModelSettings(self.path)
        self.assertEqual(settings.public()["key_source"], "environment")
        settings.update({"provider": "api", "api_model": "another"})
        self.assertNotIn(os.environ["HENGJIAN_API_KEY"], self.path.read_text())
        new_key = secrets.token_hex(16)
        public = settings.update({"provider": "api", "api_key": new_key})
        self.assertNotIn(new_key, json.dumps(public))
        reloaded = ModelSettings(self.path)
        reloaded.update({"provider": "off"})
        reloaded.update({"provider": "api", "api_key": ""})
        self.assertEqual(reloaded.snapshot().api_key, new_key)
        reloaded.update({"provider": "api", "base_url": "https://other.example/v1"})
        self.assertFalse(reloaded.public()["has_api_key"])
        reloaded.update({"provider": "api", "base_url": base, "clear_api_key": True})
        self.assertFalse(reloaded.public()["has_api_key"])

    def test_new_prefix_overrides_without_forwarding_legacy_key(self):
        os.environ.update(HENGJIAN_PROVIDER="off", HENGJIAN_API_MODEL="old",
                          HENGJIAN_API_BASE_URL="https://old.example/v1", HENGJIAN_API_KEY=secrets.token_hex(16),
                          LILAC_OBSERVER_PROVIDER="api", LILAC_OBSERVER_API_MODEL="new",
                          LILAC_OBSERVER_API_BASE_URL="https://new.example/v1",
                          ASTRA_ENABLED="0", LILAC_OBSERVER_ENABLED="1", LILAC_OBSERVER_OFFLINE="0")
        config = ModelSettings(self.path).snapshot()
        self.assertEqual((config.provider, config.model, config.api_key, config.disabled), ("api", "new", "", False))
        os.environ["LILAC_OBSERVER_API_KEY"] = secrets.token_hex(16)
        settings = ModelSettings(self.path)
        self.assertEqual(settings.snapshot().api_key, os.environ["LILAC_OBSERVER_API_KEY"])
        settings.update({"provider": "api", "base_url": os.environ["HENGJIAN_API_BASE_URL"]})
        self.assertFalse(settings.public()["has_api_key"])

    def test_invalid_inputs_preserve_file(self):
        settings = ModelSettings(self.path)
        settings.update({"provider": "codex", "codex_model": "example"})
        before = self.path.read_bytes()
        for fields in [{"provider": "unknown"}, {"provider": "api", "api_model": ""},
                       {"provider": "api", "base_url": "http://not-local.example/"},
                       {"provider": "off", "base_url": "https://a:b@foo.example/?key=a"},
                       {"provider": "api", "api_model": ["a"]}]:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                settings.update(fields)
            self.assertEqual(self.path.read_bytes(), before)

    def test_api_transport_and_schema(self):
        settings = ModelSettings(self.path)
        token = secrets.token_hex(16)
        with endpoint() as (url, seen):
            settings.update({"provider": "api", "base_url": url + "/chat/completions", "api_model": "local", "api_key": token})
            config = settings.snapshot()
            key, packet = _packet(INDEX, MARKET, ANALYSIS, config)
            # A configured system proxy must not receive traffic intended for
            # a private loopback model, even without an exception in NO_PROXY.
            with patch.dict(os.environ, {"NO_PROXY": "", "HTTP_PROXY": "http://127.0.0.1:1"}):
                result = _ask(packet, config)
            self.assertEqual(result["refs"], ["M"])
            self.assertEqual(seen[0][:2], ("/v1/chat/completions", "Bearer " + token))
            self.assertEqual(seen[0][2]["model"], "local")
            self.assertNotIn(token, json.dumps(seen[0][2]))
        with endpoint({"posture": "wrong"}) as (url, seen):
            settings.update({"provider": "api", "base_url": url})
            config = settings.snapshot()
            self.assertNotEqual(key, _packet(INDEX, MARKET, ANALYSIS, config)[0])
            with self.assertRaises(ValueError):
                _ask(packet, config)
            self.assertIsNone(seen[0][1])
        with endpoint(redirect=True) as (url, seen):
            settings.update({"provider": "api", "base_url": url, "api_key": token})
            with self.assertRaisesRegex(RuntimeError, "302"):
                _ask(packet, settings.snapshot())
            self.assertEqual(len(seen), 1)

    def test_inflight_provider_switch(self):
        running, release, returned = threading.Event(), threading.Event(), threading.Event()
        issued = []
        def runner(packet):
            running.set()
            release.wait(3)
            returned.set()
            return ANSWER.copy()
        r = Reviewer(self.path.with_suffix(".sqlite"), runner=runner, on_ready=lambda *args: issued.append(args))
        r.configure({"provider": "codex", "codex_model": "first"})
        r.submit(INDEX, MARKET, ANALYSIS)
        self.assertTrue(running.wait(2))
        r.configure({"provider": "off"})
        self.assertEqual(r.submit(INDEX, MARKET, ANALYSIS)["status"], "disabled")
        release.set()
        self.assertTrue(returned.wait(2))
        r.configure({"provider": "codex", "codex_model": "second"})
        r.submit(INDEX, MARKET, ANALYSIS)
        limit = time.monotonic() + 2
        while r.get((INDEX["id"], 5))["status"] != "ready" and time.monotonic() < limit:
            time.sleep(.01)
        self.assertEqual(len(issued), 1)
        self.assertEqual(issued[0][1]["model"], "second")
