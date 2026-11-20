"""Local model preferences. Public representations never contain credentials."""
from dataclasses import dataclass, field, replace
from ipaddress import ip_address
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
from urllib.parse import urlsplit


DEFAULT_BASE = "https://api.openai.com/v1"


def offline():
    return os.getenv("HENGJIAN_OFFLINE", os.getenv("ASTRA_OFFLINE", "")).lower() in ("1", "true", "yes")


def runtime_dir():
    configured = os.environ.get("HENGJIAN_RUNTIME_DIR")
    return Path(configured).expanduser() if configured else Path(__file__).resolve().parent / ".runtime"


def _text(value, limit, label):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(f"{label}格式无效")
    return value.strip()


def loopback_url(url):
    host = urlsplit(url).hostname
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def _base_url(value):
    url = _text(value, 2048, "API 地址").rstrip("/")
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port
    except ValueError:
        raise ValueError("API 地址格式无效") from None
    if not host or parts.username is not None or parts.password is not None or parts.query or parts.fragment:
        raise ValueError("API 地址须为不含凭据、查询参数和片段的服务地址")
    if not url.isascii() or any(c.isspace() for c in url) or "\\" in url or port == 0:
        raise ValueError("API 地址格式无效")
    if parts.scheme != "https" and not (parts.scheme == "http" and loopback_url(url)):
        raise ValueError("远程 API 请使用 HTTPS，本机回环地址可用 HTTP")
    return url.removesuffix("/chat/completions")


def _key(value):
    value = _text(value, 4096, "API 密钥")
    if not value.isascii() or any(c.isspace() for c in value):
        raise ValueError("API 密钥格式无效")
    return value


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    codex_model: str
    api_model: str
    base_url: str
    api_key: str = field(repr=False, default="")
    key_source: str = "none"

    @property
    def model(self):
        if self.provider == "codex":
            return self.codex_model or "Codex CLI 默认模型"
        return self.api_model if self.provider == "api" else ""

    @property
    def disabled(self):
        return self.provider == "off" or os.environ.get("ASTRA_ENABLED") == "0" or offline()


class ModelSettings:
    def __init__(self, path=None):
        self.path = Path(path) if path else runtime_dir() / "model-settings.json"
        self.lock = threading.RLock()
        self.warning = ""
        try:
            self.saved = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self.saved = {}
        except (ValueError, OSError):
            self.saved = {}
            self.warning = "本机模型设置无法读取，请重新保存设置。"
        try:
            self.config = self._resolve(self.saved)
        except (TypeError, ValueError, AttributeError):
            self.warning = "本机模型配置无效，请检查环境变量或重新保存设置。"
            self.saved = {}
            self.config = ModelConfig("off", "", "", DEFAULT_BASE)
        if self.warning:
            self.config = replace(self.config, provider="off")

    def _resolve(self, saved):
        if not isinstance(saved, dict):
            raise ValueError("模型配置格式无效")
        default = "codex" if shutil.which("codex") else "off"
        provider = saved.get("provider", os.getenv("HENGJIAN_PROVIDER", default))
        if provider not in ("codex", "api", "off"):
            raise ValueError("请选择 Codex、兼容 API 或关闭复核")
        codex = _text(saved.get("codex_model", os.getenv("HENGJIAN_CODEX_MODEL", os.getenv("ASTRA_MODEL", ""))), 256, "Codex 模型名")
        if codex and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/:@+-]*", codex):
            raise ValueError("请输入有效的 Codex 模型 ID，或留空使用 CLI 默认模型")
        model = _text(saved.get("api_model", os.getenv("HENGJIAN_API_MODEL", "")), 256, "API 模型名")
        env_url = os.getenv("HENGJIAN_API_BASE_URL", DEFAULT_BASE)
        base = _base_url(saved.get("base_url", env_url))
        if provider == "api" and not model:
            raise ValueError("请输入服务商提供的模型 ID")
        if "api_key" in saved:
            key = _key(saved["api_key"])
            origin = "local"
        elif os.getenv("HENGJIAN_API_KEY") and base == _base_url(env_url):
            key = _key(os.environ["HENGJIAN_API_KEY"])
            origin = "environment"
        else:
            key, origin = "", "none"
        return ModelConfig(provider, codex, model, base, key, origin if key else "none")

    def snapshot(self):
        with self.lock:
            return self.config

    def public(self):
        with self.lock:
            cfg = self.config
            return dict(provider=cfg.provider, codex_model=cfg.codex_model, api_model=cfg.api_model,
                        base_url=cfg.base_url, has_api_key=bool(cfg.api_key), key_source=cfg.key_source,
                        codex_available=bool(shutil.which("codex")), offline=offline(),
                        disabled_by_env=os.environ.get("ASTRA_ENABLED") == "0",
                        warning=self.warning)

    def update(self, payload):
        if not isinstance(payload, dict) or "provider" not in payload:
            raise ValueError("请选择模型接入方式")
        if payload.keys() - {"provider", "codex_model", "api_model", "base_url", "api_key", "clear_api_key"}:
            raise ValueError("模型配置包含未知字段")
        if type(payload.get("clear_api_key", False)) is not bool:
            raise ValueError("清除密钥选项无效")
        with self.lock:
            saved = dict(self.saved)
            for name in ("provider", "codex_model", "api_model", "base_url"):
                if name in payload:
                    saved[name] = payload[name]
            base = _base_url(saved.get("base_url", self.config.base_url))
            saved["base_url"] = base
            if base != self.config.base_url:
                saved.pop("api_key", None)
            key = _key(payload.get("api_key", ""))
            if key and payload.get("clear_api_key"):
                raise ValueError("请选择更新密钥或清除密钥")
            if payload.get("clear_api_key"):
                saved["api_key"] = ""  # Explicitly suppress any matching environment key.
            elif key:
                saved["api_key"] = key
            config = self._resolve(saved)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            pending = None
            try:
                with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent, delete=False) as out:
                    pending = Path(out.name)
                    json.dump(saved, out, ensure_ascii=False, indent=2)
                    out.flush()
                    os.fsync(out.fileno())
                os.replace(pending, self.path)
            finally:
                if pending:
                    pending.unlink(missing_ok=True)
            self.config, self.saved, self.warning = config, saved, ""
            return self.public()
