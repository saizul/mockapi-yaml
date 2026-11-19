# mockapi-yaml

[![CI](https://github.com/saizul/mockapi-yaml/actions/workflows/ci.yml/badge.svg)](https://github.com/saizul/mockapi-yaml/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/saizul/mockapi-yaml?sort=semver)](https://github.com/saizul/mockapi-yaml/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Container image](https://img.shields.io/badge/ghcr.io-saizul%2Fmockapi--yaml-2496ED?logo=docker&logoColor=white)](https://github.com/saizul/mockapi-yaml/pkgs/container/mockapi-yaml)
![Python](https://img.shields.io/badge/python-3.11%E2%80%933.13-blue)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

**A zero-code mock REST API for frontend developers.** Describe your endpoints in one
YAML file and you have a working API in seconds. You get templated JSON with fake data,
full CRUD resources with pagination and filters, OpenAPI 3 examples, added latency and
random errors, open CORS, hot reload and a request log. No JavaScript, no database,
no code.

```yaml
# mock.yaml
resources: [users, todos]          # full CRUD at /users and /todos

routes:
  - path: /me
    body: { id: 1, name: "{{faker.name}}", email: "{{faker.email}}" }

  - method: POST
    path: /login
    match: { body: { password: wrong } }
    status: 401
    body: { error: Invalid credentials }

  - method: POST
    path: /login
    latency: 400
    body: { token: "{{faker.hex(32)}}", user: "{{body.email}}" }
```

```bash
mockapi -c mock.yaml serve        # http://127.0.0.1:4010
```

## Contents

- [Features](#features)
- [Quick start](#quick-start)
- [Routes](#routes)
- [Templates](#templates)
- [Resources (CRUD)](#resources-crud)
- [OpenAPI 3](#openapi-3)
- [Latency and errors](#latency-and-errors)
- [CORS, hot reload and the request log](#cors-hot-reload-and-the-request-log)
- [Configuration reference](#configuration-reference)
- [CLI](#cli)
- [FAQ](#faq)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

## Features

- **Routes in YAML.** Method, path parameters (`/users/{id}` or `/users/:id`), status,
  headers, JSON or text body, or a body loaded from a file.
- **Request matching.** Serve different answers for different query parameters, headers or
  JSON bodies (`match:`). The first matching route wins.
- **Templates.** `{{params.id}}`, `{{query.page | int}}`, `{{body.email}}`,
  `{{headers.authorization}}`, `{{now}}`, `{{uuid}}` and 36 `{{faker.*}}` helpers. All of
  them are built in, with no Faker dependency. Use `$repeat` to generate lists. Set a seed
  and the data is the same on every run.
- **CRUD resources.** One line (`resources: [users]`) gives you `GET/POST/PUT/PATCH/DELETE`.
  It supports filters, full-text search, sorting, pagination, `X-Total-Count` and `Link`
  headers. Start empty, from seed data or from generated items.
- **OpenAPI 3.** Point it at a spec and every operation answers with its examples, or with
  data generated from the schema. Pick a status or a named example per request with a
  `Prefer` header.
- **Chaos on demand.** Add fixed or random latency and an error rate, globally or per
  route, to test spinners, retries and error states.
- **Made for the browser.** CORS is on by default, including credentials and preflight.
- **Hot reload.** Save the file and the next request uses it. If the new file is broken,
  the old definition keeps serving and the error shows up in the log and at
  `/__mockapi/health`.
- **Request log.** `GET /__mockapi/log` lists the recent requests with status, timing,
  matched route and body.
- **Small.** Starlette, uvicorn and PyYAML. A container image is available.

## Quick start

### Docker

```bash
docker run --rm -p 4010:4010 ghcr.io/saizul/mockapi-yaml
curl "http://127.0.0.1:4010/api/users?per_page=2"
```

The image ships with [`examples/mock.yaml`](examples/mock.yaml). To use your own file,
mount a folder with your `mock.yaml`. Edits are picked up while the container runs:

```bash
docker run --rm -p 4010:4010 -v "$PWD:/config:ro" ghcr.io/saizul/mockapi-yaml
```

### pip

```bash
pip install git+https://github.com/saizul/mockapi-yaml
mockapi init                      # writes a starter mock.yaml
mockapi serve                     # http://127.0.0.1:4010
```

### Try it

```bash
curl http://127.0.0.1:4010/me
curl -X POST http://127.0.0.1:4010/todos -H 'content-type: application/json' -d '{"title":"Ship it"}'
curl "http://127.0.0.1:4010/users?role=admin&sort=-created_at&page=1&per_page=5"
curl http://127.0.0.1:4010/__mockapi/routes      # everything the mock serves
```

Point your frontend at it, for example with a Vite proxy:

```js
// vite.config.js
export default { server: { proxy: { "/api": "http://127.0.0.1:4010" } } };
```

## Routes

```yaml
routes:
  - name: product detail             # optional, shown in logs and X-Mock-Source
    method: GET                      # GET (default), a list [POST, PUT] or "*"
    path: /products/{id}             # also /products/:id; {rest:path} matches slashes
    status: 200
    headers: { Cache-Control: no-store, X-Request-Id: "{{uuid}}" }
    body:
      id: "{{params.id | int}}"
      title: "{{faker.words(3)}}"
      price: "{{faker.price(5, 99)}}"

  - path: /logo.svg
    file: assets/logo.svg            # content type from the extension; JSON/YAML files are templated

  - method: DELETE
    path: /products/{id}
    status: 204                      # no body
```

Routes are checked in order and the first match wins. Put specific variants before
the general one:

```yaml
routes:
  - path: /search
    match:
      query: { q: "/^error/" }       # regex between slashes
    status: 500
    body: { error: Search backend down }

  - path: /search
    match:
      query: { page: "*" }           # "*" means the parameter is present
      headers: { Authorization: "Bearer test-token" }
    body: { page: "{{query.page | int}}", results: [] }

  - method: POST
    path: /orders
    match:
      body: { payment: { method: card } }   # subset match on the JSON body
    status: 402
    body: { error: Card declined }

  - path: /search                    # fallback
    body: { results: [] }
```

Match values can be a string or number (exact match), a list (any of them), `"*"`
(present) or `/regex/`. Header names are case-insensitive. A body match checks that the
request contains the given keys and values. For arrays, every listed item must be present.

When the body is a string, the response is `text/plain`. Anything else is JSON. Set a
`Content-Type` header to override this. Every response has an `X-Mock-Source` header
that tells you which route, resource or OpenAPI operation answered.

## Templates

A string that is exactly one `{{ }}` keeps the type of its value, so
`"{{query.limit | int}}"` is a number and `"{{body}}"` is the whole object. Templates
inside longer strings are joined as text.

| Expression | Value |
| --- | --- |
| `params.id` | path parameter |
| `query.page`, `queryAll.tag` | last value / all values of a query parameter |
| `headers.authorization` | request header (case-insensitive) |
| `body.user.email`, `body.items.0.sku` | field of the JSON (or form) request body |
| `request.method`, `request.path`, `request.url` | request info |
| `now`, `timestamp`, `uuid` | ISO time (UTC), Unix seconds, random UUID |
| `index` | position inside `$repeat` |

**Filters:** `int`, `float`, `bool`, `upper`, `lower`, `string`, `json`, `length`,
`default('fallback')`, which can be chained: `{{query.sort | default('name') | upper}}`.

**Faker helpers** (`{{faker.name}}`, `{{faker.int(1, 10)}}`):

| Group | Helpers |
| --- | --- |
| People | `name`, `first_name`, `last_name`, `username`, `email(domain?)`, `phone`, `company`, `job_title` |
| Places | `city`, `country`, `street_address`, `zip`, `latitude`, `longitude` |
| Text | `word`, `words(n)`, `sentence(words)`, `paragraph(sentences)`, `slug(words)`, `string(length)` |
| Numbers | `int(min, max)`, `float(min, max, digits)`, `price(min, max)`, `bool(chance)`, `pick('a', 'b', ...)` |
| IDs and web | `uuid`, `hex(length)`, `color`, `hex_color`, `ipv4`, `url`, `image_url(w, h)` |
| Dates | `date(days)`, `past_date(days)`, `future_date(days)`, `datetime(days)` |

Fake e-mails, URLs and IPs use reserved example domains and documentation IP ranges, so
mock data never points at real people or hosts.

**Lists:**

```yaml
body:
  results:
    $repeat: "{{query.limit | default(10)}}"   # a number, a range "3-8" or a template
    $item:
      id: "{{index}}"
      name: "{{faker.name}}"
```

## Resources (CRUD)

```yaml
resources:
  todos: {}                                   # empty collection at /todos
  users:
    seed: data/users.json                     # or an inline list of objects
  products:
    path: /shop/products                      # default: /<name>
    id_field: sku                             # default: id
    envelope: true                            # {data, meta} instead of a bare array
    per_page: 12
    generate:
      count: 100
      item: { sku: "SKU-{{index}}", title: "{{faker.words(2)}}", price: "{{faker.price}}" }
  countries:
    readonly: true                            # writes answer 405
    seed: [{ id: 1, name: Bangladesh }, { id: 2, name: Portugal }]
```

| Request | Result |
| --- | --- |
| `GET /users` | list (all items, or a page when you paginate) with `X-Total-Count` |
| `GET /users/7` | one item or `404` |
| `POST /users` | `201` with the item and `Location`; the id is the next integer, or a UUID if ids are strings |
| `PUT /users/7` | replace (the id is kept) |
| `PATCH /users/7` | shallow merge |
| `DELETE /users/7` | `204` |

List query parameters:

| Parameter | Example |
| --- | --- |
| Equality (any field, nested with dots, repeat for OR) | `?role=admin&role=editor`, `?team.name=core` |
| Operators | `?age_gte=18`, `?age_lt=65`, `?status_ne=archived`, `?name_like=ann` |
| Full-text search | `?q=lisbon` |
| Sorting (comma for several, `-` for descending) | `?sort=-created_at,name` or `?_sort=age&_order=desc` |
| Page pagination | `?page=2&per_page=20` or `?_page=2&_limit=20` |
| Offset pagination | `?offset=40&limit=20` or `?_start=40&_limit=20` |

Paginated responses include an RFC 8288 `Link` header (`first`, `prev`, `next`,
`last`). Data lives in memory: it survives hot reloads when the resource definition did
not change and resets on restart or with `POST /__mockapi/reset`.

## OpenAPI 3

```yaml
openapi: openapi.yaml       # or a list of files; JSON works too
routes: []                  # routes and resources still take precedence
```

You can also pass the spec directly: `mockapi -c openapi.yaml serve`.

For each operation the response is the first that applies:

1. the named example you asked for (`Prefer: example=refunded` or `?__example=refunded`);
2. the media type's `example`, then the first entry of `examples`;
3. a value generated from the schema, honouring `example`, `default`, `enum`, `format`,
   `$ref`, `allOf`, `oneOf`, `anyOf`, `minItems` and `minLength`.

The status is the lowest `2xx` unless you ask for another with `Prefer: code=404` or
`?__code=404`. Codes also match `4XX` style ranges and `default`. Examples can contain
templates (`"{{params.orderId}}"`). Literal paths such as `/pets/mine` win over
parameterised ones such as `/pets/{id}`.

## Latency and errors

```yaml
settings:
  latency: "50-300"            # every request: random delay in milliseconds
  error_rate: 0.05             # 5% of requests fail...
  error:                       # ...with this response (default: 500 {"error": "Injected failure ..."})
    status: 503
    headers: { Retry-After: "5" }
    body: { error: Service unavailable }

routes:
  - path: /reports/{id}
    latency: 2000              # override per route; 0 turns it off
    error_rate: 0.5
    error: { status: 504, body: { error: Gateway timeout } }
    body: { id: "{{params.id}}" }
```

Latency is `150` (fixed), `"100-400"` (random range) or `{min: 100, max: 400}`. A `404`
for an unknown path is never replaced by an injected error. Injected errors are marked in
`X-Mock-Source` and in the log.

## CORS, hot reload and the request log

- **CORS** is on by default. Any origin is reflected, credentials are allowed, and every
  method and header is accepted. `X-Total-Count`, `Link` and `Location` are exposed. Use
  `cors: ["http://localhost:5173"]` to restrict it or `cors: false` to turn it off.
- **Hot reload** checks the mock file, its OpenAPI files and body files at most once per
  `settings.reload_interval` seconds (default 1), on the next request. `--no-reload` turns
  it off and `POST /__mockapi/reload` forces a reload.
- **Admin endpoints** (never prefixed by `base_path`):

| Endpoint | Purpose |
| --- | --- |
| `GET /__mockapi/routes` | routes, resources (with item counts) and OpenAPI operations |
| `GET /__mockapi/log?limit=50` | recent requests: time, method, path, query, status, duration, source, body |
| `DELETE /__mockapi/log` | clear the log |
| `POST /__mockapi/reset` | reset every resource to its seed |
| `POST /__mockapi/reload` | reload the mock file now (`422` with the error if it is invalid) |
| `GET /__mockapi/health` | `{"status": "ok", "reload_error": null}`, used by the container health check |

Every request is also printed to the console:
`GET /api/users?page=2 -> 200 4.1ms [resource users]`.

## Configuration reference

### `settings`

| Key | Default | Description |
| --- | --- | --- |
| `base_path` | `""` | prefix for every route, resource and operation, e.g. `/api/v1` |
| `latency` | `0` | delay per request (see above) |
| `error_rate` | `0` | probability (0-1) that a request gets `error` instead |
| `error` | `500` JSON error | `{status, headers, body}` used for injected errors |
| `cors` | `true` | `true`, `false` or a list of allowed origins |
| `seed` | random | integer seed for faker helpers, generated resources, latency and errors |
| `headers` | `{}` | headers added to every mock response |
| `log_size` | `500` | number of requests kept for `/__mockapi/log` (`0` disables it) |
| `log_requests` | `true` | print one line per request |
| `reload_interval` | `1.0` | seconds between checks for changed files |

### `routes[]`

| Key | Default | Description |
| --- | --- | --- |
| `path` | required | `/users/{id}`, `/users/:id`, `/files/{rest:path}` |
| `method` / `methods` | `GET` | a method, a list or `*` |
| `name` | | label shown in logs and `X-Mock-Source` |
| `match` | | `{query, headers, body}` conditions |
| `status` | `200` | response status |
| `headers` | `{}` | response headers (templated) |
| `body` | empty | response body (templated) |
| `file` | | read the body from a file relative to the mock file |
| `latency`, `error_rate`, `error` | settings | per-route overrides |

### `resources.<name>`

| Key | Default | Description |
| --- | --- | --- |
| `path` | `/<name>` | collection path |
| `id_field` | `id` | identifier field |
| `seed` | `[]` | list of objects, or a path to a JSON/YAML file containing one |
| `generate` | | `{count, item}` where `item` is a template rendered `count` times |
| `envelope` | `false` | wrap lists as `{data, meta: {total, page, per_page, pages}}` |
| `per_page` / `max_per_page` | `20` / `1000` | page size default and cap |
| `readonly` | `false` | reject writes with `405` |

### `openapi`

A path or a list of paths to OpenAPI 3.x documents (YAML or JSON), relative to the mock file.

### Environment variables

| Variable | Default | Description |
| --- | --- | --- |
| `MOCKAPI_CONFIG` | `mock.yaml` (`/config/mock.yaml` in the image) | mock file |
| `MOCKAPI_HOST` | `127.0.0.1` (`0.0.0.0` in the image) | bind address |
| `MOCKAPI_PORT` | `4010` | port |
| `MOCKAPI_LOG_LEVEL` | `info` | `debug`, `info`, `warning`, `error` |

## CLI

```text
mockapi [-c FILE] serve [--host H] [--port P] [--no-reload] [--log-level L]
mockapi [-c FILE] check          # validate and list everything the file serves
mockapi init [PATH] [--force]    # write a starter mock.yaml
mockapi --version
```

`mockapi check` exits with status 2 and a message such as
`routes[3].status: status must be an HTTP status code (100-599)` when the file is
invalid. This makes it useful in CI.

## FAQ

**How is this different from json-server?** json-server serves CRUD from one JSON file.
mockapi-yaml does that too, using the same `_page`, `_limit`, `_sort` and `_like` query
parameters. It adds custom routes with request matching, templating, fake data, latency
and error injection, and OpenAPI examples. It is a single Python process or container.

**And from Prism or WireMock?** Prism is OpenAPI only. WireMock is powerful but uses Java
and verbose JSON mappings. mockapi-yaml aims for the 90% case that a frontend developer
needs, in a file you can read at a glance.

**Can I use it in tests?** Yes. Run the container in CI, or use it in-process from
Python: `TestClient(mockapi_yaml.app.create_app("mock.yaml"))`. Set `settings.seed` for
deterministic data.

**Is the data persisted?** No, everything is in memory. Put the state you need in `seed`.
It is restored on restart and with `POST /__mockapi/reset`.

**Why does `{{params.id}}` return a string?** Path and query values are strings. Use
`{{params.id | int}}` for a number.

**Can templates run code?** No. Templates can only read request data and call the
documented helpers and filters. There is no `eval`.

## Roadmap

Ideas, many of them marked **good first issue**:

- [ ] Response sequences (`responses: [...]` answered in turn or at random)
- [ ] Stateful routes that read from resources (`{{resources.users.0.name}}`)
- [ ] Per-request overrides through headers (`X-Mock-Delay`, `X-Mock-Status`)
- [ ] Request body validation against the OpenAPI schema
- [ ] Record mode: proxy to a real API and save responses as routes
- [ ] More faker helpers: `iban`, `credit_card_test`, `locale` aware names
- [ ] `mockapi export` to print the mock as an OpenAPI document
- [ ] Persist resources to a JSON file between restarts (opt-in)
- [ ] WebSocket and Server-Sent Events mocks

## Contributing

Contributions of every size are welcome. Small ones such as a new faker helper or a
clearer error message are a great first pull request. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the setup, the project layout and a list of good
first issues. Please follow the [Code of Conduct](CODE_OF_CONDUCT.md) and report security
issues privately as described in [SECURITY.md](SECURITY.md).

```bash
git clone https://github.com/saizul/mockapi-yaml && cd mockapi-yaml
python -m venv .venv && . .venv/bin/activate
pip install -e .[dev]
pytest && ruff check . && ruff format --check .
```

## License

[MIT](LICENSE) © Saizul Amin
