# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-11-19

### Added

- Routes in YAML: method (or a list, or `*`), `{param}`, `:param` and `{rest:path}` path
  parameters, status, headers, JSON or text body, or a body from a file.
- Request matching on query parameters, headers and a subset of the JSON body, with
  exact values, alternatives (lists), `"*"` (present) and `/regex/`. The first matching
  route wins.
- `{{ }}` templates with `params`, `query`, `queryAll`, `headers`, `body` and `request`,
  filters (`int`, `float`, `bool`, `upper`, `lower`, `string`, `json`, `length`,
  `default`), `now`, `timestamp`, `uuid` and 36 dependency-free `faker.*` helpers;
  `$repeat` / `$item` for generated lists; `settings.seed` for reproducible data.
- In-memory CRUD resources (`GET`, `POST`, `PUT`, `PATCH`, `DELETE`) with filters
  (`field=`, `_gte`, `_lte`, `_gt`, `_lt`, `_ne`, `_like`, nested `a.b`), full-text `q`,
  multi-field sorting, page and offset pagination, `X-Total-Count`, `Link` headers, an
  optional envelope, read-only resources, seed data inline or from a file, and generated
  items.
- OpenAPI 3.0/3.1 mode: every operation answers with its examples or a value generated
  from the schema (`$ref`, `allOf`, `oneOf`, `anyOf`, enums, formats); pick a status or a
  named example with `Prefer: code=404, example=name` or `?__code=` / `?__example=`.
- Latency (fixed or random range) and error injection (`error_rate`, custom error
  response), globally or per route.
- CORS enabled by default (any origin with credentials, or an origin list).
- Hot reload of the mock file, its OpenAPI documents and body files; a broken edit keeps
  the previous definition and reports the error.
- Admin endpoints under `/__mockapi`: `routes`, `log`, `health`, `reset`, `reload`.
- CLI: `mockapi serve`, `mockapi check`, `mockapi init`.
- Container image on `ghcr.io/saizul/mockapi-yaml` (non-root, health check, example mock
  built in).

[Unreleased]: https://github.com/saizul/mockapi-yaml/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/saizul/mockapi-yaml/releases/tag/v0.1.0
