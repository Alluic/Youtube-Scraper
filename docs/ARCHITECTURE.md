# Architecture

## Data flow

```text
YouTube OAuth subscriptions
          |
          v
Channel uploads playlists -- watermark overlap --> SQLite videos
          |
          v
Gemma metadata classifier
     | include/ambiguous
     v
manual captions -> automatic captions -> temporary audio + Whisper
          |
          v
transcript-level classification for ambiguous videos
          |
          v
timestamp-aware chunk extraction -> Gemma final brief
          |
          v
cross-video synthesis -> HTML-safe outbox -> Telegram
```

## Processing invariants

- YouTube video ID is the durable deduplication key.
- A discovery watermark advances only after a successful feed scan.
- The two-hour overlap protects against clock skew and delayed publication
  indexing.
- A video is delivered only after every outbox message in its digest batch has
  a recorded Telegram message ID.
- Audio lives only inside a per-video temporary directory and is removed in a
  `finally` block.
- Credentials and runtime data never use repository-relative paths.

## Video states

| State | Meaning |
|---|---|
| `discovered` | Metadata is persisted but not classified |
| `classified` | Included or ambiguous; transcript is required |
| `transcript_ready` | Normalized timestamped transcript is available |
| `summarized` | Structured investor brief exists |
| `queued` | Digest messages are persisted in the outbox |
| `delivered` | Entire outbox batch was accepted by Telegram |
| `filtered_out` | High-confidence non-finance content |
| `failed` | Recoverable or terminal error; attempts are counted |

## Model memory sequencing

`gemma4:12b` is close to the capacity of an 8 GB GPU. The pipeline:

1. finishes metadata classifications;
2. obtains all available captions;
3. unloads Gemma once if any Whisper work is required;
4. transcribes all missing-caption videos with one Whisper model instance; and
5. reloads Gemma implicitly for transcript classification and summaries.

This avoids attempting to hold both models in VRAM simultaneously.

## Structured output

Ollama receives a JSON Schema for classification, partial chunk extraction,
video summary, and cross-video synthesis. Required keys are validated after
decoding. A malformed response is retried once with an explicit JSON repair
instruction and then recorded as a failure.

## Delivery semantics

The SQLite outbox provides restart-safe, ordered, at-least-once delivery.
Telegram has no request idempotency key, so an operating-system crash in the
small interval between remote acceptance and local commit may duplicate one
message. Every successful response's Telegram message ID is retained.
