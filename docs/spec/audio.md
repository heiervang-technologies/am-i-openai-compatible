# Audio

OpenAI's audio surface has three endpoints. Two are core; one is an
extension that's commonly folded into another.

## `/v1/audio/speech` (TTS)

Server takes text, returns audio bytes.

**Request:**

```json
{
  "model": "<id>",
  "input": "Hello world",
  "voice": "alloy",
  "response_format": "mp3"
}
```

**Response:** raw audio bytes. The prober checks:

* `Content-Type` starts with `audio/` (`mp3`, `mpeg`, `wav`, `opus`,
  `ogg`, `flac` all accepted). `application/octet-stream` is a `WARN`
  — clients usually cope but it's wrong.
* Body length is non-zero.

### Common deviations

* **`response_format` ignored.** Server always returns MP3 regardless
  of the requested codec. WARN.
* **Voice id required vs. optional.** Spec marks `voice` as required;
  some servers default to a "voice 0" if omitted. Defaulting is fine;
  rejecting with 400 is also fine; silently returning empty audio is
  not.
* **Streaming.** OpenAI streams audio as the model generates it. Most
  OSS shims wait for completion and then send the whole file. Catalog
  treats this as a SKIP for now (no separate stream row); we may add
  one when streaming TTS becomes common.

## `/v1/audio/voices` *(extension — OSS convention)*

OpenAI ships a fixed voice enum (`alloy`, `echo`, `fable`, `onyx`,
`nova`, `shimmer`) and doesn't expose enumeration. Most OSS TTS
servers ship arbitrary voice files (reference-audio-clone TTS,
Kokoro, VibeVoice, etc.) and need a way for clients to discover
what's available. `/v1/audio/voices` is the de-facto convention.

**Request:** `GET /v1/audio/voices` (no body, no auth-specific params).

**Response:**

```json
{
  "voices": [
    {"id": "alloy", "name": "Alloy", "language": "en", "sample_rate": 24000},
    {"id": "stevejobs-clone-1", "name": "Steve Jobs (clone)", "language": "en"}
  ]
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `voices[].id` | string | yes | the string to pass as `audio.voice` on `/v1/audio/speech` or in `[omni]` chat |
| `voices[].name` | string | no | human-readable display name |
| `voices[].language` | string | no | BCP-47 tag (e.g. `"en"`, `"en-US"`) |
| `voices[].sample_rate` | integer | no | native sample rate of the voice model |
| `voices[].gender` | string | no | implementation-defined enum |

A bare-list shape (`{"voices": ["alloy", "stevejobs-clone-1"]}`) is
also seen on minimal servers; clients SHOULD handle either form.
The catalog Phase B check requires only that the `voices` key
exists and is non-empty.

### Common deviations

* **Servers without TTS return 404.** The catalog grades this as
  WARN under the `ext` kind (capability-gated, not non-compliance).
* **Per-voice metadata varies wildly.** ElevenLabs returns
  `{voice_id, name, samples, category, ...}` (no `id` field — uses
  `voice_id`); most OSS shims pick a flat `{id, name, ...}`.
  HT-compat picks `id` to match `/v1/models[i].id`.

## `/v1/audio/transcriptions` (STT)

Multipart upload of an audio file, returns transcribed text.

**Request fields (multipart):**

* `file` — the audio bytes.
* `model` — server model id.
* Optional: `language`, `prompt`, `temperature`,
  `response_format` (`json` / `text` / `verbose_json` / `srt` / `vtt`).

**Response (default `json`):**

```json
{ "text": "Hello world" }
```

**Response (`verbose_json`):**

```json
{
  "text": "Hello world",
  "language": "en",
  "duration": 2.4,
  "segments": [...]
}
```

The prober probes the default `json` format with one second of silent
WAV — enough to exercise the upload path without burning model
inference budget on a real signal.

### Common deviations

* **`text` field but body wrapped** (`{"transcription": {"text": "..."}}`).
  Hard `FAIL`.
* **No `language` even on `verbose_json`.** WARN — some Whisper
  variants return `verbose_json` shape but skip language detection
  when given silent audio. The prober treats it leniently.
* **422 on a 1-second probe.** A few servers reject sub-N-second
  uploads as "too short to transcribe". Catalog accepts a `422` here
  as a documented deviation (PASS-with-warning) since the route
  clearly exists.

## `/v1/audio/translations` (STT to English)

`ext`. OpenAI keeps it; many OSS servers fold its functionality into
`/v1/audio/transcriptions` with a `task: translate` parameter. A `404`
here is `SKIP`, not `FAIL`.
