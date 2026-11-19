"""Serve the examples of an OpenAPI 3.x document.

For each operation the mock answers with, in order of preference: the named
example asked for (``Prefer: example=<name>``), the media type's ``example``,
the first of its ``examples``, the schema's ``example`` and finally a value
generated from the schema. The status is the lowest 2xx response unless the
client asks for another with ``Prefer: code=404`` (or ``?__code=404``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mockapi_yaml.config import METHODS, ConfigError, compile_path, load_file

MAX_DEPTH = 8


@dataclass
class MockResponse:
    status: int
    content_type: str | None = None
    examples: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)

    def example(self, name: str | None = None) -> Any:
        if not self.examples:
            return None
        if name and name in self.examples:
            return self.examples[name]
        return next(iter(self.examples.values()))


@dataclass
class Operation:
    method: str
    path: str
    operation_id: str
    responses: dict[str, MockResponse]
    source: str
    pattern: re.Pattern[str] = field(default=re.compile(""), repr=False)

    def __post_init__(self) -> None:
        self.pattern = compile_path(self.path)

    def default_key(self) -> str | None:
        success = sorted(k for k in self.responses if k.isdigit() and k.startswith("2"))
        if success:
            return success[0]
        if "default" in self.responses:
            return "default"
        numeric = sorted(k for k in self.responses if k.isdigit())
        return numeric[0] if numeric else None

    def select(self, code: str | None) -> MockResponse:
        if code:
            if code in self.responses:
                return self.responses[code]
            wildcard = f"{code[0]}XX"
            for key in (wildcard, wildcard.lower()):
                if key in self.responses:
                    resp = self.responses[key]
                    return MockResponse(int(code), resp.content_type, resp.examples, resp.headers)
            if "default" in self.responses and code.isdigit():
                resp = self.responses["default"]
                return MockResponse(int(code), resp.content_type, resp.examples, resp.headers)
        key = self.default_key()
        if key is None:
            return MockResponse(200)
        return self.responses[key]


class Resolver:
    def __init__(self, document: dict[str, Any]) -> None:
        self.document = document

    def resolve(self, node: Any) -> Any:
        seen = 0
        while isinstance(node, dict) and "$ref" in node:
            ref = node["$ref"]
            if not isinstance(ref, str) or not ref.startswith("#/"):
                return {}
            target: Any = self.document
            for part in ref[2:].split("/"):
                part = part.replace("~1", "/").replace("~0", "~")
                if not isinstance(target, dict) or part not in target:
                    return {}
                target = target[part]
            node = target
            seen += 1
            if seen > 32:
                return {}
        return node

    def sample(self, schema: Any, depth: int = 0) -> Any:
        schema = self.resolve(schema)
        if not isinstance(schema, dict) or depth > MAX_DEPTH:
            return None
        if "example" in schema:
            return schema["example"]
        if isinstance(schema.get("examples"), list) and schema["examples"]:
            return schema["examples"][0]
        if "default" in schema:
            return schema["default"]
        if "const" in schema:
            return schema["const"]
        if isinstance(schema.get("enum"), list) and schema["enum"]:
            return schema["enum"][0]
        if isinstance(schema.get("allOf"), list):
            merged: dict[str, Any] = {}
            for part in schema["allOf"]:
                value = self.sample(part, depth + 1)
                if isinstance(value, dict):
                    merged.update(value)
            if merged or not any(k in schema for k in ("type", "properties")):
                return merged
        for key in ("oneOf", "anyOf"):
            if isinstance(schema.get(key), list) and schema[key]:
                return self.sample(schema[key][0], depth + 1)
        kind = schema.get("type")
        if isinstance(kind, list):
            kind = next((k for k in kind if k != "null"), "null")
        if kind is None:
            if "properties" in schema or "additionalProperties" in schema:
                kind = "object"
            elif "items" in schema:
                kind = "array"
        if kind == "object":
            props = schema.get("properties") or {}
            result = {name: self.sample(prop, depth + 1) for name, prop in props.items()}
            extra = schema.get("additionalProperties")
            if not props and isinstance(extra, dict):
                result["key"] = self.sample(extra, depth + 1)
            return result
        if kind == "array":
            count = max(1, int(schema.get("minItems", 1) or 1))
            item = self.sample(schema.get("items", {}), depth + 1)
            return [item for _ in range(min(count, 5))]
        if kind in ("integer", "number"):
            minimum = schema.get("minimum")
            value = minimum if isinstance(minimum, int | float) and not isinstance(minimum, bool) else 0
            return int(value) if kind == "integer" else float(value)
        if kind == "boolean":
            return True
        if kind == "string":
            return _string_sample(schema)
        if kind == "null":
            return None
        return None


STRING_FORMATS = {
    "date-time": "2026-01-01T12:00:00Z",
    "date": "2026-01-01",
    "time": "12:00:00",
    "email": "user@example.com",
    "uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "uri": "https://example.com/",
    "url": "https://example.com/",
    "hostname": "example.com",
    "ipv4": "192.0.2.1",
    "ipv6": "2001:db8::1",
    "byte": "U3dhZ2dlciByb2Nrcw==",
    "password": "********",
}


def _string_sample(schema: dict[str, Any]) -> str:
    value = STRING_FORMATS.get(str(schema.get("format", "")), "string")
    min_length = schema.get("minLength")
    if isinstance(min_length, int) and len(value) < min_length:
        value = value + "x" * (min_length - len(value))
    return value


def _media(content: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    if not content:
        return None, {}
    for media_type in content:
        if media_type.split(";")[0].strip().endswith("json"):
            return media_type, content[media_type] or {}
    media_type = next(iter(content))
    return media_type, content[media_type] or {}


def _response(resolver: Resolver, status: str, spec: Any) -> MockResponse:
    spec = resolver.resolve(spec) or {}
    content_type, media = _media(resolver.resolve(spec.get("content")) or {})
    media = resolver.resolve(media) or {}
    examples: dict[str, Any] = {}
    if "example" in media:
        examples["example"] = media["example"]
    for name, example in (media.get("examples") or {}).items():
        example = resolver.resolve(example)
        if isinstance(example, dict) and "value" in example:
            examples[name] = example["value"]
    if not examples and content_type is not None and media.get("schema") is not None:
        examples["generated"] = resolver.sample(media["schema"])
    headers: dict[str, str] = {}
    for name, header in (spec.get("headers") or {}).items():
        header = resolver.resolve(header) or {}
        value = header.get("example")
        if value is None and header.get("schema") is not None:
            value = resolver.sample(header["schema"])
        if value is not None:
            headers[name] = str(value)
    code = int(status) if status.isdigit() else 200
    return MockResponse(code, content_type, examples, headers)


def operations_from_document(document: Any, source: str = "openapi") -> list[Operation]:
    if not isinstance(document, dict) or not isinstance(document.get("paths"), dict):
        raise ConfigError(f"{source}: not an OpenAPI 3 document (no 'paths' mapping)")
    version = str(document.get("openapi", ""))
    if not version.startswith("3"):
        raise ConfigError(f"{source}: only OpenAPI 3.x is supported (found openapi: {version or 'missing'})")
    resolver = Resolver(document)
    ops: list[Operation] = []
    for path, item in document["paths"].items():
        item = resolver.resolve(item) or {}
        for method, spec in item.items():
            if method.upper() not in METHODS or not isinstance(spec, dict):
                continue
            responses = {
                str(status): _response(resolver, str(status), resp)
                for status, resp in (spec.get("responses") or {}).items()
            }
            ops.append(
                Operation(
                    method=method.upper(),
                    path=str(path),
                    operation_id=str(spec.get("operationId", f"{method.upper()} {path}")),
                    responses=responses,
                    source=source,
                )
            )
    # Literal segments win over parameters: /pets/mine before /pets/{id}.
    ops.sort(key=lambda op: (op.path.count("{"), -len(op.path)))
    return ops


def load_operations(path: Path) -> list[Operation]:
    return operations_from_document(load_file(path), path.name)


def parse_prefer(header: str) -> dict[str, str]:
    """Parse ``Prefer: code=404, example=notFound`` into a dict."""
    result: dict[str, str] = {}
    for part in re.split(r"[,;]", header or ""):
        key, sep, value = part.strip().partition("=")
        if sep:
            result[key.strip().lower()] = value.strip().strip('"')
    return result
