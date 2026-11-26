"""Local A-share research harness. Run with python app.py --open."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time as daytime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import re
import socket
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit
import webbrowser

from astra import Reviewer, TZ, build_packet, replay_key
from engine import analyze
from forward import ForwardBook
from llm_config import offline, runtime_dir
import fundamentals
import sources
import stocks
import stock_fundamentals
from paper_service import PaperDesk, _continuous
from replay import ReplayBook
from watchlist import Watchlist


ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
VERSION = "0.4.0"


class Harness:
    def __init__(self):
        self.indices = {i["id"]: {**i, "kind": "index"} for i in sources.catalog()}
        self.watchlist = Watchlist(runtime_dir() / "watchlist.sqlite")
        self.paper = PaperDesk(runtime_dir() / "paper.sqlite", self.watchlist, self.risk_context)
        self.default = "sh000300" if "sh000300" in self.indices else next(iter(self.indices))
        self.forward = ForwardBook(runtime_dir() / "forward.sqlite")
        self.replay = ReplayBook(runtime_dir() / "replay.sqlite")
        self.collector_stop = threading.Event()
        self.ai_preference_lock = threading.Lock()
        self.reviewer = Reviewer(on_ready=self.review_completed, claim_replay=self.claim_replay)
        self.pool = ThreadPoolExecutor(6, thread_name_prefix="research-feed")
        self.snapshots = {}
        self.risk_lines = {}
        self.locks = {key: threading.Lock() for key in self.indices}

    def instrument(self, symbol):
        return self.indices.get(symbol) or self.watchlist.get(symbol)

    def quotes(self):
        selected = [s["id"] for s in self.watchlist.all()]
        pending = self.pool.submit(stocks.quotes, selected) if selected else None
        quotes = sources.quotes()
        stock_quotes = pending.result() if pending else {}
        if stock_quotes:
            self.observe_replay(stock_quotes, sources.now())
        return {**quotes, **stock_quotes}

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

    def research_inputs(self, symbol, horizon):
        index = self.instrument(symbol)
        if not index:
            raise KeyError(symbol)
        with self.locks.setdefault(symbol, threading.Lock()):
            ts, market = self.snapshots.get(symbol, (0, None))
            if market is None or time.monotonic() - ts >= 15:
                market = self._market(index)
                self.snapshots[symbol] = (time.monotonic(), market)
        analysis = analyze(market, horizon)
        if index["kind"] == "stock":
            self.risk_lines[symbol, horizon] = (market["meta"], analysis)
        return index, market, analysis

    def risk_context(self, symbols, selected, horizon, quote):
        sectors = {}
        for symbol in symbols:
            _, market = self.snapshots.get(symbol, (0, {}))
            item = next((e for e in market.get("evidence", []) if e.get("index_id") == symbol and e.get("report")), None)
            if item is None:
                stored = sources._read(sources.CACHE / f"stock-fin-{symbol}.json.gz")
                item = stored and stored["value"]
            if isinstance(item, dict) and item.get("index_id") == symbol and item.get("report", {}).get("sector"):
                sectors[symbol] = item["report"]["sector"]
        context = {"sectors": sectors}
        meta, analysis = self.risk_lines.get((selected, horizon), ({}, {}))
        origin = analysis.get("as_of")
        if (not origin or analysis.get("historical") or analysis.get("status") != "ok"
                or meta.get("history_status") != "latest" or meta.get("adjustment") != "qfq"
                or not quote or quote.get("status") not in ("live", "latest")):
            return context
        # A line expressed on yesterday's scale is unusable after an ex-rights
        # adjustment. Anchor it to the selected quote's own close or prior close.
        try:
            stamp = datetime.fromisoformat(quote["asof"])
            if stamp.tzinfo is None:
                return context
            stamp = stamp.astimezone(TZ)
            age = (stamp.date() - datetime.fromisoformat(origin).date()).days
        except (KeyError, ValueError, TypeError):
            return context
        basis = quote.get("prev_close") if age else quote.get("price")
        if (0 <= age <= 7 and basis and abs(basis - analysis["base_price"]) < .005
                and (age or stamp.time() >= daytime(15))
                and str(meta.get("asof") or "")[:10] == stamp.date().isoformat()):
            context.update(stop=analysis["strategy"]["stop"], stop_asof=origin)
        return context

    def review_completed(self, packet, review):
        try:
            self.forward.record(packet, review)
        finally:
            if review.get("replay_key"):
                self.replay.attach_review(packet["index"]["id"], review["as_of"], review["replay_key"], review, sources.now())

    def claim_replay(self, packet):
        symbol = packet["index"]["id"]
        with self.ai_preference_lock:
            return (self.replay.auto_ai() and not self.reviewer.settings.snapshot().disabled
                    and self.watchlist.get(symbol) is not None
                    and self.replay.claim_review(symbol, packet["analysis"]["as_of"], replay_key(packet), sources.now()))

    def queue_frozen_reviews(self, now, fresh=None):
        with self.ai_preference_lock:
            if not self.replay.auto_ai() or self.reviewer.settings.snapshot().disabled:
                return
            pending = {fresh["index"]["id"]: fresh} if fresh is not None else self.replay.pending_reviews(now)
            for symbol, packet in pending.items():
                if self.watchlist.get(symbol):
                    review = self.reviewer.submit_frozen(packet)
                    if review.get("replay_key"):
                        self.replay.attach_review(symbol, packet["analysis"]["as_of"], review["replay_key"], review, sources.now())

    def capture_replay(self, index, market, analysis, now, lang="zh"):
        symbol = index["id"]
        if (index["kind"] != "stock" or analysis["horizon"] != 5 or now.weekday() >= 5 or now.hour < 15
                or analysis.get("as_of") != now.date().isoformat() or not analysis.get("validation", {}).get("n")
                or not self.replay.needs_capture(symbol, now.date())):
            return
        packet = build_packet(index, market, analysis, lang=lang)
        digest = replay_key(packet)
        price = analyze({**market, "evidence": []}, 5)
        if self.replay.capture(symbol, market, price, analysis, digest, now, packet=packet):
            self.queue_frozen_reviews(now, fresh=packet)

    def observe_replay(self, quotes, now):
        if now.weekday() < 5 and _continuous(now):
            for symbol in self.replay.pending_symbols(now.date()).intersection(quotes):
                self.replay.observe(symbol, quotes[symbol], now)

    def replay_eligibility(self, symbol):
        meta, analysis = self.risk_lines.get((symbol, 5), ({}, {}))
        if not analysis:
            return "unknown"
        if meta.get("adjustment") != "qfq" or analysis.get("status") != "ok":
            return "history"
        if analysis.get("historical") or meta.get("history_status") != "latest":
            return "stale"
        return "ready" if analysis.get("validation", {}).get("n") else "unvalidated"

    def collect_replay(self):
        now = sources.now()
        if offline():
            return
        if now.hour >= 15 or now.time() < daytime(9, 15) or now.weekday() >= 5:
            self.queue_frozen_reviews(now)
        if now.weekday() >= 5:
            return
        watched = {s["id"] for s in self.watchlist.all()}
        if _continuous(now):
            pending = self.replay.pending_symbols(now.date()).intersection(watched)
            if pending:
                self.observe_replay(stocks.quotes(sorted(pending)), sources.now())
        elif now.hour >= 15:
            needed = []
            for symbol in sorted(watched):
                meta, model = self.risk_lines.get((symbol, 5), ({}, {}))
                if (model.get("as_of") == now.date().isoformat() and meta.get("history_status") == "latest"
                        and meta.get("adjustment") == "qfq" and not model.get("validation", {}).get("n")):
                    continue
                if self.replay.needs_capture(symbol, now.date()):
                    needed.append(symbol)
            for symbol, quote in (stocks.quotes(needed) if needed else {}).items():
                if self.collector_stop.is_set():
                    break
                if (not quote or quote.get("status") != "latest" or
                        str(quote.get("asof") or "")[:10] != now.date().isoformat()):
                    continue
                try:
                    index, market, analysis = self.research_inputs(symbol, 5)
                    self.capture_replay(index, market, analysis, sources.now())
                except KeyError:
                    if self.watchlist.get(symbol):
                        logging.exception("Closing data incomplete for %s", symbol)
                except Exception:
                    logging.exception("Could not capture closing data for %s", symbol)

    def start_replay(self):
        def run():
            while not self.collector_stop.is_set():
                try:
                    self.collect_replay()
                except Exception:
                    logging.exception("Could not collect replay data")
                if self.collector_stop.wait(300 if sources.now().hour >= 15 else 30):
                    break
        threading.Thread(target=run, name="stock-replay", daemon=True).start()

    def replay_settings(self, data):
        if not isinstance(data, dict) or data.keys() != {"auto_ai"} or type(data["auto_ai"]) is not bool:
            raise ValueError("请选择是否自动复核自选股")
        with self.ai_preference_lock:
            enabled = self.replay.set_auto_ai(data["auto_ai"])
            if not enabled:
                self.reviewer.cancel_replay_queue()
        if enabled:
            self.queue_frozen_reviews(sources.now())
        return {"auto_ai": enabled, "model_enabled": not self.reviewer.settings.snapshot().disabled}

    def research(self, symbol, horizon, lang="zh"):
        index, market, analysis = self.research_inputs(symbol, horizon)
        self.capture_replay(index, market, analysis, sources.now(), lang)
        review = self.reviewer.submit(index, market, analysis, lang=lang)
        if review.get("replay_key"):
            self.replay.attach_review(symbol, analysis["as_of"], review["replay_key"], review, sources.now())
        track = self.forward.track(symbol, horizon, market["bars"], adjustment=market["meta"].get("adjustment"))
        return dict(index=index, market=market, analysis=analysis, review=review, astra=review, forward=track,
                    generated_at=datetime.now(TZ).isoformat(timespec="seconds"))

    def paper_review(self, symbol, horizon, lang):
        self.paper.stock(symbol)
        index, market, analysis = self.research_inputs(symbol, horizon)
        with self.paper.lock:
            position = self.paper.position(symbol)
            return self.reviewer.submit(index, market, analysis, position=position, lang=lang)


class Endpoint(BaseHTTPRequestHandler):
    server_version = f"Lilac-Observer/{VERSION}"

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
        with app.paper.lock:
            if action == "remove" and symbol in app.paper.book.symbols():
                return self.respond(409, {"error": "该股票仍有模拟持仓，请平仓后再移出自选"})
            updated = app.watchlist.update(symbol, security)
        return self.respond(200, {"stocks": updated})

    def paper_request(self, app, path):
        params = parse_qs(path.query, keep_blank_values=True)
        route = path.path
        try:
            if self.command == "POST" and route in ("/api/paper/preview", "/api/paper/orders"):
                data = self.read_json(2048)
                if route.endswith("/orders"):
                    result = app.paper.order(data, confirm=True, on_fill=app.reviewer.invalidate_paper)
                else:
                    result = app.paper.order(data)
            elif self.command == "GET" and route == "/api/paper":
                result = app.paper.snapshot(params.get("symbol", [""])[0])
            elif route == "/api/paper/review":
                if self.command == "POST":
                    query = self.read_json(2048)
                    if not isinstance(query, dict):
                        raise ValueError("无效的持仓复核参数")
                else:
                    query = {k: v[0] for k, v in params.items()}
                symbol = query.get("symbol")
                app.paper.stock(symbol)
                horizon, lang = str(query.get("horizon", 5)), query.get("lang", "zh")
                if horizon not in ("1", "5", "20") or lang not in ("zh", "en"):
                    raise ValueError("无效的持仓复核参数")
                slot = (symbol, int(horizon), "paper") + (("en",) if lang == "en" else ())
                review = (app.paper_review(symbol, int(horizon), lang) if self.command == "POST"
                          else app.reviewer.get(slot))
                result = {"review": review}
            else:
                return self.respond(404, {"error": "资源不存在"})
        except ValueError as error:
            return self.respond(400, {"error": str(error)})
        return self.respond(200, result)

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
            if path.path == "/api/replay/settings":
                try:
                    return self.respond(200, app.replay_settings(self.read_json(512)))
                except ValueError as error:
                    return self.respond(400, {"error": str(error)})
            if path.path.startswith("/api/paper/"):
                return self.paper_request(app, path)
            return self.respond(404, {"error": "资源不存在"})
        if path.path == "/api/paper" or path.path.startswith("/api/paper/"):
            return self.paper_request(app, path)
        if path.path == "/api/replay":
            symbol = parse_qs(path.query).get("symbol", [""])[0]
            try:
                app.paper.stock(symbol)
            except ValueError as error:
                return self.respond(400, {"error": str(error)})
            return self.respond(200, {**app.replay.report(symbol, sources.now()), "eligibility": app.replay_eligibility(symbol),
                                      "auto_ai": app.replay.auto_ai(),
                                      "model_enabled": not app.reviewer.settings.snapshot().disabled})
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
            return self.respond(200, {"status": "ok", "service": "lilac-observer", "version": VERSION})
        if path.path == "/api/catalog":
            return self.respond(200, {"indices": list(app.indices.values()), "stocks": app.watchlist.all(), "default": app.default})
        if path.path == "/api/quotes":
            return self.respond(200, {"quotes": app.quotes()})
        if path.path in ("/api/research", "/api/review", "/api/astra"):
            params = parse_qs(path.query, keep_blank_values=True)
            index = params.get("index", [app.default])[0]
            horizon = params.get("horizon", ["5"])[0]
            lang = params.get("lang", ["zh"])[0]
            if not app.instrument(index) or horizon not in ("1", "5", "20") or lang not in ("en", "zh"):
                return self.respond(400, {"error": "请选择有效指数或先将股票加入自选，周期可选 1、5、20 日"})
            if path.path in ("/api/review", "/api/astra"):
                review = app.reviewer.get((index, int(horizon)) + (("en",) if lang == "en" else ()))
                return self.respond(200, {"review": review, "astra": review})
            try:
                result = app.research(index, int(horizon), lang)
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
    parser = argparse.ArgumentParser(description="Lilac-Observer · A 股研究台")
    parser.add_argument("--version", action="version", version=f"Lilac-Observer {VERSION}")
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
                existing = json.load(response).get("service") in ("lilac-observer", "hengjian", "astra-a-share")
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
    server.harness.start_replay()
    print("研究台已启动，可以直接访问", url, flush=True)
    print("使用期间请保留此服务窗口，按 Ctrl+C 停止服务。", flush=True)
    if args.open:
        threading.Timer(0.25, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.harness.collector_stop.set()
        server.server_close()
        server.harness.pool.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    main()
