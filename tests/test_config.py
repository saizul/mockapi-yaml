from pathlib import Path

import pytest

from mockapi_yaml.config import ConfigError, Latency, compile_path, load_config, parse_config, parse_latency

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, Latency()), (0, Latency()), (150, Latency(150, 150)), ("100-400", Latency(100, 400)),
     ("250ms", Latency(250, 250)), ({"min": 10, "max": 20}, Latency(10, 20))],
)  # fmt: skip
def test_parse_latency(value, expected):
    assert parse_latency(value, "x") == expected


@pytest.mark.parametrize("value", ["fast", "400-100", -5, True, {"min": 1, "avg": 2}, 999_999])
def test_parse_latency_rejects(value):
    with pytest.raises(ConfigError):
        parse_latency(value, "x")


def test_compile_path():
    assert compile_path("/a/{id}").match("/a/1").groupdict() == {"id": "1"}
    assert compile_path("/a/{id}").match("/a/1/b") is None
    assert compile_path("/a/:id/b").match("/a/x/b/").groupdict() == {"id": "x"}
    assert compile_path("/").match("/")
    assert compile_path("/dots.json").match("/dotsxjson") is None


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ([1], "must be a mapping"),
        ({"rotues": []}, "unknown key"),
        ({"routes": {}}, "routes must be a list"),
        ({"routes": [{"path": "x"}]}, "must start with '/'"),
        ({"routes": [{"path": "/x", "methd": "GET"}]}, "unknown key"),
        ({"routes": [{"path": "/x", "method": "FETCH"}]}, "unknown HTTP method"),
        ({"routes": [{"path": "/x", "status": 700}]}, "status"),
        ({"routes": [{"path": "/x", "body": 1, "file": "a.json"}]}, "either body or file"),
        ({"routes": [{"path": "/x", "file": "missing.json"}]}, "does not exist"),
        ({"routes": [{"path": "/x", "body": "{{faker.nope}}"}]}, "unknown faker helper"),
        ({"routes": [{"path": "/x", "error_rate": 2}]}, "between 0 and 1"),
        ({"routes": [{"path": "/x", "match": {"cookies": {}}}]}, "unknown key"),
        ({"settings": {"cors": 5}}, "settings.cors"),
        ({"settings": {"seed": "abc"}}, "seed"),
        ({"settings": {"base_path": "api"}}, "base_path"),
        ({"resources": {"bad name": {}}}, "letters, digits"),
        ({"resources": {"a": {"seed": [1]}}}, "list of objects"),
        ({"resources": {"a": {"generate": {"count": -1}}}}, "count"),
        ({"resources": {"a": {"per_page": 0}}}, "per_page"),
        ({"resources": {"a": {"path": "/x"}, "b": {"path": "/x"}}}, "already used"),
        ({"resources": 5}, "resources must be"),
        ({"openapi": "missing.yaml"}, "does not exist"),
    ],
)
def test_invalid_configs(tmp_path, data, message):
    with pytest.raises(ConfigError, match=message):
        parse_config(data, tmp_path)


def test_empty_file_is_valid(tmp_path):
    path = tmp_path / "mock.yaml"
    path.write_text("", "utf-8")
    config = load_config(path)
    assert config.routes == [] and config.resources == {}


def test_invalid_yaml_reports_file(tmp_path):
    path = tmp_path / "mock.yaml"
    path.write_text("routes: [", "utf-8")
    with pytest.raises(ConfigError, match=r"mock\.yaml"):
        load_config(path)


def test_methods_any(tmp_path):
    config = parse_config({"routes": [{"path": "/x", "method": "*"}]}, tmp_path)
    assert "DELETE" in config.routes[0].methods


@pytest.mark.parametrize("name", ["mock.yaml", "openapi.yaml"])
def test_examples_are_valid(name):
    config = load_config(ROOT / "examples" / name)
    assert config.routes or config.resources or config.openapi
