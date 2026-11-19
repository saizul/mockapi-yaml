import re

import pytest

from mockapi_yaml.fake import HELPERS, Fake
from mockapi_yaml.templating import Renderer, TemplateError, validate_templates

CTX = {
    "params": {"id": "42"},
    "query": {"page": "2", "flag": "true"},
    "headers": {"x-user": "ada"},
    "body": {"user": {"name": "Ada", "tags": ["a", "b"]}},
}


@pytest.fixture
def renderer() -> Renderer:
    return Renderer(Fake(1))


def test_plain_strings_are_untouched(renderer):
    assert renderer.render("hello", CTX) == "hello"
    assert renderer.render(5, CTX) == 5


def test_path_lookup_keeps_native_type_when_whole_string(renderer):
    assert renderer.render("{{params.id}}", CTX) == "42"
    assert renderer.render("{{ params.id | int }}", CTX) == 42
    assert renderer.render("{{body.user}}", CTX) == {"name": "Ada", "tags": ["a", "b"]}
    assert renderer.render("{{body.user.tags.1}}", CTX) == "b"
    assert renderer.render("{{query.flag | bool}}", CTX) is True


def test_interpolation_in_longer_strings(renderer):
    assert renderer.render("user {{params.id}} page {{query.page}}", CTX) == "user 42 page 2"
    assert renderer.render("missing: [{{params.nope}}]", CTX) == "missing: []"
    assert renderer.render("tags={{body.user.tags}}", CTX) == 'tags=["a", "b"]'


def test_headers_are_case_insensitive(renderer):
    assert renderer.render("{{headers.X-User}}", CTX) == "ada"


def test_filters(renderer):
    assert renderer.render("{{params.nope | default('anon')}}", CTX) == "anon"
    assert renderer.render("{{headers.x-user | upper}}", CTX) == "ADA"
    assert renderer.render("{{query.page | float}}", CTX) == 2.0
    assert renderer.render("{{body.user.tags | length}}", CTX) == 2
    assert renderer.render("{{body.user | json}}", CTX) == '{"name": "Ada", "tags": ["a", "b"]}'
    with pytest.raises(TemplateError):
        renderer.render("{{params.id | explode}}", CTX)


def test_faker_helpers(renderer):
    assert isinstance(renderer.render("{{faker.name}}", CTX), str)
    value = renderer.render("{{faker.int(5, 7)}}", CTX)
    assert isinstance(value, int) and 5 <= value <= 7
    assert re.fullmatch(r"[^@]+@example\.(com|org|net)", renderer.render("{{faker.email}}", CTX))
    assert renderer.render("{{faker.email('acme.test')}}", CTX).endswith("@acme.test")
    assert renderer.render("{{faker.pick('a', 'b')}}", CTX) in ("a", "b")
    assert re.fullmatch(r"[0-9a-f-]{36}", renderer.render("{{faker.uuid}}", CTX))
    assert renderer.render("{{faker.ipv4}}", CTX).startswith(("192.0.2.", "198.51.100.", "203.0.113."))


def test_every_helper_runs_without_arguments():
    fake = Fake(3)
    for name in HELPERS:
        getattr(fake, name)()


def test_seed_makes_output_reproducible():
    template = {"a": "{{faker.name}}", "b": "{{faker.int(1, 1000000)}}"}
    assert Renderer(Fake(7)).render(template, {}) == Renderer(Fake(7)).render(template, {})


def test_builtin_functions(renderer):
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", renderer.render("{{now}}", CTX))
    assert isinstance(renderer.render("{{timestamp}}", CTX), int)
    assert len(renderer.render("{{uuid}}", CTX)) == 36


def test_unknown_helper_raises(renderer):
    with pytest.raises(TemplateError):
        renderer.render("{{faker.nope}}", CTX)
    with pytest.raises(TemplateError):
        renderer.render("{{faker.int('a', 'b')}}", CTX)
    with pytest.raises(TemplateError):
        renderer.render("{{shout()}}", CTX)


def test_repeat(renderer):
    out = renderer.render({"$repeat": 3, "$item": {"n": "#{{index}}", "id": "{{index}}"}}, CTX)
    assert out == [{"n": "#0", "id": 0}, {"n": "#1", "id": 1}, {"n": "#2", "id": 2}]
    ranged = renderer.render({"$repeat": "2-4", "$item": 1}, CTX)
    assert 2 <= len(ranged) <= 4
    templated = renderer.render({"$repeat": "{{query.page}}", "$item": "x"}, CTX)
    assert templated == ["x", "x"]
    with pytest.raises(TemplateError):
        renderer.render({"$repeat": "lots"}, CTX)


def test_repeat_is_capped(renderer):
    assert len(renderer.render({"$repeat": 10**9, "$item": 0}, CTX)) == 10_000


def test_literals(renderer):
    assert renderer.render("{{'text'}}", CTX) == "text"
    assert renderer.render("{{12}}", CTX) == 12
    assert renderer.render("{{true}}", CTX) is True


def test_validate_templates_reports_paths():
    problems = validate_templates({"a": ["{{faker.nope}}"], "b": "{{params.id}}"}, "routes[0].body")
    assert problems == ["routes[0].body.a[0]: unknown faker helper: faker.nope"]
