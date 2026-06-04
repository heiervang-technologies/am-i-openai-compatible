# Images & videos

Images are part of the canonical surface. Videos are an `ours`
extension that mirrors OpenAI's Sora job model.

## `/v1/images/generations`

```json
{ "model": "<id>", "prompt": "a small cat", "size": "512x512", "n": 1 }
```

**Response:**

```json
{
  "created": 1730000000,
  "data": [
    {"url": "https://..."} | {"b64_json": "..."}
  ]
}
```

Exactly one of `url` or `b64_json` per item — both being absent or both
being present is a `WARN`.

### Common deviations

* **Returning `image_url` instead of `url`.** Hard `FAIL`. Surprisingly
  common in roll-your-own ComfyUI shims.
* **`b64_json` carrying a data URI** (`data:image/png;base64,...`)
  instead of bare base64. Spec says bare base64. WARN.
* **`n > 1` quietly clamped.** Spec allows up to 10; most OSS servers
  cap at 1. The prober tests `n=1` so this isn't visible from a
  default run.

## `/v1/images/edits`

Multipart in canonical OpenAI:

| Field    | Required | Notes                                  |
|----------|----------|----------------------------------------|
| `image`  | yes      | The source image bytes                 |
| `mask`   | no       | RGBA mask; transparent = editable      |
| `prompt` | yes      | Text instruction                       |
| `model`  | no       | Required by some OSS impls             |
| `n`      | no       | Default 1                              |
| `size`   | no       | E.g. `1024x1024`                       |

**Common deviation:** servers that take JSON instead of multipart and
expect `image` as base64. The catalog flags this as a documented
deviation (`WARN`) because some local image-edit pipelines (notably
the comfy-openai shim) only ever wanted JSON. Real OpenAI clients
break against JSON-only servers, so it stays a WARN, not a PASS.

## `/v1/images/variations`

`ext`. Less commonly implemented. Same multipart shape as `edits` but
without `prompt`. A `404` is `SKIP`.

## `/v1/videos` *(ours extension)*

Async job model. Probably the most divergent surface in the catalog
because OpenAI's Sora API is still narrow and most local implementers
have invented their own job shape.

This catalog uses the shape that matches OpenAI's Sora response and
that ComfyUI-workflow-shim implementations have converged on:

**Create:**

```json
{ "model": "wan22-i2v", "image": "<base64>", "prompt": "..." }
```

**Response:**

```json
{
  "id": "<job-id>",
  "model": "wan22-i2v",
  "status": "queued|in_progress|completed|failed",
  "created": 1730000000,
  "started": null,
  "finished": null,
  "error": null
}
```

**Poll:** `GET /v1/videos/{id}` returns the same shape, with `status`
advancing.

**Fetch result:** `GET /v1/videos/{id}/content` returns video bytes
when `status == "completed"`.

The probe tests creation only. It deliberately submits a *bad* image
(`"not a real image"`) so the job fails fast — we want to confirm:

1. The route exists.
2. The error response uses the documented OpenAI error envelope or at
   least surfaces a useful message in `error`. A terminal status of
   `error: "400: upstream error"` is a `WARN` (the validation message
   was eaten by the proxy); a specific message like `error: "400:
   Invalid image input: not a base64 string..."` is a `PASS`.

### Common deviations

* **Sync return.** Some shims block until the video is generated and
  return bytes directly with `Content-Type: video/mp4`. Catalog
  declares this a `FAIL` against the OpenAI Sora model — clients that
  do `POST` then `GET id` will hang.
* **Different status vocabulary** (`pending` instead of `queued`,
  `done` instead of `completed`). WARN.
* **`error` returned as a structured object** instead of a string.
  Spec is loose here; both are accepted.
