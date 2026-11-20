"""Local A-share research harness. Run with python app.py --open."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import socket
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit
import webbrowser

from astra import Reviewer, TZ
from engine import analyze
from forward import ForwardBook
from llm_config import runtime_dir
import fundamentals
import sources
import stocks
import stock_fundamentals
from watchlist import Watchlist


ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
VERSION = "0.1.0"


class Harness:
    def __init__(self):
        self.indices = {i["id"]: {**i, "kind": "index"} for i in sources.catalog()}
        self.watchlist = Watchlist(runtime_dir() / "watchlist.sqlite")
        self.default = "sh000300" if "sh000300" in self.indices else next(iter(self.indices))
        self.forward = ForwardBook(runtime_dir() / "forward.sqlite")
        self.reviewer = Reviewer(on_ready=self.forward.record)
        self.pool = ThreadPoolExecutor(6, thread_name_prefix="research-feed")
        self.snapshots = {}
        self.locks = {key: threading.Lock() for key in self.indices}

    def instrument(self, symbol):
        return self.indices.get(symbol) or self.watchlist.get(symbol)

    def quotes(self):
        selected = [s["id"] for s in self.watchlist.all()]
        pending = self.pool.submit(stocks.quotes, selected) if selected else None
        quotes = sources.quotes()
        return {**quotes, **(pending.result() if pending else {})}

    def _market(self, security):
        symbol = security["id"]
        if security["kind"] == "stock":
            financial_future = self.pool.submit(stock_fundamentals.evidence, security)
            tape = self.pool.submit(sources.minute_tape, symbol) if stocks.resolve(symbol) else None
            filings = self.pool.submit(sources.company_filings, symbol)
            context = self.pool.submit(sources.public_evidence)
            market = dict(stocks.market(symbol, watched=security))
            general, statuses = context.result()
            announcements, filing_status = filings.result()
            market["meta"] = {**market["meta"], **statuses, "filings_status": filing_status}
            market["evidence"] = list(market.get("evidence") or []) + announcements + general
            market["intraday"] = tape.result() if tape else {"date": None, "points": [], "status": "unavailable"}
            sector_exposure = stock_fundamentals.sector_exposure
            missing = "未取得本公司可用财报，已跳过财报因子"
        else:
            financial_future = self.pool.submit(fundamentals.evidence, symbol)
            market = dict(sources.market(symbol))
            sector_exposure = fundamentals.sector_exposure
            missing = "未取得成份股财报，已跳过财报因子"
        market["id"] = symbol
        market["kind"] = security["kind"]
        market["index"] = security
        market["meta"] = {**market["meta"], "instrument_type": security["kind"]}
        financial = financial_future.result()
        if financial:
            market["evidence"] = [financial, *(sector_exposure(e, financial) if e.get("sector_yoy") else e
                                               for e in market["evidence"])]
        else:
            market["meta"]["warnings"] = list(market["meta"].get("warnings") or []) + [missing]
        return market

    def research(self, symbol, horizon):
        index = self.instrument(symbol)
        if not index:
            raise KeyError(symbol)
        with self.locks.setdefault(symbol, threading.Lock()):
            ts, market = self.snapshots.get(symbol, (0, None))
            if market is None or time.monotonic() - ts >= 15:
                market = self._market(index)
                self.snapshots[symbol] = (time.monotonic(), market)
        analysis = analyze(market, horizon)
        review = self.reviewer.submit(index, market, analysis)
        track = self.forward.track(symbol, horizon, market["bars"], adjustment=market["meta"].get("adjustment"))
        return dict(index=index, market=market, analysis=analysis, review=review, astra=review, forward=track,
                    generated_at=datetime.now(TZ).isoformat(timespec="seconds"))


class Endpoint(BaseHTTPRequestHandler):
    server_version = "Hengjian/1"

    def send_bytes(self, status, body, mime):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def respond(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_bytes(status, body, "application/json; charset=utf-8")

    def do_GET(self):
        try:
            self.dispatch()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception:
            import traceback
            traceback.print_exc()
            self.respond(500, {"error": "当前数据处理失败，请稍后刷新。详情见本机服务日志。"})

    do_POST = do_GET

    def read_json(self, limit):
        try:
            size = int(self.headers.get("Content-Length", 0))
            if self.headers.get_content_type() != "application/json" or not 0 < size <= limit:
                raise ValueError
            return json.loads(self.rfile.read(size))
        except (ValueError, UnicodeError):
            raise ValueError("请提交有效的 JSON 设置") from None

    def update_watchlist(self, app):
        try:
            data = self.read_json(2048)
            symbol, action = data["id"], data["action"]
            if action not in ("add", "remove") or not re.fullmatch(r"(sh|sz|bj)\d{6}", symbol):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            return self.respond(400, {"error": "请提交有效的股票代码和自选操作"})
        security = None
        if action == "add":
            security = stocks.resolve(symbol)
            if not security or security["id"] != symbol or not security.get("listed", True) or symbol in app.indices:
                return self.respond(400, {"error": "未在 A 股上市证券目录中找到该股票"})
            security = {**security, "kind": "stock", "listed": True}
        return self.respond(200, {"stocks": app.watchlist.update(symbol, security)})

    def dispatch(self):
        path = urlsplit(self.path)
        if self.headers.get("Host", "").split(":")[0] not in ("localhost", "127.0.0.1"):
            return self.respond(403, {"error": "仅允许本机访问"})
        if path.path.startswith("/api/") and self.headers.get("Sec-Fetch-Site") == "cross-site":
            return self.respond(403, {"error": "请从本机研究台访问"})
        app = self.server.harness
        if self.command == "POST":
            origin = self.headers.get("Origin")
            if origin and origin != "http://" + self.headers["Host"]:
                return self.respond(403, {"error": "设置只能从本机研究台更改"})
            if path.path == "/api/settings":
                try:
                    settings = app.reviewer.configure(self.read_json(16384))
                except ValueError as error:
                    return self.respond(400, {"error": str(error)})
                return self.respond(200, settings)
            if path.path == "/api/watchlist":
                return self.update_watchlist(app)
            return self.respond(404, {"error": "资源不存在"})
        if path.path == "/api/settings":
            return self.respond(200, app.reviewer.settings.public())
        if path.path == "/api/search":
            query = parse_qs(path.query).get("q", [""])[0].strip()
            if len(query) > 80:
                return self.respond(400, {"error": "搜索词过长"})
            results = stocks.search(query) if query else []
            if query and not results and not stocks.directory_available():
                return self.respond(503, {"error": "证券名录暂不可用。首次使用请联网，稍后重试。"})
            return self.respond(200, {"results": results})
        if path.path == "/api/health":
            return self.respond(200, {"status": "ok", "service": "hengjian", "version": VERSION})
        if path.path == "/api/catalog":
            return self.respond(200, {"indices": list(app.indices.values()), "stocks": app.watchlist.all(), "default": app.default})
        if path.path == "/api/quotes":
            return self.respond(200, {"quotes": app.quotes()})
        if path.path in ("/api/research", "/api/review", "/api/astra"):
            params = parse_qs(path.query, keep_blank_values=True)
            index = params.get("index", [app.default])[0]
            horizon = params.get("horizon", ["5"])[0]
            if not app.instrument(index) or horizon not in ("1", "5", "20"):
                return self.respond(400, {"error": "请选择有效指数或先将股票加入自选，周期可选 1、5、20 日"})
            if path.path in ("/api/review", "/api/astra"):
                review = app.reviewer.get((index, int(horizon)))
                return self.respond(200, {"review": review, "astra": review})
            try:
                result = app.research(index, int(horizon))
            except KeyError:
                if not app.instrument(index):
                    return self.respond(404, {"error": "该股票已移出自选"})
                raise
            return self.respond(200, result)
        # Only serve immediate UI assets, never files elsewhere in the project.
        name = "index.html" if path.path == "/" else path.path.lstrip("/")
        mime = {".css": "text/css", ".js": "text/javascript", ".html": "text/html", ".svg": "image/svg+xml"}
        asset = WEB / name
        if Path(name).name == name and asset.suffix in mime and asset.is_file():
            return self.send_bytes(200, asset.read_bytes(), mime[asset.suffix] + "; charset=utf-8")
        return self.respond(404, {"error": "资源不存在"})


class LocalServer(ThreadingHTTPServer):
    def server_bind(self):
        # Windows SO_REUSEADDR permits two live listeners on the same port.
        if os.name == "nt":
            self.allow_reuse_address = False
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def main():
    parser = argparse.ArgumentParser(description="衡见 · A 股研究台")
    parser.add_argument("--version", action="version", version=f"Hengjian {VERSION}")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="在默认浏览器打开")
    args = parser.parse_args()
    url = f"http://127.0.0.1:{args.port}/"
    try:
        server = LocalServer(("127.0.0.1", args.port), Endpoint)
    except OSError:
        from urllib.request import urlopen
        try:
            with urlopen(url + "api/health", timeout=2) as response:
                existing = json.load(response).get("service") in ("hengjian", "astra-a-share")
        except Exception:
            existing = False
        if existing:
            print("研究台已经在运行，可以直接访问", url, flush=True)
            if args.open:
                print("关闭本次启动窗口不会停止已有服务。", flush=True)
                webbrowser.open(url)
            return
        sys.exit(f"Port {args.port} is unavailable. Choose another with --port.")
    server.harness = Harness()
    print("研究台已启动，可以直接访问", url, flush=True)
    print("使用期间请保留此服务窗口，按 Ctrl+C 停止服务。", flush=True)
    if args.open:
        threading.Timer(0.25, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        server.harness.pool.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    main()
