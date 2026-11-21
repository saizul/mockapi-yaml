import time


def test_global_and_route_latency(mock, harness):
    client = mock(
        """
        settings: { latency: 100 }
        routes:
          - path: /default
            body: 1
          - path: /slow
            latency: "300-400"
            body: 1
          - path: /fast
            latency: 0
            body: 1
        """
    )
    client.get("/default")
    client.get("/slow")
    client.get("/fast")
    calls = harness.sleeper.calls
    assert calls[0] == 0.1
    assert 0.3 <= calls[1] <= 0.4
    assert len(calls) == 2


def test_error_rate_injects_configured_error(mock):
    client = mock(
        """
        settings:
          error_rate: 1
          error: { status: 503, body: { error: down }, headers: { Retry-After: "5" } }
        routes:
          - path: /flaky
            body: ok
          - path: /stable
            error_rate: 0
            body: ok
          - path: /teapot
            error_rate: 1
            error: { status: 418 }
            body: ok
        """
    )
    resp = client.get("/flaky")
    assert resp.status_code == 503
    assert resp.json() == {"error": "down"}
    assert resp.headers["retry-after"] == "5"
    assert "injected error" in resp.headers["x-mock-source"]
    assert client.get("/stable").text == "ok"
    teapot = client.get("/teapot")
    assert teapot.status_code == 418
    assert teapot.json()["error"].startswith("Injected failure")


def test_error_rate_is_probabilistic_and_seeded(mock):
    client = mock(
        """
        settings: { error_rate: 0.5, seed: 1 }
        routes:
          - path: /x
            body: ok
        """
    )
    statuses = [client.get("/x").status_code for _ in range(200)]
    failures = statuses.count(500)
    assert 60 < failures < 140


def test_404_is_never_turned_into_injected_error(mock):
    client = mock("settings: { error_rate: 1 }\n")
    assert client.get("/missing").status_code == 404


def test_cors_preflight_and_simple_requests(mock):
    client = mock(
        """
        routes:
          - method: POST
            path: /x
            body: 1
        """
    )
    pre = client.options(
        "/x",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type, authorization",
        },
    )
    assert pre.status_code == 200
    assert pre.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert pre.headers["access-control-allow-credentials"] == "true"
    assert "authorization" in pre.headers["access-control-allow-headers"].lower()
    simple = client.post("/x", headers={"Origin": "http://localhost:3000"})
    assert simple.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "x-total-count" in simple.headers["access-control-expose-headers"].lower()


def test_cors_origin_list_and_disabled(mock, harness):
    client = mock(
        """
        settings: { cors: ["http://app.test"] }
        routes: [{ path: /x, body: 1 }]
        """
    )
    assert (
        client.get("/x", headers={"Origin": "http://app.test"}).headers["access-control-allow-origin"]
        == "http://app.test"
    )
    assert "access-control-allow-origin" not in client.get("/x", headers={"Origin": "http://evil.test"}).headers
    client = mock("settings: { cors: false }\nroutes: [{ path: /x, body: 1 }]\n")
    assert "access-control-allow-origin" not in client.get("/x", headers={"Origin": "http://app.test"}).headers


def test_hot_reload_picks_up_changes(mock, harness):
    client = mock("routes: [{ path: /v, body: one }]\n")
    assert client.get("/v").text == "one"
    harness.write("routes: [{ path: /v, body: two }]\n")
    # Within the reload interval the old definition is still served.
    assert client.get("/v").text == "one"
    harness.clock.advance(2)
    _bump_mtime(harness.path)
    assert client.get("/v").text == "two"
    assert harness.app.reloads == 1


def test_hot_reload_restarts_response_sequences(mock, harness):
    client = mock("routes: [{ path: /s, responses: [{ body: a }, { body: b }] }]\n")
    assert [client.get("/s").text for _ in range(2)] == ["a", "b"]
    harness.write("routes: [{ path: /s, responses: [{ body: a }, { body: c }] }]\n")
    harness.clock.advance(2)
    _bump_mtime(harness.path)
    assert [client.get("/s").text for _ in range(2)] == ["a", "c"]


def test_hot_reload_keeps_old_definition_on_error(mock, harness):
    client = mock("routes: [{ path: /v, body: one }]\n")
    harness.write("routes: [{ path: v-without-slash }]\n")
    harness.clock.advance(2)
    _bump_mtime(harness.path)
    assert client.get("/v").text == "one"
    health = client.get("/__mockapi/health").json()
    assert "must start with '/'" in health["reload_error"]
    harness.write("routes: [{ path: /v, body: fixed }]\n")
    harness.clock.advance(2)
    _bump_mtime(harness.path)
    assert client.get("/v").text == "fixed"
    assert client.get("/__mockapi/health").json()["reload_error"] is None


def test_hot_reload_watches_body_files_and_keeps_unchanged_resources(mock, harness):
    harness.write('{"v": 1}', "data.json")
    client = mock(
        """
        resources: [notes]
        routes: [{ path: /data, file: data.json }]
        """
    )
    client.post("/notes", json={"text": "keep me"})
    harness.write('{"v": 2}', "data.json")
    harness.clock.advance(2)
    _bump_mtime(harness.tmp_path / "data.json")
    assert client.get("/data").json() == {"v": 2}
    assert harness.app.reloads == 1
    assert client.get("/notes").json() == [{"id": 1, "text": "keep me"}]


def test_reload_can_be_disabled(mock, harness):
    client = mock("routes: [{ path: /v, body: one }]\n", reload=False)
    harness.write("routes: [{ path: /v, body: two }]\n")
    harness.clock.advance(2)
    _bump_mtime(harness.path)
    assert client.get("/v").text == "one"
    assert client.post("/__mockapi/reload").status_code == 409


def test_forced_reload_endpoint(mock, harness):
    client = mock("routes: [{ path: /v, body: one }]\n")
    harness.write("routes: [{ path: /v, body: two }]\n")
    resp = client.post("/__mockapi/reload")
    assert resp.status_code == 200
    assert client.get("/v").text == "two"
    harness.write("routes: nope\n")
    assert client.post("/__mockapi/reload").status_code == 422


def test_request_log(mock):
    client = mock("routes: [{ method: POST, path: /x, body: 1 }]\n")
    client.post("/x?debug=1", json={"a": 1})
    client.get("/missing")
    entries = client.get("/__mockapi/log").json()
    assert [e["status"] for e in entries] == [200, 404]
    first = entries[0]
    assert first["method"] == "POST"
    assert first["path"] == "/x"
    assert first["query"] == "debug=1"
    assert first["body"] == '{"a":1}' or first["body"] == '{"a": 1}'
    assert first["source"] == "routes[0]"
    assert client.get("/__mockapi/log?limit=1").json()[0]["path"] == "/missing"
    assert client.delete("/__mockapi/log").status_code == 204
    assert client.get("/__mockapi/log").json() == []


def test_request_log_size_limit(mock):
    client = mock("settings: { log_size: 2 }\nroutes: [{ path: /x, body: 1 }]\n")
    for _ in range(5):
        client.get("/x")
    assert len(client.get("/__mockapi/log").json()) == 2


def test_admin_routes_listing_and_unknown(mock):
    client = mock(
        """
        resources: [users]
        routes: [{ name: ping, path: /ping, body: pong }]
        """
    )
    info = client.get("/__mockapi/routes").json()
    assert info["routes"][0]["name"] == "ping"
    assert info["resources"][0]["path"] == "/users"
    assert client.get("/__mockapi/nope").status_code == 404


def test_large_request_body_rejected(mock):
    client = mock("routes: [{ method: POST, path: /x, body: 1 }]\n")
    resp = client.post("/x", content=b"x" * (10 * 1024 * 1024 + 1))
    assert resp.status_code == 413


def _bump_mtime(path):
    stat = path.stat()
    later = stat.st_mtime + 5
    import os

    os.utime(path, (later, later))
    assert path.stat().st_mtime_ns != stat.st_mtime_ns or time.time()
