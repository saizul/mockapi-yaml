# Security Policy

## Supported versions

| Version | Supported |
| --- | --- |
| 0.1.x | yes |

## Scope

mockapi-yaml is a development tool. It is meant to run on a developer machine, in CI or
in a private preview environment, not as a public production service. It has no
authentication and CORS is open by default.

Things we treat as vulnerabilities:

- Reading files outside the directory of the mock file through a request (path traversal)
- Executing code or shell commands through a mock file, a template or a request
- Crashing the server or exhausting memory with a single crafted request
- A template expression reaching Python objects other than the documented helpers

Things that are expected behaviour and not vulnerabilities: anyone who can reach the port
can read and change in-memory resources and read the request log; a mock file can reference
any file the process can read (a mock file is trusted, like code).

## Reporting

Please **do not** open a public issue. Use
[GitHub private vulnerability reporting](https://github.com/saizul/mockapi-yaml/security/advisories/new)
with the version, the impact and steps to reproduce.

You will get an answer within 5 working days. Fixes are released as soon as
possible and credited in the changelog unless you prefer otherwise.

## Recommendations

- Bind to `127.0.0.1` (the default for `mockapi serve`) unless you need the network.
- The request log keeps the first 2000 characters of every request body in memory; do not
  send real credentials to a mock. Set `settings.log_size: 0` to turn the log off.
- Restrict `settings.cors` to your dev origin if the mock is reachable by other people.
