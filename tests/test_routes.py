import json


def test_static_route_and_source_header(mock):
    client = mock(
        """
        routes:
          - path: /health
            body: { ok: true }
        """
    )
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.headers["x-mock-source"] == "routes[0]"


def test_path_params_both_syntaxes_and_trailing_slash(mock):
    client = mock(
        """
        routes:
          - path: /users/{id}
            body: { id: "{{params.id | int}}", label: "user-{{params.id}}" }
          - path: /orgs/:org/repos/:repo
            body: "{{params.org}}/{{params.repo}}"
          - path: /files/{rest:path}
            body: { path: "{{params.rest}}" }
        """
    )
    assert client.get("/users/7").json() == {"id": 7, "label": "user-7"}
    assert client.get("/users/7/").json()["id"] == 7
    resp = client.get("/orgs/acme/repos/site")
    assert resp.text == "acme/site"
    assert resp.headers["content-type"].startswith("text/plain")
    assert client.get("/files/a/b/c.txt").json() == {"path": "a/b/c.txt"}


def test_methods_status_and_headers(mock):
    client = mock(
        """
        settings:
          headers: { X-Powered-By: mockapi }
        routes:
          - method: [POST, PUT]
            path: /items
            status: 201
            headers: { X-Request: "{{headers.x-trace}}", Location: /items/1 }
            body: { created: "{{body.name}}" }
          - method: DELETE
            path: /items/{id}
            status: 204
        """
    )
    resp = client.post("/items", json={"name": "lamp"}, headers={"X-Trace": "t-1"})
    assert resp.status_code == 201
    assert resp.json() == {"created": "lamp"}
    assert resp.headers["x-request"] == "t-1"
    assert resp.headers["location"] == "/items/1"
    assert resp.headers["x-powered-by"] == "mockapi"
    assert client.put("/items", json={"name": "x"}).status_code == 201
    deleted = client.delete("/items/1")
    assert deleted.status_code == 204 and deleted.content == b""


def test_method_not_allowed_and_not_found(mock):
    client = mock(
        """
        routes:
          - method: GET
            path: /only-get
            body: 1
        """
    )
    resp = client.post("/only-get")
    assert resp.status_code == 405
    assert resp.headers["allow"] == "GET"
    missing = client.get("/nothing")
    assert missing.status_code == 404
    assert "no mock for GET /nothing" in missing.json()["error"]


def test_head_uses_get_route(mock):
    client = mock(
        """
        routes:
          - path: /thing
            body: { a: 1 }
        """
    )
    resp = client.head("/thing")
    assert resp.status_code == 200
    assert resp.content == b""
    assert resp.headers["content-length"] == str(len(json.dumps({"a": 1}, separators=(", ", ": "))))


def test_query_header_and_body_matching_picks_first_match(mock):
    client = mock(
        """
        routes:
          - path: /search
            match: { query: { q: "/^err/" } }
            status: 500
            body: { error: boom }
          - path: /search
            match: { query: { q: "*", page: "2" } }
            body: { page: 2 }
          - path: /search
            match: { headers: { Authorization: "Bearer good" } }
            body: { authed: true }
          - path: /search
            body: { default: true }
          - method: POST
            path: /login
            match: { body: { user: { role: admin } } }
            body: { admin: true }
          - method: POST
            path: /login
            match: { body: { tags: [a] } }
            body: { tagged: true }
          - method: POST
            path: /login
            status: 401
        """
    )
    assert client.get("/search?q=error-1").status_code == 500
    assert client.get("/search?q=x&page=2").json() == {"page": 2}
    assert client.get("/search?page=2").json() == {"default": True}
    assert client.get("/search", headers={"Authorization": "Bearer good"}).json() == {"authed": True}
    assert client.get("/search").json() == {"default": True}
    assert client.post("/login", json={"user": {"role": "admin", "id": 1}}).json() == {"admin": True}
    assert client.post("/login", json={"tags": ["b", "a"]}).json() == {"tagged": True}
    assert client.post("/login", json={"user": {"role": "guest"}}).status_code == 401


def test_query_matching_with_list_of_options(mock):
    client = mock(
        """
        routes:
          - path: /color
            match: { query: { c: [red, blue] } }
            body: primary
          - path: /color
            body: other
        """
    )
    assert client.get("/color?c=blue").text == "primary"
    assert client.get("/color?c=green").text == "other"


def test_form_and_text_bodies_reach_templates(mock):
    client = mock(
        """
        routes:
          - method: POST
            path: /form
            body: { email: "{{body.email}}" }
          - method: POST
            path: /echo
            body: "{{body}}"
        """
    )
    assert client.post("/form", data={"email": "a@example.com"}).json() == {"email": "a@example.com"}
    resp = client.post("/echo", content=b"plain text", headers={"content-type": "text/plain"})
    assert resp.text == "plain text"


def test_body_from_file_is_templated(mock, harness):
    harness.write('{"id": "{{params.id}}", "items": [1, 2]}', "user.json")
    harness.write("<svg></svg>", "logo.svg")
    client = mock(
        """
        routes:
          - path: /users/{id}
            file: user.json
          - path: /logo
            file: logo.svg
        """
    )
    assert client.get("/users/9").json() == {"id": "9", "items": [1, 2]}
    logo = client.get("/logo")
    assert logo.headers["content-type"].startswith("image/svg+xml")
    assert logo.text == "<svg></svg>"


def test_explicit_content_type(mock):
    client = mock(
        """
        routes:
          - path: /xml
            headers: { Content-Type: application/xml }
            body: "<ok/>"
          - path: /json-string
            headers: { Content-Type: application/json }
            body: "just a string"
        """
    )
    resp = client.get("/xml")
    assert resp.headers["content-type"].startswith("application/xml")
    assert resp.text == "<ok/>"
    assert client.get("/json-string").json() == "just a string"


def test_base_path(mock):
    client = mock(
        """
        settings: { base_path: /api/v1 }
        routes:
          - path: /ping
            body: pong
        resources: [users]
        """
    )
    assert client.get("/api/v1/ping").text == "pong"
    assert client.get("/ping").status_code == 404
    created = client.post("/api/v1/users", json={"name": "a"})
    assert created.headers["location"] == "/api/v1/users/1"


def test_template_error_at_request_time_is_a_500(mock):
    client = mock(
        """
        routes:
          - path: /bad
            body: { n: "{{faker.int(1)}}" }
          - path: /worse
            body: { $repeat: "{{query.n}}", $item: 1 }
        """
    )
    assert client.get("/bad").status_code == 200
    resp = client.get("/worse?n=abc")
    assert resp.status_code == 500
    assert "template error" in resp.json()["error"]


def test_yaml_dates_serialize(mock):
    client = mock(
        """
        routes:
          - path: /d
            body: { day: 2026-01-02 }
        """
    )
    assert client.get("/d").json() == {"day": "2026-01-02"}


def test_response_sequence_answers_in_turn_then_repeats_the_last(mock):
    client = mock(
        """
        routes:
          - method: GET
            path: /jobs/{id}
            name: job-status
            headers: { X-Job: "{{params.id}}" }
            responses:
              - status: 202
                headers: { Retry-After: "1" }
                body: { state: queued }
              - status: 202
                body: { state: running }
              - body: { state: done, id: "{{params.id | int}}" }
        """
    )
    first = client.get("/jobs/7")
    assert first.status_code == 202
    assert first.json() == {"state": "queued"}
    assert first.headers["retry-after"] == "1"
    assert first.headers["x-job"] == "7"
    assert first.headers["x-mock-source"] == "routes[0] job-status responses[0]"
    second = client.get("/jobs/7")
    assert (second.status_code, second.json()) == (202, {"state": "running"})
    assert "retry-after" not in second.headers
    for _ in range(3):
        done = client.get("/jobs/7")
        assert (done.status_code, done.json()) == (200, {"state": "done", "id": 7})


def test_response_cycle_random_and_reset(mock, harness):
    harness.write('{"from": "file"}', "payload.json")
    client = mock(
        """
        settings: { seed: 3 }
        routes:
          - path: /flaky
            mode: cycle
            responses:
              - status: 503
              - file: payload.json
          - path: /coin
            mode: random
            responses:
              - body: heads
              - body: tails
        """
    )
    statuses = [client.get("/flaky").status_code for _ in range(4)]
    assert statuses == [503, 200, 503, 200]
    assert client.get("/flaky").status_code == 503
    assert client.post("/__mockapi/reset").status_code == 200
    resp = client.get("/flaky")
    assert resp.status_code == 503
    assert client.get("/flaky").json() == {"from": "file"}
    flips = {client.get("/coin").text for _ in range(40)}
    assert flips == {"heads", "tails"}
    routes = client.get("/__mockapi/routes").json()["routes"]
    assert routes[0]["responses"] == [503, 200]
    assert routes[0]["mode"] == "cycle"
    assert routes[0]["status"] == 503
