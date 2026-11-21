# Contributing to mockapi-yaml

Thank you for helping! New template helpers, matchers, resource features, documentation
and bug reports are all welcome.

- [Ways to contribute](#ways-to-contribute)
- [Good first issues](#good-first-issues)
- [Development setup](#development-setup)
- [Project layout](#project-layout)
- [Add a faker helper](#add-a-faker-helper)
- [Guidelines](#guidelines)
- [Pull request process](#pull-request-process)

## Ways to contribute

| Size | Idea |
| --- | --- |
| 10 minutes | Fix a typo, add a FAQ entry, improve an example in `examples/` |
| 30 minutes | Add a faker helper or a template filter, improve an error message |
| 1-2 hours | One of the good first issues below |
| Larger | Record mode, response sequences, schema validation (open an issue first) |

Comment on an issue before you start so nobody else picks the same one.

## Good first issues

Each of these is self-contained and touches one or two files plus tests.

1. **`X-Mock-Delay` and `X-Mock-Status` request headers.** Let a client override latency
   (milliseconds) and the status of a single request, for example to test one slow call
   from browser dev tools. (`app.py`, `tests/test_behaviour.py`, README)
2. **New faker helpers.** `iban`, `credit_card_test` (only published test numbers),
   `time`, `currency_code`, `mime_type`, `file_name`. See "Add a faker helper" below.
   (`fake.py`, `tests/test_templating.py`, README table)
3. **`slice` and `join` filters.** `{{body.tags | join(', ')}}`,
   `{{body.items | slice(0, 3)}}`. (`templating.py`, tests)
4. **`mockapi check --strict`.** Fail when two routes are identical (same method, path
   and match), because the second one can never answer. (`cli.py`, `tests/test_cli.py`)
5. **Delay only the first byte vs the whole body.** Add `settings.latency_mode: total`
   that counts processing time towards the target latency. (`app.py`, tests)
6. **Nested resources.** `GET /users/{id}/posts` returns posts whose `userId` matches,
   configured with `resources.posts.parent: { resource: users, field: userId }`.
   (`config.py`, `resources.py`, `app.py`, tests)
7. **OpenAPI `servers` prefix.** Optionally mount operations under the path of
   `servers[0].url` (`openapi_use_servers: true`). (`openapi.py`, `app.py`, tests)
8. **Windows-friendly paths in `file:`.** Add tests with backslashes and make sure the
   error message shows the resolved path. (`config.py`, `tests/test_config.py`)

## Development setup

```bash
git clone https://github.com/saizul/mockapi-yaml
cd mockapi-yaml
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e .[dev]
pytest
ruff check . && ruff format --check .
```

Python 3.11+ is needed. Tests use Starlette's `TestClient`, run in-process and never
touch the network. The `harness` fixture in `tests/conftest.py` writes a mock file to a
temporary directory and gives you a fake clock (to test hot reload without sleeping) and
a fake `sleep` (to test latency instantly).

To try the server by hand:

```bash
mockapi -c examples/mock.yaml serve --log-level debug
curl "http://127.0.0.1:4010/api/users?per_page=3"
```

## Project layout

| Path | Responsibility |
| --- | --- |
| `src/mockapi_yaml/config.py` | YAML/JSON loading, validation, `Route`, `Resource`, `Settings`, path compilation |
| `src/mockapi_yaml/templating.py` | `{{ }}` parser, filters, `$repeat`, `validate_templates` |
| `src/mockapi_yaml/fake.py` | dependency-free fake data helpers (`Fake`) |
| `src/mockapi_yaml/resources.py` | in-memory CRUD collections: filter, sort, paginate |
| `src/mockapi_yaml/openapi.py` | OpenAPI 3 operations, example selection, schema sampler |
| `src/mockapi_yaml/app.py` | ASGI app: dispatch, latency/errors, CORS, hot reload, log, admin API |
| `src/mockapi_yaml/cli.py` | `serve`, `check`, `init` |
| `tests/` | pytest suite; `conftest.py` has the harness, clock and sleeper |

## Add a faker helper

1. Add a public method to `Fake` in `src/mockapi_yaml/fake.py`. Use `self.rng` for all
   randomness, so `settings.seed` keeps working. Give every argument a default, so
   `{{faker.your_helper}}` works without parentheses:

   ```python
   def currency_code(self) -> str:
       return self.rng.choice(("EUR", "USD", "BDT", "JPY", "GBP"))
   ```

2. Never generate data that could belong to a real person or system. Use reserved
   domains (`example.com`), documentation IP ranges and published test numbers only.
3. Add a test in `tests/test_templating.py`. `test_every_helper_runs_without_arguments`
   picks the helper up automatically.
4. Add it to the faker table in `README.md` and a line under "Unreleased" in
   `CHANGELOG.md`.

## Guidelines

- Keep runtime dependencies to Starlette, uvicorn and PyYAML; discuss new ones first.
- Templates must stay a small, safe language: no `eval`, no attribute access on Python
  objects, no file or network access.
- Every new config key is validated in `config.py`, has a default and a clear error
  message that names the key (`routes[2].latency: ...`).
- Type hints everywhere; `ruff check` and `ruff format` clean.
- Tests are fast and deterministic: no network, no real `sleep`.

## Pull request process

1. Fork and create a branch (`feat/response-sequences`, `fix/patch-nested`).
2. Keep pull requests focused; fill in the checklist in the template.
3. Add an entry to `CHANGELOG.md` under "Unreleased".
4. A maintainer reviews within a few days.

By contributing you agree that your work is released under the MIT License and
that you follow the [Code of Conduct](CODE_OF_CONDUCT.md).
