import json

import pytest

from mockapi_yaml.config import ConfigError
from mockapi_yaml.openapi import Resolver, operations_from_document, parse_prefer

SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "Pets", "version": "1"},
    "paths": {
        "/pets": {
            "get": {
                "operationId": "listPets",
                "responses": {
                    "200": {
                        "description": "ok",
                        "headers": {"X-Rate-Limit": {"schema": {"type": "integer", "example": 100}}},
                        "content": {
                            "application/json": {
                                "schema": {"type": "array", "items": {"$ref": "#/components/schemas/Pet"}}
                            }
                        },
                    }
                },
            },
            "post": {
                "operationId": "createPet",
                "responses": {
                    "201": {
                        "description": "created",
                        "content": {"application/json": {"example": {"id": 10, "name": "{{body.name}}"}}},
                    },
                    "400": {"$ref": "#/components/responses/BadRequest"},
                },
            },
        },
        "/pets/mine": {"get": {"operationId": "myPets", "responses": {"200": {"description": "ok"}}}},
        "/pets/{petId}": {
            "get": {
                "operationId": "showPet",
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "examples": {
                                    "cat": {"value": {"id": 1, "name": "Tom"}},
                                    "dog": {"$ref": "#/components/examples/Dog"},
                                }
                            }
                        },
                    },
                    "4XX": {
                        "description": "client error",
                        "content": {"application/json": {"example": {"error": "client error"}}},
                    },
                    "default": {
                        "description": "error",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
                    },
                },
            }
        },
        "/text": {
            "get": {"responses": {"200": {"description": "ok", "content": {"text/plain": {"example": "hello"}}}}}
        },
    },
    "components": {
        "schemas": {
            "Pet": {
                "type": "object",
                "required": ["id", "name"],
                "properties": {
                    "id": {"type": "integer", "format": "int64"},
                    "name": {"type": "string", "example": "Rex"},
                    "tag": {"type": "string", "enum": ["dog", "cat"]},
                    "born": {"type": "string", "format": "date"},
                    "owner": {
                        "allOf": [{"$ref": "#/components/schemas/Owner"}, {"properties": {"vip": {"type": "boolean"}}}]
                    },
                },
            },
            "Owner": {"type": "object", "properties": {"email": {"type": "string", "format": "email"}}},
            "Error": {"type": "object", "properties": {"code": {"type": "integer"}, "message": {"type": "string"}}},
        },
        "responses": {
            "BadRequest": {
                "description": "bad",
                "content": {"application/json": {"example": {"error": "bad request"}}},
            }
        },
        "examples": {"Dog": {"value": {"id": 2, "name": "Rex"}}},
    },
}


@pytest.fixture
def client(mock, harness):
    harness.write(json.dumps(SPEC), "openapi.json")
    return mock("openapi: openapi.json\n")


def test_generated_example_from_schema(client):
    resp = client.get("/pets")
    assert resp.status_code == 200
    assert resp.headers["x-rate-limit"] == "100"
    assert resp.json() == [
        {
            "id": 0,
            "name": "Rex",
            "tag": "dog",
            "born": "2026-01-01",
            "owner": {"email": "user@example.com", "vip": True},
        }
    ]
    assert resp.headers["x-mock-source"] == "openapi listPets"


def test_media_example_is_templated(client):
    resp = client.post("/pets", json={"name": "Nemo"})
    assert resp.status_code == 201
    assert resp.json() == {"id": 10, "name": "Nemo"}


def test_named_examples_and_prefer_header(client):
    assert client.get("/pets/5").json() == {"id": 1, "name": "Tom"}
    assert client.get("/pets/5", headers={"Prefer": "example=dog"}).json() == {"id": 2, "name": "Rex"}
    assert client.get("/pets/5?__example=dog").json()["name"] == "Rex"


def test_status_selection(client):
    bad = client.post("/pets", headers={"Prefer": "code=400"})
    assert bad.status_code == 400 and bad.json() == {"error": "bad request"}
    wildcard = client.get("/pets/5?__code=404")
    assert wildcard.status_code == 404 and wildcard.json() == {"error": "client error"}
    default = client.get("/pets/5?__code=503")
    assert default.status_code == 503 and default.json() == {"code": 0, "message": "string"}


def test_literal_path_wins_and_empty_response(client):
    resp = client.get("/pets/mine")
    assert resp.status_code == 200
    assert resp.headers["x-mock-source"] == "openapi myPets"
    assert resp.content == b""


def test_non_json_media_type(client):
    resp = client.get("/text")
    assert resp.text == "hello"
    assert resp.headers["content-type"].startswith("text/plain")


def test_method_not_allowed_for_openapi_path(client):
    assert client.delete("/pets").status_code == 405


def test_bare_openapi_file_can_be_the_config(harness):
    harness.path = harness.write(json.dumps(SPEC), "spec.json")
    client = harness.client()
    assert client.get("/pets/1").json()["name"] == "Tom"


def test_routes_override_openapi(mock, harness):
    harness.write(json.dumps(SPEC), "openapi.json")
    client = mock("openapi: openapi.json\nroutes: [{ path: '/pets/{id}', body: { overridden: true } }]\n")
    assert client.get("/pets/1").json() == {"overridden": True}


def test_rejects_swagger_2_and_garbage():
    with pytest.raises(ConfigError, match="only OpenAPI 3"):
        operations_from_document({"swagger": "2.0", "paths": {}})
    with pytest.raises(ConfigError, match="no 'paths'"):
        operations_from_document({"openapi": "3.0.0"})


def test_schema_sampler_edge_cases():
    resolver = Resolver(
        {
            "components": {
                "schemas": {"Node": {"type": "object", "properties": {"next": {"$ref": "#/components/schemas/Node"}}}}
            }
        }
    )
    deep = resolver.sample({"$ref": "#/components/schemas/Node"})
    depth = 0
    while isinstance(deep, dict) and deep.get("next") is not None:
        deep = deep["next"]
        depth += 1
    assert depth <= 9
    assert resolver.sample({"type": ["string", "null"], "format": "uuid"}) == "3fa85f64-5717-4562-b3fc-2c963f66afa6"
    assert resolver.sample({"oneOf": [{"type": "integer", "minimum": 5}]}) == 5
    assert resolver.sample({"type": "array", "items": {"type": "number"}, "minItems": 2}) == [0.0, 0.0]
    assert resolver.sample({"type": "object", "additionalProperties": {"type": "boolean"}}) == {"key": True}
    assert resolver.sample({"type": "string", "minLength": 10}) == "stringxxxx"
    assert resolver.sample({"$ref": "#/missing"}) is None
    assert resolver.sample({"$ref": "http://elsewhere/schema.json"}) is None


def test_parse_prefer():
    assert parse_prefer('code=404, example="notFound"') == {"code": "404", "example": "notFound"}
    assert parse_prefer("") == {}
