import pytest

USERS = """
resources:
  users:
    seed:
      - { id: 1, name: Ada, role: admin, age: 36, team: { name: core } }
      - { id: 2, name: Linus, role: dev, age: 28, team: { name: kernel } }
      - { id: 3, name: Grace, role: admin, age: 45, team: { name: core } }
      - { id: 4, name: Alan, role: dev, age: 41, team: { name: crypto } }
"""


@pytest.fixture
def client(mock):
    return mock(USERS)


def names(resp):
    return [u["name"] for u in resp.json()]


def test_list_returns_array_with_total(client):
    resp = client.get("/users")
    assert resp.status_code == 200
    assert len(resp.json()) == 4
    assert resp.headers["x-total-count"] == "4"
    assert "link" not in resp.headers


def test_get_one_and_404(client):
    assert client.get("/users/2").json()["name"] == "Linus"
    missing = client.get("/users/99")
    assert missing.status_code == 404
    assert missing.json() == {"error": "users 99 not found"}


def test_filters(client):
    assert names(client.get("/users?role=admin")) == ["Ada", "Grace"]
    assert names(client.get("/users?role=admin&role=dev")) == ["Ada", "Linus", "Grace", "Alan"]
    assert names(client.get("/users?team.name=core")) == ["Ada", "Grace"]
    assert names(client.get("/users?age_gte=40")) == ["Grace", "Alan"]
    assert names(client.get("/users?age_lt=30")) == ["Linus"]
    assert names(client.get("/users?role_ne=admin")) == ["Linus", "Alan"]
    assert names(client.get("/users?name_like=a")) == ["Ada", "Grace", "Alan"]
    assert names(client.get("/users?q=kern")) == ["Linus"]


def test_sorting(client):
    assert names(client.get("/users?sort=name")) == ["Ada", "Alan", "Grace", "Linus"]
    assert names(client.get("/users?sort=-age")) == ["Grace", "Alan", "Ada", "Linus"]
    assert names(client.get("/users?_sort=age&_order=desc")) == ["Grace", "Alan", "Ada", "Linus"]
    assert names(client.get("/users?sort=role,-age")) == ["Grace", "Ada", "Alan", "Linus"]


def test_pagination_page_style(client):
    resp = client.get("/users?page=2&per_page=3")
    assert names(resp) == ["Alan"]
    assert resp.headers["x-total-count"] == "4"
    link = resp.headers["link"]
    assert 'rel="prev"' in link and 'rel="first"' in link and 'rel="last"' in link
    assert 'rel="next"' not in link
    assert names(client.get("/users?_page=1&_limit=2")) == ["Ada", "Linus"]


def test_pagination_offset_style(client):
    assert names(client.get("/users?offset=1&limit=2")) == ["Linus", "Grace"]
    assert names(client.get("/users?_start=3&_limit=10")) == ["Alan"]


def test_bad_pagination_values(client):
    assert client.get("/users?page=0").status_code == 400
    assert client.get("/users?per_page=abc").status_code == 400


def test_create_assigns_incrementing_id(client):
    resp = client.post("/users", json={"name": "Margaret"})
    assert resp.status_code == 201
    assert resp.json() == {"id": 5, "name": "Margaret"}
    assert resp.headers["location"] == "/users/5"
    assert client.get("/users/5").json()["name"] == "Margaret"


def test_create_with_existing_id_conflicts(client):
    assert client.post("/users", json={"id": 1, "name": "dup"}).status_code == 409
    assert client.post("/users", json={"id": "x9", "name": "custom"}).json()["id"] == "x9"


def test_create_requires_object(client):
    assert client.post("/users", json=[1, 2]).status_code == 400
    assert client.post("/users", content=b"not json").status_code == 400


def test_put_replaces_patch_merges(client):
    put = client.put("/users/1", json={"name": "Ada L.", "id": 999})
    assert put.json() == {"id": 1, "name": "Ada L."}
    patch = client.patch("/users/2", json={"age": 29})
    assert patch.json()["age"] == 29 and patch.json()["name"] == "Linus"
    assert client.patch("/users/42", json={}).status_code == 404


def test_delete(client):
    assert client.delete("/users/3").status_code == 204
    assert client.get("/users/3").status_code == 404
    assert client.delete("/users/3").status_code == 404
    assert client.get("/users").headers["x-total-count"] == "3"


def test_method_not_allowed_on_resource(client):
    assert client.delete("/users").status_code == 405
    assert client.post("/users/1").status_code == 405
    assert "GET" in client.post("/users/1").headers["allow"]


def test_reset_restores_seed(client):
    client.delete("/users/1")
    client.post("/users", json={"name": "x"})
    assert client.post("/__mockapi/reset").status_code == 200
    assert names(client.get("/users")) == ["Ada", "Linus", "Grace", "Alan"]


def test_generated_resource_with_envelope(mock):
    client = mock(
        """
        settings: { seed: 3 }
        resources:
          products:
            path: /shop/products
            envelope: true
            per_page: 5
            generate:
              count: 12
              item:
                sku: "SKU-{{index}}"
                title: "{{faker.words(2)}}"
                price: "{{faker.price(1, 99)}}"
        """
    )
    resp = client.get("/shop/products?page=3")
    data = resp.json()
    assert data["meta"] == {"total": 12, "page": 3, "per_page": 5, "pages": 3}
    assert [p["sku"] for p in data["data"]] == ["SKU-10", "SKU-11"]
    assert data["data"][0]["id"] == 11
    assert isinstance(data["data"][0]["price"], float)


def test_uuid_ids_and_custom_id_field(mock):
    client = mock(
        """
        resources:
          posts:
            id_field: slug
            seed: [{ slug: hello, title: Hello }]
        """
    )
    created = client.post("/posts", json={"title": "Next"}).json()
    assert len(created["slug"]) == 36
    assert client.get("/posts/hello").json()["title"] == "Hello"


def test_readonly_resource(mock):
    client = mock("resources: { countries: { readonly: true, seed: [{ id: 1, name: X }] } }\n")
    assert client.get("/countries").status_code == 200
    assert client.post("/countries", json={"name": "Y"}).status_code == 405


def test_seed_from_file(mock, harness):
    harness.write('[{"id": 1, "title": "from file"}]', "todos.json")
    client = mock("resources: { todos: { seed: todos.json } }\n")
    assert client.get("/todos/1").json()["title"] == "from file"


def test_max_per_page_cap(mock):
    client = mock("resources: { n: { per_page: 2, max_per_page: 3, generate: { count: 10, item: {} } } }\n")
    assert len(client.get("/n?per_page=100").json()) == 3


def test_routes_take_precedence_over_resources(mock):
    client = mock(
        """
        resources: [users]
        routes:
          - path: /users/me
            body: { me: true }
        """
    )
    assert client.get("/users/me").json() == {"me": True}
    assert client.get("/users/1").status_code == 404
