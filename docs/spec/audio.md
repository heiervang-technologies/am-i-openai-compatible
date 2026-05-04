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
