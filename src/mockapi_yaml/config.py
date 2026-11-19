"""Load and validate the mock definition file (``mock.yaml``)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from mockapi_yaml.templating import validate_templates

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")
PARAM_RE = re.compile(r"{([A-Za-z_]\w*)(?::(path))?}|:([A-Za-z_]\w*)")


class ConfigError(ValueError):
    """The mock file is invalid. The message says where and why."""


@dataclass(frozen=True)
class Latency:
    low: int = 0
    high: int = 0

    @property
    def enabled(self) -> bool:
        return self.high > 0


@dataclass
class ErrorResponse:
    status: int = 500
    body: Any = field(default_factory=lambda: {"error": "Injected failure from mockapi-yaml"})
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class Settings:
    latency: Latency = field(default_factory=Latency)
    error_rate: float = 0.0
    error: ErrorResponse = field(default_factory=ErrorResponse)
    cors: bool | list[str] = True
    seed: int | None = None
    base_path: str = ""
    log_size: int = 500
    log_requests: bool = True
    reload_interval: float = 1.0
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class Route:
    path: str
    methods: tuple[str, ...] = ("GET",)
    name: str = ""
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    body: Any = None
    file: Path | None = None
    match_query: dict[str, Any] = field(default_factory=dict)
    match_headers: dict[str, Any] = field(default_factory=dict)
    match_body: Any = None
    latency: Latency | None = None
    error_rate: float | None = None
    error: ErrorResponse | None = None
    source: str = "routes"
    pattern: re.Pattern[str] = field(default=re.compile(""), repr=False)

    def __post_init__(self) -> None:
        self.pattern = compile_path(self.path)


@dataclass
class Resource:
    name: str
    path: str
    id_field: str = "id"
    seed: list[dict[str, Any]] = field(default_factory=list)
    generate_count: int = 0
    generate_item: dict[str, Any] = field(default_factory=dict)
    envelope: bool = False
    per_page: int = 20
    max_per_page: int = 1000
    readonly: bool = False

    def signature(self) -> str:
        """Identity of the definition, used to keep data across reloads when nothing changed."""
        return json.dumps(
            [self.path, self.id_field, self.seed, self.generate_count, self.generate_item], sort_keys=True, default=str
        )


@dataclass
class Config:
    settings: Settings = field(default_factory=Settings)
    routes: list[Route] = field(default_factory=list)
    resources: dict[str, Resource] = field(default_factory=dict)
    openapi: list[Path] = field(default_factory=list)
    path: Path | None = None

    def watched_files(self) -> list[Path]:
        files = [p for p in [self.path, *self.openapi] if p is not None]
        files += [r.file for r in self.routes if r.file is not None]
        return files


def compile_path(path: str) -> re.Pattern[str]:
    """``/users/{id}`` or ``/users/:id`` to a regex; ``{rest:path}`` matches across slashes."""
    out = []
    pos = 0
    for match in PARAM_RE.finditer(path):
        out.append(re.escape(path[pos : match.start()]))
        name = match.group(1) or match.group(3)
        out.append(f"(?P<{name}>.+)" if match.group(2) else f"(?P<{name}>[^/]+)")
        pos = match.end()
    out.append(re.escape(path[pos:]))
    pattern = "".join(out).rstrip("/") or "/"
    if pattern != "/":
        pattern += "/?"
    try:
        return re.compile(f"^{pattern}$")
    except re.error as exc:
        raise ConfigError(f"invalid path {path!r}: {exc}") from exc


def _check_keys(data: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ConfigError(f"{where}: unknown key(s) {', '.join(unknown)} (allowed: {', '.join(sorted(allowed))})")


def _mapping(value: Any, where: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{where}: expected a mapping, got {type(value).__name__}")
    return value


def parse_latency(value: Any, where: str) -> Latency:
    """``150`` (ms), ``"100-500"`` (random in range), ``{min: 100, max: 500}`` or ``0``."""
    if value is None or value is False:
        return Latency()
    if isinstance(value, bool):
        raise ConfigError(f"{where}: latency must be milliseconds, a range '100-500' or {{min, max}}")
    if isinstance(value, int | float):
        low = high = int(value)
    elif isinstance(value, str):
        text = value.strip().removesuffix("ms").strip()
        if "-" in text:
            a, _, b = text.partition("-")
            try:
                low, high = int(a.strip().removesuffix("ms")), int(b.strip().removesuffix("ms"))
            except ValueError as exc:
                raise ConfigError(f"{where}: bad latency range {value!r}") from exc
        else:
            try:
                low = high = int(text)
            except ValueError as exc:
                raise ConfigError(f"{where}: bad latency {value!r}") from exc
    elif isinstance(value, dict):
        _check_keys(value, {"min", "max"}, where)
        low, high = int(value.get("min", 0)), int(value.get("max", value.get("min", 0)))
    else:
        raise ConfigError(f"{where}: bad latency {value!r}")
    if low < 0 or high < low:
        raise ConfigError(f"{where}: latency range must satisfy 0 <= min <= max")
    if high > 120_000:
        raise ConfigError(f"{where}: latency above 120000 ms is not allowed")
    return Latency(low, high)


def _error_rate(value: Any, where: str) -> float:
    try:
        rate = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{where}: error_rate must be a number between 0 and 1") from exc
    if not 0 <= rate <= 1:
        raise ConfigError(f"{where}: error_rate must be between 0 and 1")
    return rate


def _status(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 100 <= value <= 599:
        raise ConfigError(f"{where}: status must be an HTTP status code (100-599)")
    return value


def _headers(value: Any, where: str) -> dict[str, str]:
    return {str(k): str(v) for k, v in _mapping(value, where).items()}


def _error(value: Any, where: str) -> ErrorResponse:
    data = _mapping(value, where)
    _check_keys(data, {"status", "body", "headers"}, where)
    default = ErrorResponse()
    return ErrorResponse(
        status=_status(data.get("status", 500), f"{where}.status"),
        body=data.get("body", default.body),
        headers=_headers(data.get("headers"), f"{where}.headers"),
    )


def _settings(data: dict[str, Any]) -> Settings:
    where = "settings"
    _check_keys(
        data,
        {"latency", "error_rate", "error", "cors", "seed", "base_path", "log_size", "log_requests", "reload_interval",
         "headers"},
        where,
    )  # fmt: skip
    cors = data.get("cors", True)
    if not isinstance(cors, bool):
        if isinstance(cors, str):
            cors = [cors]
        if not isinstance(cors, list) or not all(isinstance(o, str) for o in cors):
            raise ConfigError("settings.cors: use true, false or a list of allowed origins")
    seed = data.get("seed")
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise ConfigError("settings.seed must be an integer")
    base_path = str(data.get("base_path", "") or "").rstrip("/")
    if base_path and not base_path.startswith("/"):
        raise ConfigError("settings.base_path must start with '/'")
    return Settings(
        latency=parse_latency(data.get("latency"), "settings.latency"),
        error_rate=_error_rate(data.get("error_rate", 0), "settings.error_rate"),
        error=_error(data.get("error"), "settings.error") if data.get("error") is not None else ErrorResponse(),
        cors=cors,
        seed=seed,
        base_path=base_path,
        log_size=max(0, int(data.get("log_size", 500))),
        log_requests=bool(data.get("log_requests", True)),
        reload_interval=float(data.get("reload_interval", 1.0)),
        headers=_headers(data.get("headers"), "settings.headers"),
    )


ROUTE_KEYS = {
    "method", "methods", "path", "name", "status", "headers", "body", "file", "match", "latency", "error_rate",
    "error",
}  # fmt: skip


def _methods(value: Any, where: str) -> tuple[str, ...]:
    items = value if isinstance(value, list) else [value]
    methods: list[str] = []
    for item in items:
        method = str(item).upper()
        if method in ("*", "ANY"):
            return METHODS
        if method not in METHODS:
            raise ConfigError(f"{where}: unknown HTTP method {item!r}")
        methods.append(method)
    return tuple(methods)


def _route(data: Any, index: int, base_dir: Path) -> Route:
    where = f"routes[{index}]"
    data = _mapping(data, where)
    _check_keys(data, ROUTE_KEYS, where)
    path = data.get("path")
    if not isinstance(path, str) or not path.startswith("/"):
        raise ConfigError(f"{where}.path is required and must start with '/'")
    match = _mapping(data.get("match"), f"{where}.match")
    _check_keys(match, {"query", "headers", "body"}, f"{where}.match")
    if "body" in data and "file" in data:
        raise ConfigError(f"{where}: use either body or file, not both")
    file = None
    if data.get("file") is not None:
        file = (base_dir / str(data["file"])).resolve()
        if not file.is_file():
            raise ConfigError(f"{where}.file: {file} does not exist")
    for problem in validate_templates(data.get("body"), f"{where}.body"):
        raise ConfigError(problem)
    for problem in validate_templates(data.get("headers"), f"{where}.headers"):
        raise ConfigError(problem)
    return Route(
        path=path,
        methods=_methods(data.get("methods", data.get("method", "GET")), f"{where}.method"),
        name=str(data.get("name", "")),
        status=_status(data.get("status", 200), f"{where}.status"),
        headers=_headers(data.get("headers"), f"{where}.headers"),
        body=data.get("body"),
        file=file,
        match_query=_mapping(match.get("query"), f"{where}.match.query"),
        match_headers={k.lower(): v for k, v in _mapping(match.get("headers"), f"{where}.match.headers").items()},
        match_body=match.get("body"),
        latency=parse_latency(data["latency"], f"{where}.latency") if "latency" in data else None,
        error_rate=_error_rate(data["error_rate"], f"{where}.error_rate") if "error_rate" in data else None,
        error=_error(data["error"], f"{where}.error") if data.get("error") is not None else None,
    )


RESOURCE_KEYS = {"path", "id_field", "seed", "generate", "envelope", "per_page", "max_per_page", "readonly"}


def _resource(name: str, data: Any, base_dir: Path) -> Resource:
    where = f"resources.{name}"
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ConfigError(f"{where}: resource names may only use letters, digits, '-' and '_'")
    data = _mapping(data, where)
    _check_keys(data, RESOURCE_KEYS, where)
    path = str(data.get("path", f"/{name}")).rstrip("/")
    if not path.startswith("/"):
        raise ConfigError(f"{where}.path must start with '/'")
    seed = data.get("seed", [])
    if isinstance(seed, str):
        seed_file = (base_dir / seed).resolve()
        try:
            seed = (
                json.loads(seed_file.read_text("utf-8"))
                if seed.endswith(".json")
                else yaml.safe_load(seed_file.read_text("utf-8"))
            )
        except (OSError, ValueError, yaml.YAMLError) as exc:
            raise ConfigError(f"{where}.seed: cannot read {seed_file}: {exc}") from exc
    if not isinstance(seed, list) or not all(isinstance(item, dict) for item in seed):
        raise ConfigError(f"{where}.seed must be a list of objects (or a path to a JSON/YAML file with one)")
    generate = _mapping(data.get("generate"), f"{where}.generate")
    _check_keys(generate, {"count", "item"}, f"{where}.generate")
    count = generate.get("count", 0)
    if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 100_000:
        raise ConfigError(f"{where}.generate.count must be an integer between 0 and 100000")
    item = _mapping(generate.get("item"), f"{where}.generate.item")
    for problem in validate_templates(item, f"{where}.generate.item"):
        raise ConfigError(problem)
    per_page = int(data.get("per_page", 20))
    max_per_page = int(data.get("max_per_page", 1000))
    if per_page < 1 or max_per_page < per_page:
        raise ConfigError(f"{where}: need 1 <= per_page <= max_per_page")
    return Resource(
        name=name,
        path=path,
        id_field=str(data.get("id_field", "id")),
        seed=seed,
        generate_count=count,
        generate_item=item,
        envelope=bool(data.get("envelope", False)),
        per_page=per_page,
        max_per_page=max_per_page,
        readonly=bool(data.get("readonly", False)),
    )


def parse_config(data: Any, base_dir: Path | str = ".", path: Path | None = None) -> Config:
    base_dir = Path(base_dir)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError("the mock file must be a mapping with settings, routes, resources and/or openapi")
    _check_keys(data, {"settings", "routes", "resources", "openapi"}, "top level")
    settings = _settings(_mapping(data.get("settings"), "settings"))

    routes_data = data.get("routes")
    if routes_data is None:
        routes_data = []
    if not isinstance(routes_data, list):
        raise ConfigError("routes must be a list")
    routes = [_route(item, i, base_dir) for i, item in enumerate(routes_data)]

    resources_data = data.get("resources") or {}
    if isinstance(resources_data, str):
        resources_data = [resources_data]
    if isinstance(resources_data, list):
        resources_data = {str(name): {} for name in resources_data}
    if not isinstance(resources_data, dict):
        raise ConfigError("resources must be a list of names or a mapping of name to options")
    resources = {name: _resource(str(name), spec, base_dir) for name, spec in resources_data.items()}
    seen: dict[str, str] = {}
    for res in resources.values():
        if res.path in seen:
            raise ConfigError(f"resources.{res.name}: path {res.path} is already used by {seen[res.path]}")
        seen[res.path] = res.name

    openapi_data = data.get("openapi") or []
    if isinstance(openapi_data, str):
        openapi_data = [openapi_data]
    if not isinstance(openapi_data, list):
        raise ConfigError("openapi must be a file path or a list of paths")
    openapi = []
    for item in openapi_data:
        spec_path = (base_dir / str(item)).resolve()
        if not spec_path.is_file():
            raise ConfigError(f"openapi: {spec_path} does not exist")
        openapi.append(spec_path)
    return Config(settings=settings, routes=routes, resources=resources, openapi=openapi, path=path)


def load_file(path: Path) -> Any:
    try:
        text = path.read_text("utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    try:
        if path.suffix.lower() == ".json":
            return json.loads(text)
        return yaml.safe_load(text)
    except (ValueError, yaml.YAMLError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def load_config(path: str | Path) -> Config:
    """Load a mock file. A bare OpenAPI document (with an ``openapi:`` version key) is accepted too."""
    path = Path(path).resolve()
    data = load_file(path)
    if isinstance(data, dict) and isinstance(data.get("openapi"), str) and "paths" in data:
        return Config(openapi=[path], path=path)
    return parse_config(data, path.parent, path)
