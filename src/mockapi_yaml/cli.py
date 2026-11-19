"""Command line interface: ``mockapi serve | check | init``."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from mockapi_yaml._version import __version__
from mockapi_yaml.config import ConfigError

DEFAULT_CONFIG = "mock.yaml"

STARTER = """\
# mockapi-yaml definition. Docs: https://github.com/saizul/mockapi-yaml
settings:
  latency: 0            # e.g. 150 or "100-400" (milliseconds)
  error_rate: 0         # e.g. 0.05 answers 5% of requests with settings.error
  cors: true

resources:
  users:
    generate:
      count: 25
      item:
        name: "{{faker.name}}"
        email: "{{faker.email}}"
        role: "{{faker.pick('admin', 'editor', 'viewer')}}"
        created_at: "{{faker.past_date}}"
  todos:
    seed:
      - { id: 1, title: "Try mockapi-yaml", done: true }
      - { id: 2, title: "Point the frontend at it", done: false }

routes:
  - method: GET
    path: /me
    body:
      id: 1
      name: "{{faker.name}}"
      token_expires: "{{now}}"

  - method: POST
    path: /login
    match:
      body: { password: "wrong" }
    status: 401
    body: { error: "invalid credentials" }

  - method: POST
    path: /login
    body: { token: "{{faker.hex(32)}}", user: "{{body.email}}" }
"""


def _config_path(args: argparse.Namespace) -> str:
    return args.config or os.environ.get("MOCKAPI_CONFIG") or DEFAULT_CONFIG


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from mockapi_yaml.app import create_app

    app = create_app(_config_path(args), reload=not args.no_reload)
    base = app.config.settings.base_path
    print(f"mockapi-yaml {__version__} serving {app.config_path} on http://{args.host}:{args.port}{base}")
    print(
        f"routes: http://{args.host}:{args.port}/__mockapi/routes   log: http://{args.host}:{args.port}/__mockapi/log"
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level, access_log=False, server_header=False)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    from mockapi_yaml.app import create_app

    app = create_app(_config_path(args), reload=False)
    info = app.describe()
    for route in info["routes"]:
        print(f"route     {','.join(route['methods']):<7} {route['path']}  -> {route['status']}")
    for res in info["resources"]:
        print(f"resource  {res['path']}  ({res['count']} items{', read-only' if res['readonly'] else ''})")
    for op in info["openapi"]:
        print(f"openapi   {op['method']:<7} {op['path']}  [{', '.join(op['responses'])}]")
    print("config OK")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    path = Path(args.path)
    if path.exists() and not args.force:
        print(f"{path} already exists (use --force to overwrite)", file=sys.stderr)
        return 1
    path.write_text(STARTER, "utf-8")
    print(f"wrote {path}; start it with: mockapi -c {path} serve")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mockapi", description="Zero-code mock REST API server from YAML or OpenAPI.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-c", "--config", help=f"mock file (default: $MOCKAPI_CONFIG or {DEFAULT_CONFIG})")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the mock server")
    serve.add_argument("--host", default=os.environ.get("MOCKAPI_HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.environ.get("MOCKAPI_PORT", "4010")))
    serve.add_argument("--no-reload", action="store_true", help="do not watch the mock file for changes")
    serve.add_argument(
        "--log-level",
        default=os.environ.get("MOCKAPI_LOG_LEVEL", "info"),
        choices=["debug", "info", "warning", "error"],
    )
    serve.set_defaults(func=cmd_serve)

    check = sub.add_parser("check", help="validate the mock file and list what it serves")
    check.set_defaults(func=cmd_check)

    init = sub.add_parser("init", help="write a starter mock.yaml")
    init.add_argument("path", nargs="?", default=DEFAULT_CONFIG)
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    level = getattr(args, "log_level", "info").upper()
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")
    try:
        return int(args.func(args))
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
