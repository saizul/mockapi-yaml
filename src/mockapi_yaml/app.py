"""The ASGI application: routes, resources, OpenAPI examples, CORS, hot reload and the request log."""

from __future__ import annotations

import asyncio
import collections
import json
import logging
import mimetypes
import random
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import yaml
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from mockapi_yaml._version import __version__
from mockapi_yaml.config import Config, ConfigError, ErrorResponse, Latency, Route, load_config
from mockapi_yaml.fake import Fake
from mockapi_yaml.openapi import Operation, load_operations, parse_prefer
from mockapi_yaml.resources import Collection, ResourceError
from mockapi_yaml.templating import Renderer, TemplateError

log = logging.getLogger("mockapi_yaml")

ADMIN_PREFIX = "/__mockapi"
MAX_BODY_BYTES = 10 * 1024 * 1024
LOG_BODY_CHARS = 2000
Sleep = Callable[[float], Awaitable[Any]]


@dataclass
class Outcome:
    status: int
    body: Any = None
    headers: dict[str, str] | None = None
    raw: bytes | None = None
    content_type: str | None = None
    source: str = ""
    latency: Latency | None = None
    error_rate: float | None = None
    error: ErrorResponse | None = None


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")


def _value_matches(expected: Any, actual: Any) -> bool:
    if isinstance(expected, list) and not isinstance(actual, list):
        return any(_value_matches(e, actual) for e in expected)
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            k in actual and _value_matches(v, actual[k]) for k, v in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and all(any(_value_matches(e, a) for a in actual) for e in expected)
    if expected == "*":
        return actual is not None
    if isinstance(expected, str) and len(expected) >= 2 and expected.startswith("/") and expected.endswith("/"):
        return actual is not None and re.search(expected[1:-1], _text(actual)) is not None
    if actual is None:
        return expected is None
    return _text(expected) == _text(actual)


def _text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class MockApp:
    """ASGI app. Pass a path to enable hot reload, or a :class:`Config` for a fixed definition."""

    def __init__(
        self,
        source: str | Path | Config,
        *,
        sleep: Sleep = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        reload: bool = True,
    ) -> None:
        self.sleep = sleep
        self.clock = clock
        self.reload_enabled = reload and not isinstance(source, Config)
        self.config_path = None if isinstance(source, Config) else Path(source).resolve()
        self.last_check = 0.0
        self.mtimes: dict[Path, float] = {}
        self.reload_error: str | None = None
        self.reloads = 0
        self.collections: dict[str, Collection] = {}
        config = source if isinstance(source, Config) else load_config(source)
        self.log: collections.deque[dict[str, Any]] = collections.deque(maxlen=config.settings.log_size or None)
        self.request_counter = 0
        self._apply(config)

    # -- configuration and reload ------------------------------------------
    def _apply(self, config: Config) -> None:
        operations: list[Operation] = []
        for spec in config.openapi:
            operations.extend(load_operations(spec))
        self.config = config
        self.operations = operations
        self.fake = Fake(config.settings.seed)
        self.renderer = Renderer(self.fake)
        self.rng = random.Random(config.settings.seed)
        old = self.collections
        self.collections = {}
        for name, spec in config.resources.items():
            previous = old.get(name)
            if previous is not None and previous.spec.signature() == spec.signature():
                previous.spec = spec
                previous.renderer = self.renderer
                self.collections[name] = previous
            else:
                self.collections[name] = Collection(spec, self.renderer)
        if self.log.maxlen != (config.settings.log_size or None):
            self.log = collections.deque(self.log, maxlen=config.settings.log_size or None)
        self.mtimes = self._stat(config)
        self.app = self._build_stack(config)

    @staticmethod
    def _stat(config: Config) -> dict[Path, float]:
        mtimes = {}
        for path in config.watched_files():
            try:
                mtimes[path] = path.stat().st_mtime_ns
            except OSError:
                mtimes[path] = -1
        return mtimes

    def _build_stack(self, config: Config) -> ASGIApp:
        cors = config.settings.cors
        if cors is False:
            return self.handle
        origins = cors if isinstance(cors, list) else []
        return CORSMiddleware(
            self.handle,
            allow_origins=origins,
            allow_origin_regex=None if origins else ".*",
            allow_methods=["*"],
            allow_headers=["*"],
            allow_credentials=True,
            expose_headers=["*", "X-Total-Count", "Link", "Location", "X-Mock-Source"],
            max_age=600,
        )

    def maybe_reload(self, force: bool = False) -> bool:
        if not self.reload_enabled or self.config_path is None:
            return False
        now = self.clock()
        if not force and now - self.last_check < self.config.settings.reload_interval:
            return False
        self.last_check = now
        current = self._stat(self.config)
        if not force and current == self.mtimes:
            return False
        try:
            config = load_config(self.config_path)
            self._apply(config)
        except (ConfigError, OSError) as exc:
            self.mtimes = current  # do not retry until the file changes again
            self.reload_error = str(exc)
            log.error("reload failed, keeping the previous definition: %s", exc)
            return False
        self.reload_error = None
        self.reloads += 1
        log.info("reloaded %s", self.config_path)
        return True

    # -- ASGI ---------------------------------------------------------------
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        if scope["type"] != "http":
            return
        self.maybe_reload()
        await self.app(scope, receive, send)

    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        started = time.perf_counter()
        path = request.url.path
        if path == ADMIN_PREFIX or path.startswith(ADMIN_PREFIX + "/"):
            response = await self.admin(request, path[len(ADMIN_PREFIX) :] or "/")
            await response(scope, receive, send)
            return

        raw = b""
        async for chunk in request.stream():
            raw += chunk
            if len(raw) > MAX_BODY_BYTES:
                response = self._json(413, {"error": "request body too large"})
                await response(scope, receive, send)
                return
        body = self._parse_body(raw, request.headers.get("content-type", ""))

        try:
            outcome = self.dispatch(request, path, body)
        except TemplateError as exc:
            outcome = Outcome(500, {"error": f"template error: {exc}"}, source="template-error")

        settings = self.config.settings
        latency = outcome.latency if outcome.latency is not None else settings.latency
        if latency.enabled:
            await self.sleep(self.rng.uniform(latency.low, latency.high) / 1000)
        error_rate = outcome.error_rate if outcome.error_rate is not None else settings.error_rate
        if outcome.status != 404 and error_rate > 0 and self.rng.random() < error_rate:
            error = outcome.error or settings.error
            outcome = Outcome(
                error.status, error.body, dict(error.headers), source=f"{outcome.source} (injected error)"
            )

        response = self._render(outcome, request)
        await response(scope, receive, send)
        self._record(request, raw, response.status_code, outcome.source, started)

    # -- dispatch -----------------------------------------------------------
    @staticmethod
    def _parse_body(raw: bytes, content_type: str) -> Any:
        if not raw:
            return None
        text = raw.decode("utf-8", errors="replace")
        if "json" in content_type or text.lstrip()[:1] in ("{", "["):
            try:
                return json.loads(text)
            except ValueError:
                return text
        if "application/x-www-form-urlencoded" in content_type:
            return {k: v[-1] if len(v) == 1 else v for k, v in parse_qs(text, keep_blank_values=True).items()}
        return text

    def _context(self, request: Request, params: dict[str, str], body: Any) -> dict[str, Any]:
        query: dict[str, Any] = {}
        for key, value in request.query_params.multi_items():
            query[key] = value
        return {
            "params": params,
            "query": query,
            "queryAll": {k: request.query_params.getlist(k) for k in request.query_params},
            "headers": {k.lower(): v for k, v in request.headers.items()},
            "body": body,
            "request": {"method": request.method, "path": request.url.path, "url": str(request.url)},
        }

    def dispatch(self, request: Request, path: str, body: Any) -> Outcome:
        base = self.config.settings.base_path
        if base:
            if path != base and not path.startswith(base + "/"):
                return Outcome(404, {"error": f"not found: {path} (base_path is {base})"}, source="none")
            path = path[len(base) :] or "/"
        method = request.method.upper()
        lookup_method = "GET" if method == "HEAD" else method
        allowed: set[str] = set()

        for index, route in enumerate(self.config.routes):
            match = route.pattern.match(path)
            if not match:
                continue
            if lookup_method not in route.methods and method not in route.methods:
                allowed.update(route.methods)
                continue
            context = self._context(request, match.groupdict(), body)
            if not self._route_matches(route, context):
                continue
            return self._route_outcome(route, index, context)

        for name, collection in self.collections.items():
            outcome = self._resource(collection, name, path, method, body, request, allowed)
            if outcome is not None:
                return outcome

        for op in self.operations:
            match = op.pattern.match(path)
            if not match:
                continue
            if op.method != lookup_method:
                allowed.add(op.method)
                continue
            return self._operation_outcome(op, request, self._context(request, match.groupdict(), body))

        if allowed and method != "OPTIONS":
            return Outcome(
                405,
                {"error": f"method {method} not allowed for {path}"},
                headers={"Allow": ", ".join(sorted(allowed))},
                source="none",
            )
        return Outcome(
            404, {"error": f"no mock for {method} {path}", "hint": f"see GET {ADMIN_PREFIX}/routes"}, source="none"
        )

    @staticmethod
    def _route_matches(route: Route, context: dict[str, Any]) -> bool:
        for key, expected in route.match_query.items():
            values = context["queryAll"].get(key)
            actual: Any = None if not values else (values[0] if len(values) == 1 else values)
            if isinstance(actual, list) and not isinstance(expected, list):
                if not any(_value_matches(expected, v) for v in actual):
                    return False
            elif not _value_matches(expected, actual):
                return False
        for key, expected in route.match_headers.items():
            if not _value_matches(expected, context["headers"].get(key)):
                return False
        return route.match_body is None or _value_matches(route.match_body, context["body"])

    def _route_outcome(self, route: Route, index: int, context: dict[str, Any]) -> Outcome:
        source = f"routes[{index}]" + (f" {route.name}" if route.name else "")
        headers = {
            **self.config.settings.headers,
            **{k: str(self.renderer.render(v, context)) for k, v in route.headers.items()},
        }
        outcome = Outcome(
            route.status, headers=headers, source=source, latency=route.latency, error_rate=route.error_rate,
            error=route.error,
        )  # fmt: skip
        if route.file is not None:
            suffix = route.file.suffix.lower()
            if suffix in (".json", ".yaml", ".yml"):
                text = route.file.read_text("utf-8")
                data = json.loads(text) if suffix == ".json" else yaml.safe_load(text)
                outcome.body = self.renderer.render(data, context)
            else:
                outcome.raw = route.file.read_bytes()
                outcome.content_type = mimetypes.guess_type(route.file.name)[0] or "application/octet-stream"
        else:
            outcome.body = self.renderer.render(route.body, context)
        return outcome

    def _resource(
        self,
        collection: Collection,
        name: str,
        path: str,
        method: str,
        body: Any,
        request: Request,
        allowed: set[str],
    ) -> Outcome | None:
        base = collection.spec.path
        source = f"resource {name}"
        headers = dict(self.config.settings.headers)
        if path.rstrip("/") == base:
            item_id = None
        elif path.startswith(base + "/") and "/" not in path[len(base) + 1 :].rstrip("/") and path[len(base) + 1 :]:
            item_id = path[len(base) + 1 :].rstrip("/")
        else:
            return None
        try:
            if item_id is None:
                if method in ("GET", "HEAD"):
                    params = {k: request.query_params.getlist(k) for k in request.query_params}
                    items, meta = collection.query(params)
                    headers["X-Total-Count"] = str(meta["total"])
                    if "page" in meta:
                        headers.update(self._link_header(request, meta))
                    payload: Any = {"data": items, "meta": meta} if collection.spec.envelope else items
                    return Outcome(200, payload, headers, source=source)
                if method == "POST":
                    item = collection.create(body)
                    headers["Location"] = f"{self.config.settings.base_path}{base}/{item[collection.spec.id_field]}"
                    return Outcome(201, item, headers, source=source)
                allowed.update(("GET", "POST"))
                return None
            if method in ("GET", "HEAD"):
                return Outcome(200, collection.get(item_id), headers, source=source)
            if method == "PUT":
                return Outcome(200, collection.replace(item_id, body), headers, source=source)
            if method == "PATCH":
                return Outcome(200, collection.update(item_id, body), headers, source=source)
            if method == "DELETE":
                collection.delete(item_id)
                return Outcome(204, None, headers, source=source)
            allowed.update(("GET", "PUT", "PATCH", "DELETE"))
            return None
        except ResourceError as exc:
            return Outcome(exc.status, {"error": exc.message}, headers, source=source)

    @staticmethod
    def _link_header(request: Request, meta: dict[str, Any]) -> dict[str, str]:
        links = []
        page, pages = meta["page"], meta["pages"]

        def url(number: int) -> str:
            params = dict(request.query_params)
            params.pop("offset", None)
            params.pop("_start", None)
            params["page" if "_page" not in params else "_page"] = str(number)
            return str(request.url.replace_query_params(**params))

        if pages:
            links.append(f'<{url(1)}>; rel="first"')
            if page > 1:
                links.append(f'<{url(page - 1)}>; rel="prev"')
            if page < pages:
                links.append(f'<{url(page + 1)}>; rel="next"')
            links.append(f'<{url(pages)}>; rel="last"')
        return {"Link": ", ".join(links)} if links else {}

    def _operation_outcome(self, op: Operation, request: Request, context: dict[str, Any]) -> Outcome:
        prefer = parse_prefer(request.headers.get("prefer", ""))
        code = request.query_params.get("__code") or prefer.get("code")
        example_name = request.query_params.get("__example") or prefer.get("example")
        selected = op.select(code)
        body = self.renderer.render(selected.example(example_name), context)
        headers = {**self.config.settings.headers, **selected.headers}
        outcome = Outcome(selected.status, body, headers, source=f"openapi {op.operation_id}")
        if selected.content_type and "json" not in selected.content_type:
            outcome.content_type = selected.content_type
            outcome.raw = (
                body.encode("utf-8") if isinstance(body, str) else (_json_bytes(body) if body is not None else b"")
            )
        return outcome

    # -- responses ------------------------------------------------------------
    def _render(self, outcome: Outcome, request: Request) -> Response:
        headers = dict(outcome.headers or {})
        content_type = next((v for k, v in headers.items() if k.lower() == "content-type"), None)
        headers = {k: v for k, v in headers.items() if k.lower() != "content-type"}
        if outcome.raw is not None:
            content = outcome.raw
            content_type = content_type or outcome.content_type
        elif outcome.body is None or outcome.status in (204, 304):
            content = b""
        elif isinstance(outcome.body, str) and not (content_type and "json" in content_type):
            content = outcome.body.encode("utf-8")
            content_type = content_type or "text/plain; charset=utf-8"
        elif isinstance(outcome.body, bytes):
            content = outcome.body
        else:
            content = _json_bytes(outcome.body)
            content_type = content_type or "application/json"
        if outcome.source:
            headers["X-Mock-Source"] = outcome.source
        if request.method == "HEAD":
            headers["Content-Length"] = str(len(content))
            content = b""
        return Response(content, status_code=outcome.status, headers=headers, media_type=content_type)

    @staticmethod
    def _json(status: int, data: Any) -> Response:
        return Response(_json_bytes(data), status_code=status, media_type="application/json")

    def _record(self, request: Request, raw: bytes, status: int, source: str, started: float) -> None:
        duration = round((time.perf_counter() - started) * 1000, 1)
        self.request_counter += 1
        entry = {
            "id": self.request_counter,
            "time": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "method": request.method,
            "path": request.url.path,
            "query": request.url.query,
            "status": status,
            "duration_ms": duration,
            "source": source,
            "body": raw[:LOG_BODY_CHARS].decode("utf-8", errors="replace") if raw else None,
        }
        if self.config.settings.log_size:
            self.log.append(entry)
        if self.config.settings.log_requests:
            query = f"?{request.url.query}" if request.url.query else ""
            log.info("%s %s%s -> %s %.1fms [%s]", request.method, request.url.path, query, status, duration, source)

    # -- admin API ------------------------------------------------------------
    def describe(self) -> dict[str, Any]:
        base = self.config.settings.base_path
        routes = [
            {
                "source": f"routes[{i}]",
                "name": r.name,
                "methods": list(r.methods),
                "path": base + r.path,
                "status": r.status,
            }
            for i, r in enumerate(self.config.routes)
        ]
        resources = [
            {"name": name, "path": base + c.spec.path, "count": len(c.items), "readonly": c.spec.readonly}
            for name, c in self.collections.items()
        ]
        operations = [
            {
                "operation_id": op.operation_id,
                "method": op.method,
                "path": base + op.path,
                "responses": list(op.responses),
            }
            for op in self.operations
        ]
        return {
            "version": __version__,
            "config": str(self.config_path) if self.config_path else None,
            "reloads": self.reloads,
            "reload_error": self.reload_error,
            "routes": routes,
            "resources": resources,
            "openapi": operations,
        }

    async def admin(self, request: Request, sub: str) -> Response:
        method = request.method
        if sub in ("/", "/routes") and method == "GET":
            return self._json(200, self.describe())
        if sub == "/health" and method in ("GET", "HEAD"):
            return self._json(200, {"status": "ok", "version": __version__, "reload_error": self.reload_error})
        if sub == "/log":
            if method == "GET":
                limit = request.query_params.get("limit", "")
                entries = list(self.log)
                if limit.isdigit():
                    entries = entries[-int(limit) :] if int(limit) else []
                return self._json(200, entries)
            if method == "DELETE":
                self.log.clear()
                return Response(status_code=204)
        if sub == "/reset" and method == "POST":
            for collection in self.collections.values():
                collection.reset()
            return self._json(200, {"status": "reset", "resources": list(self.collections)})
        if sub == "/reload" and method == "POST":
            if not self.reload_enabled:
                return self._json(409, {"error": "reload is disabled"})
            self.maybe_reload(force=True)
            status = 200 if self.reload_error is None else 422
            return self._json(status, {"reloads": self.reloads, "reload_error": self.reload_error})
        return self._json(404, {"error": f"unknown admin endpoint {method} {ADMIN_PREFIX}{sub}"})


def create_app(source: str | Path | Config, **kwargs: Any) -> MockApp:
    return MockApp(source, **kwargs)
