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
* `kind` — `core`, `optional`, `ext`, or `ours`. See
  [Spec — Overview](spec/index.md).
* `body` — the minimal valid request body for Phase B, or `None` for
  GET endpoints.
* `expects` — the shape validator: a tuple of dotted keys that must
  be present in the JSON response, or one of the sentinel strings
  (`"audio"`, `"image"`, `"sse"`).
* `response_model` — the name of a model in `schemas.py` when a full
  Pydantic validator exists for the response.
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

### Release checklist

The version drift surfaced by the v0.3.1 tag (the bump was missed
on `pyproject.toml`, so installs reported the old number) is the
reason this checklist exists. Follow it for every tag.

1. `git checkout main && git pull origin main` — start from a clean
   tip.
2. Decide the version bump. Pre-1.0 the convention is: additive
   features → minor (`0.x.0`); bug fixes only → patch (`0.x.y`).
   The HT-compat-1.0 → 1.1 spec bump in PR #13 was the kind of
   "this changes how clients write code" change that warrants a
   minor.
3. Bump `pyproject.toml`'s `version = "..."` line. (Since
   `__init__.py` reads `__version__` from `importlib.metadata`,
   you only have to update this one file.)
4. In `CHANGELOG.md`, move the `[Unreleased]` content to a new
   `[X.Y.Z] — YYYY-MM-DD` section. Leave `[Unreleased]` in place
   as an empty header for the next round.
5. Commit: `git commit -am "release: vX.Y.Z"`.
6. Tag: `git tag vX.Y.Z`.
7. Push both at once: `git push origin main vX.Y.Z`.
8. Verify `aioc --version` reports the new number from a fresh
   install: `pip install git+https://github.com/heiervang-technologies/am-i-openai-compatible.git@vX.Y.Z`
   (in a throwaway venv).
9. Bump the `@vX.Y.Z` install-pin examples to the new tag in
   `README.md`, `docs/getting-started.md`, and `action.yml`'s
   `aioc-version` input description. The pin examples are
   user-facing docs; leaving them at the previous tag means new
   users miss the bug fixes in the just-cut release. (For patch
   releases, this is optional but recommended; for minor releases,
   do it.)

The `tests/test_metadata.py` invariants will catch the most common
drift — `__version__` disagreeing with `pyproject.toml` or with
`importlib.metadata` — but they can't catch a release that was
tagged without the bump. That's what step 8 is for.
