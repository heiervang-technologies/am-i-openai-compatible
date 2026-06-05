# Security Policy

## Reporting a vulnerability

Please report security issues privately rather than opening a public
GitHub issue. Use one of:

- **GitHub Private Vulnerability Reporting**:
  [open a private advisory](https://github.com/heiervang-technologies/am-i-openai-compatible/security/advisories/new)
  for this repo. This is the preferred path.
- **Email**: the maintainer (see commit history for the address).

You should receive an acknowledgement within **7 days**. If you don't,
follow up — the report may not have arrived.

A PGP key is not required. If you want to encrypt the report anyway,
mention it in the first message and we'll exchange a key out of band.

## Scope

`aioc` is an HTTP client probe — it sends short, well-formed requests
to a target server and grades the responses. The package itself runs
in the user's environment with the user's credentials. The main
security-relevant surfaces are:

- **HTTP credential handling.** `--openai-api-key` and the equivalent
  environment variable are read at probe time and sent in the
  `Authorization` header on requests / WebSocket upgrades to the
  configured target. They are not logged, not written to the report
  JSON, and not echoed in error messages. A leak of these values
  through any code path would be in scope.
- **URL handling.** The probe accepts a user-supplied base URL and
  templates known paths onto it. The probe does NOT fetch URLs
  derived from server responses (it only fetches the paths it's
  shipped with). Any server-controlled URL fetching would be in scope.
- **Multipart and JSON body assembly.** Bodies are built from the
  catalog templates with `{model}` substitution. Injection of
  attacker-controlled content into bodies sent to a third-party
  server would be in scope.

Out of scope:

- The behavior of the target server you're probing — that's a bug
  report against the target, not against `aioc`.
- The HT-compat spec text in `docs/spec/ht-compat.md` — that's a
  spec design issue, not a security one. Open a regular GitHub issue.

## Supported versions

We patch security issues on the latest minor release. Older minors
are not actively patched; upgrade to the latest minor first.

## Disclosure

After a fix lands, we'll publish a GHSA advisory describing the
issue, affected versions, and the fix. Credit will go to the reporter
unless they request otherwise.
