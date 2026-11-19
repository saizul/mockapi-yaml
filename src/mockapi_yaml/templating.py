"""``{{ ... }}`` templates for response bodies and headers.

Grammar (deliberately small)::

    template   := "{{" expression ( "|" filter )* "}}"
    expression := path | call | literal
    path       := name ( "." segment )*            params.id, body.user.name, query.tags.0
    call       := path "(" [ literal ( "," literal )* ] ")"   faker.int(1, 10)
    filter     := name [ "(" literals ")" ]         int, float, bool, upper, lower, json, default("x")

A string that is exactly one template keeps the native type of the value
(``"{{faker.int(1, 9)}}"`` renders as a number, ``"{{body}}"`` as an object).
Templates embedded in longer strings are interpolated as text.

Special objects in a body: ``{"$repeat": 3, "$item": {...}}`` renders a list of
three items; inside, ``{{index}}`` is the 0-based position. ``$repeat`` also
accepts a range ``"2-5"`` or a template such as ``"{{query.limit | int}}"``.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from mockapi_yaml.fake import Fake, helper

TEMPLATE_RE = re.compile(r"{{\s*((?:(?!}}).)*?)\s*}}", re.S)
CALL_RE = re.compile(r"^([A-Za-z_][\w.-]*)\s*\((.*)\)$", re.S)
PATH_RE = re.compile(r"^[A-Za-z_$][\w$-]*(\.[\w$-]+)*$")
MAX_REPEAT = 10_000


class TemplateError(ValueError):
    """Raised for a malformed template expression."""


def _split_top(text: str, sep: str) -> list[str]:
    """Split on ``sep`` outside quotes and parentheses."""
    parts: list[str] = []
    depth = 0
    quote = ""
    current: list[str] = []
    for ch in text:
        if quote:
            current.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == sep and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(ch)
    parts.append("".join(current))
    return [p.strip() for p in parts]


def _literal(token: str) -> Any:
    token = token.strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "'\"":
        return token[1:-1]
    lowered = token.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in ("null", "none"):
        return None
    try:
        return int(token)
    except ValueError:
        pass
    try:
        return float(token)
    except ValueError:
        pass
    raise TemplateError(f"not a literal: {token!r}")


def _args(text: str) -> list[Any]:
    text = text.strip()
    if not text:
        return []
    return [_literal(t) for t in _split_top(text, ",")]


def lookup(context: Mapping[str, Any], path: str) -> Any:
    value: Any = context
    for segment in path.split("."):
        if isinstance(value, Mapping):
            if segment in value:
                value = value[segment]
            elif segment.lower() in value:
                value = value[segment.lower()]
            else:
                return None
        elif isinstance(value, list | tuple) and segment.lstrip("-").isdigit():
            index = int(segment)
            if -len(value) <= index < len(value):
                value = value[index]
            else:
                return None
        else:
            return None
    return value


def _to_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _apply_filter(value: Any, spec: str) -> Any:
    match = CALL_RE.match(spec)
    name, args = (match.group(1), _args(match.group(2))) if match else (spec, [])
    if name == "default":
        return value if value not in (None, "") else (args[0] if args else "")
    if value is None:
        return None
    try:
        if name == "int":
            return int(float(value)) if isinstance(value, str) else int(value)
        if name == "float":
            return float(value)
    except (TypeError, ValueError):
        return value
    if name == "bool":
        return _to_bool(value)
    if name == "upper":
        return str(value).upper()
    if name == "lower":
        return str(value).lower()
    if name == "string":
        return _stringify(value)
    if name == "json":
        return json.dumps(value)
    if name == "length":
        return len(value) if hasattr(value, "__len__") else 0
    raise TemplateError(f"unknown filter: {name}")


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict | list):
        return json.dumps(value)
    return str(value)


class Renderer:
    """Renders templates against a request context with a shared :class:`Fake`."""

    def __init__(self, fake: Fake | None = None) -> None:
        self.fake = fake or Fake()

    def _call(self, name: str, args: list[Any]) -> Any:
        if name.startswith("faker."):
            fn = helper(self.fake, name[len("faker.") :])
            if fn is None:
                raise TemplateError(f"unknown faker helper: {name}")
            try:
                return fn(*args)
            except (TypeError, ValueError) as exc:
                raise TemplateError(f"bad arguments for {name}: {exc}") from exc
        if name == "uuid":
            return str(uuid.uuid4())
        if name == "now":
            return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        if name == "timestamp":
            return int(datetime.now(UTC).timestamp())
        raise TemplateError(f"unknown function: {name}")

    def evaluate(self, expression: str, context: Mapping[str, Any]) -> Any:
        parts = _split_top(expression, "|")
        head, filters = parts[0], parts[1:]
        match = CALL_RE.match(head)
        if match:
            value = self._call(match.group(1), _args(match.group(2)))
        elif head.startswith("faker.") or head in ("uuid", "now", "timestamp"):
            value = self._call(head, [])
        elif PATH_RE.match(head) and head.lower() not in ("true", "false", "null", "none"):
            value = lookup(context, head)
        else:
            value = _literal(head)
        for spec in filters:
            value = _apply_filter(value, spec)
        return value

    def render_string(self, text: str, context: Mapping[str, Any]) -> Any:
        if "{{" not in text:
            return text
        whole = TEMPLATE_RE.fullmatch(text.strip())
        if whole:
            return self.evaluate(whole.group(1), context)
        return TEMPLATE_RE.sub(lambda m: _stringify(self.evaluate(m.group(1), context)), text)

    def _repeat_count(self, spec: Any, context: Mapping[str, Any]) -> int:
        if isinstance(spec, str):
            spec = self.render_string(spec, context)
        if isinstance(spec, str) and re.fullmatch(r"\s*\d+\s*-\s*\d+\s*", spec):
            low, high = (int(x) for x in spec.split("-"))
            spec = self.fake.rng.randint(min(low, high), max(low, high))
        try:
            count = int(spec)
        except (TypeError, ValueError) as exc:
            raise TemplateError(f"$repeat needs a number or a range, got {spec!r}") from exc
        return max(0, min(count, MAX_REPEAT))

    def render(self, value: Any, context: Mapping[str, Any]) -> Any:
        if isinstance(value, str):
            return self.render_string(value, context)
        if isinstance(value, list):
            return [self.render(v, context) for v in value]
        if isinstance(value, dict):
            if "$repeat" in value:
                count = self._repeat_count(value["$repeat"], context)
                item = value.get("$item", {})
                return [self.render(item, {**context, "index": i}) for i in range(count)]
            return {str(self.render_string(str(k), context)): self.render(v, context) for k, v in value.items()}
        return value


def validate_templates(value: Any, where: str) -> list[str]:
    """Return syntax problems in every template found in ``value`` (used by ``mockapi check``)."""
    problems: list[str] = []
    renderer = Renderer(Fake(0))

    def walk(node: Any, path: str) -> None:
        if isinstance(node, str):
            for match in TEMPLATE_RE.finditer(node):
                try:
                    renderer.evaluate(match.group(1), {})
                except TemplateError as exc:
                    problems.append(f"{path}: {exc}")
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{path}[{i}]")
        elif isinstance(node, dict):
            for key, item in node.items():
                walk(str(key), path)
                walk(item, f"{path}.{key}")

    walk(value, where)
    return problems
