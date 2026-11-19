"""In-memory CRUD collections: ``resources: [users]`` gives a full REST resource."""

from __future__ import annotations

import copy
import math
import uuid
from collections.abc import Mapping
from typing import Any

from mockapi_yaml.config import Resource
from mockapi_yaml.templating import Renderer, lookup

PAGE_KEYS = {"page", "per_page", "limit", "offset", "_page", "_limit", "_per_page", "_start"}
SORT_KEYS = {"sort", "_sort", "_order", "order"}
RESERVED = PAGE_KEYS | SORT_KEYS | {"q", "_q", "__code", "__example"}
OPERATORS = ("_gte", "_lte", "_gt", "_lt", "_ne", "_like")


class ResourceError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _int(value: str | None, name: str, minimum: int) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except ValueError as exc:
        raise ResourceError(400, f"{name} must be an integer") from exc
    if number < minimum:
        raise ResourceError(400, f"{name} must be >= {minimum}")
    return number


def _compare_key(value: Any) -> tuple[int, Any]:
    if value is None:
        return (2, "")
    if isinstance(value, bool):
        return (0, int(value))
    if isinstance(value, int | float):
        return (0, value)
    return (1, str(value).lower())


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    return str(value)


def _matches(item: Mapping[str, Any], field: str, op: str, wanted: list[str]) -> bool:
    value = lookup(item, field)
    if op == "":
        if isinstance(value, list):
            return any(_as_text(v) in wanted for v in value)
        return _as_text(value) in wanted
    if op == "_ne":
        return _as_text(value) not in wanted
    if op == "_like":
        return any(w.lower() in _as_text(value).lower() for w in wanted)
    target = wanted[-1]
    left, right = _number(value), _number(target)
    if left is None or right is None:
        if value is None:
            return False
        left_s, right_s = _as_text(value), target
        return {
            "_gte": left_s >= right_s,
            "_lte": left_s <= right_s,
            "_gt": left_s > right_s,
            "_lt": left_s < right_s,
        }[op]
    return {"_gte": left >= right, "_lte": left <= right, "_gt": left > right, "_lt": left < right}[op]


def _contains_text(value: Any, needle: str) -> bool:
    if isinstance(value, dict):
        return any(_contains_text(v, needle) for v in value.values())
    if isinstance(value, list):
        return any(_contains_text(v, needle) for v in value)
    return value is not None and needle in _as_text(value).lower()


class Collection:
    def __init__(self, spec: Resource, renderer: Renderer) -> None:
        self.spec = spec
        self.renderer = renderer
        self.items: list[dict[str, Any]] = []
        self.reset()

    def reset(self) -> None:
        items = copy.deepcopy(self.spec.seed)
        for i in range(self.spec.generate_count):
            item = self.renderer.render(self.spec.generate_item, {"index": i})
            if not isinstance(item, dict):
                item = {"value": item}
            items.append(item)
        self.items = []
        for item in items:
            if self.spec.id_field not in item:
                item = {self.spec.id_field: self._next_id(), **item}
            self.items.append(item)

    # -- helpers ------------------------------------------------------------
    def _next_id(self) -> Any:
        ids = [item.get(self.spec.id_field) for item in self.items]
        if all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
            return max(ids, default=0) + 1
        return str(uuid.uuid4())

    def _index(self, item_id: str) -> int:
        for i, item in enumerate(self.items):
            if _as_text(item.get(self.spec.id_field)) == item_id:
                return i
        raise ResourceError(404, f"{self.spec.name} {item_id} not found")

    def _check_writable(self) -> None:
        if self.spec.readonly:
            raise ResourceError(405, f"{self.spec.name} is read-only")

    @staticmethod
    def _object(body: Any) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise ResourceError(400, "request body must be a JSON object")
        return body

    # -- queries ------------------------------------------------------------
    def query(self, params: Mapping[str, list[str]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Filter, sort and paginate. Returns the page and metadata (total, page, per_page, pages)."""
        items = list(self.items)
        for key, values in params.items():
            if key in RESERVED:
                continue
            op = next((o for o in OPERATORS if key.endswith(o) and len(key) > len(o)), "")
            field = key[: -len(op)] if op else key
            items = [item for item in items if _matches(item, field, op, values)]

        needle = (params.get("q") or params.get("_q") or [""])[-1].strip().lower()
        if needle:
            items = [item for item in items if _contains_text(item, needle)]

        sort_spec = (params.get("sort") or params.get("_sort") or [""])[-1]
        orders = ((params.get("_order") or params.get("order") or [""])[-1]).split(",")
        sort_fields = [f.strip() for f in sort_spec.split(",") if f.strip()]
        # Stable sort: apply the least significant key first.
        for position in range(len(sort_fields) - 1, -1, -1):
            name = sort_fields[position]
            descending = name.startswith("-")
            name = name.lstrip("-+")
            if position < len(orders) and orders[position].strip().lower() == "desc":
                descending = True
            items.sort(key=lambda item, n=name: _compare_key(lookup(item, n)), reverse=descending)

        total = len(items)
        last = lambda *names: next((params[n][-1] for n in names if params.get(n)), None)  # noqa: E731
        per_page = _int(last("per_page", "_per_page", "limit", "_limit"), "per_page", 1)
        page = _int(last("page", "_page"), "page", 1)
        offset = _int(last("offset", "_start"), "offset", 0)
        paginate = per_page is not None or page is not None or offset is not None or self.spec.envelope
        meta: dict[str, Any] = {"total": total}
        if paginate:
            per_page = min(per_page or self.spec.per_page, self.spec.max_per_page)
            if offset is None:
                page = page or 1
                offset = (page - 1) * per_page
            else:
                page = offset // per_page + 1
            items = items[offset : offset + per_page]
            meta.update(page=page, per_page=per_page, pages=math.ceil(total / per_page) if total else 0)
        return items, meta

    def get(self, item_id: str) -> dict[str, Any]:
        return self.items[self._index(item_id)]

    def create(self, body: Any) -> dict[str, Any]:
        self._check_writable()
        item = dict(self._object(body))
        id_field = self.spec.id_field
        if item.get(id_field) in (None, ""):
            item = {id_field: self._next_id(), **{k: v for k, v in item.items() if k != id_field}}
        elif any(_as_text(existing.get(id_field)) == _as_text(item[id_field]) for existing in self.items):
            raise ResourceError(409, f"{self.spec.name} {item[id_field]} already exists")
        self.items.append(item)
        return item

    def replace(self, item_id: str, body: Any) -> dict[str, Any]:
        self._check_writable()
        index = self._index(item_id)
        current_id = self.items[index][self.spec.id_field]
        item = {
            self.spec.id_field: current_id,
            **{k: v for k, v in self._object(body).items() if k != self.spec.id_field},
        }
        self.items[index] = item
        return item

    def update(self, item_id: str, body: Any) -> dict[str, Any]:
        self._check_writable()
        index = self._index(item_id)
        changes = {k: v for k, v in self._object(body).items() if k != self.spec.id_field}
        self.items[index] = {**self.items[index], **changes}
        return self.items[index]

    def delete(self, item_id: str) -> None:
        self._check_writable()
        del self.items[self._index(item_id)]
