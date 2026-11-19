from pathlib import Path

from mockapi_yaml.cli import main

ROOT = Path(__file__).resolve().parent.parent


def test_version(capsys):
    try:
        main(["--version"])
    except SystemExit as exc:
        assert exc.code == 0
    assert "mockapi" in capsys.readouterr().out


def test_init_then_check(tmp_path, capsys):
    path = tmp_path / "mock.yaml"
    assert main(["init", str(path)]) == 0
    assert main(["init", str(path)]) == 1
    assert main(["-c", str(path), "check"]) == 0
    out = capsys.readouterr().out
    assert "resource  /users  (25 items)" in out
    assert "config OK" in out


def test_check_example_with_openapi(capsys):
    assert main(["-c", str(ROOT / "examples" / "mock.yaml"), "check"]) == 0
    assert "openapi" in capsys.readouterr().out


def test_check_reports_errors(tmp_path, capsys):
    path = tmp_path / "mock.yaml"
    path.write_text("routes: [{ path: nope }]\n", "utf-8")
    assert main(["-c", str(path), "check"]) == 2
    assert "must start with '/'" in capsys.readouterr().err


def test_config_from_environment(tmp_path, monkeypatch, capsys):
    path = tmp_path / "custom.yaml"
    path.write_text("routes: [{ path: /x }]\n", "utf-8")
    monkeypatch.setenv("MOCKAPI_CONFIG", str(path))
    assert main(["check"]) == 0
    assert "/x" in capsys.readouterr().out
