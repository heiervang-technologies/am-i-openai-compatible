# Contributing

Three kinds of contribution land regularly.

## 1. Fix a wrong cell in the matrix

Run `aioc probe` against the relevant server, attach the JSON report
to your PR, and update the column in
[`docs/compatibility-matrix.md`](compatibility-matrix.md). Be sure
to note the server version in the PR.

## 2. Add a new endpoint to the catalog

Edit
[`src/am_i_openai_compatible/endpoints.py`](https://github.com/heiervang-technologies/am-i-openai-compatible/blob/main/src/am_i_openai_compatible/endpoints.py).
Each entry is a frozen dataclass with:

* `path` — the URL path. Use `{model}` if it should be sniffed from
  `/v1/models`.
* `method` — `GET` / `POST` / `DELETE`.
* `group` — a grouping for reporting. Reuse an existing one if you
  can; new groups should appear in the docs.
* `kind` — `core`, `ext`, or `ours`. See
  [Spec — Overview](spec/index.md).
* `body` — the minimal valid request body for Phase B, or `None` for
  GET endpoints.
* `expects` — the shape validator: a tuple of dotted keys that must
  be present in the JSON response, or one of the sentinel strings
  (`"audio"`, `"image"`, `"sse"`).
* `notes` — one-liner that ends up in the docs.

Then update the appropriate spec page under `docs/spec/`.

## 3. Document a deviation

If you find an OSS server doing something the catalog doesn't
mention, add it to the relevant
[implementations](implementations/index.md) page or
[`docs/spec/extensions.md`](spec/extensions.md). Be specific about:

* the server and version,
* the request that triggers it,
* what the spec says (or doesn't),
* what the server actually does.

## Coding standards

* Python 3.10+. Type hints encouraged but not religious.
* `ruff` for lint; CI runs `ruff check` and `ruff format --check`.
* Tests under `tests/`. The prober itself is tested with `respx` —
  no live network calls in CI.

## Building docs locally

```bash
pip install -e ".[docs]"
mkdocs serve
```

The site lives under `docs/`. The build command CI runs is `mkdocs
build --strict` — broken links fail the build.

## Releasing

Versioning follows semver. Tag `v0.x.y` on `main`; the `docs`
workflow pushes a fresh build to GitHub Pages. There is no PyPI
release right now — consumers install via
`pip install git+https://github.com/heiervang-technologies/am-i-openai-compatible.git@v0.x.y`,
and the GitHub Action's `aioc-version` input resolves the same way.
