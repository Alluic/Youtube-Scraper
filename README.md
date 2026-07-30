# YouTube Investor Digest

A private, Windows-native research pipeline that:

1. reads new uploads from your YouTube subscriptions;
2. selects finance, macroeconomics, investing, markets, and trading videos;
3. obtains captions or transcribes audio locally;
4. analyzes the transcript with `gemma4:12b` through Ollama; and
5. sends a source-grounded investor digest to Telegram.

Runtime data and credentials remain on the PC. This public repository contains
only source code, safe configuration examples, documentation, and tests.

## System requirements

- Windows 11
- [Ollama](https://ollama.com/) with `gemma4:12b`
- NVIDIA GPU recommended; the configured fallback is an RTX 4060-class 8 GB GPU
- Existing YouTube Data API OAuth desktop-client JSON
- Existing Telegram bot token and destination chat ID
- PowerShell and Git

The project uses Python 3.12 through `uv`. It does not require a system-wide
FFmpeg installation: `yt-dlp` downloads the original audio container and
`faster-whisper` decodes it through PyAV.

## Install

From PowerShell:

```powershell
winget install --id astral-sh.uv -e
uv python install 3.12
uv sync --extra dev
ollama list
```

Confirm that `gemma4:12b` appears in `ollama list`.

## Configure credentials

Run:

```powershell
uv run youtube-digest configure
```

The command:

- copies the selected OAuth client JSON to
  `%LOCALAPPDATA%\YoutubeFinanceDigest\client_secret.json`;
- stores the Telegram bot token in Windows Credential Manager;
- writes non-secret settings to
  `%LOCALAPPDATA%\YoutubeFinanceDigest\config.toml`; and
- never writes credentials into the repository.

Authorize YouTube and validate every dependency:

```powershell
uv run youtube-digest auth
uv run youtube-digest doctor
```

The Google Cloud project must have YouTube Data API v3 enabled. The OAuth
client must be a desktop application and the authorizing account must have
access to the intended YouTube subscriptions.

## Safe first run

Generate the previous 24 hours without sending Telegram messages:

```powershell
uv run youtube-digest backfill --hours 24 --no-send
```

The command prints Telegram-formatted HTML to the terminal. After reviewing it:

```powershell
uv run youtube-digest run
```

An immediate rerun is safe. YouTube video IDs, processing states, and Telegram
outbox records are durable in SQLite.

## Daily scheduling

Install the 7:30 AM local-time Windows task:

```powershell
uv run youtube-digest schedule install
uv run youtube-digest schedule status
```

Remove it with:

```powershell
uv run youtube-digest schedule remove
```

The task starts missed runs when the user next signs in, retries failures three
times at 15-minute intervals, ignores overlapping starts, and has a six-hour
execution limit. It uses Windows local time, so daylight-saving changes are
automatic. Because credentials reside in the user's Windows profile, the task
uses an interactive-user principal.

## Commands

| Command | Behavior |
|---|---|
| `youtube-digest configure` | Copy OAuth credentials, save settings, and store the Telegram token |
| `youtube-digest auth` | Complete Google OAuth in the browser |
| `youtube-digest doctor` | Check Ollama/model, YouTube authentication, and Telegram |
| `youtube-digest run` | Resume from the durable watermark and deliver summaries |
| `youtube-digest run --since 2026-07-29T12:00:00Z` | Override the discovery window |
| `youtube-digest run --no-send` | Process and print without sending |
| `youtube-digest backfill --hours 24` | Process a fixed historical window |
| `youtube-digest schedule install\|status\|remove` | Manage Task Scheduler |

## Selection and output

Every new subscription video receives a local metadata classification:

- relevant with confidence at least `0.70`: include;
- irrelevant with confidence at least `0.85`: exclude;
- otherwise: retrieve the transcript and classify again.

Channel and keyword overrides are available in the private `config.toml`.
Transcript-level uncertainty is included conservatively to reduce false
negatives.

Each digest card separates:

- creator thesis and stated actions;
- core assets and directional views;
- the causal WHY chain;
- timestamped evidence;
- catalysts, time horizon, risks, counterarguments, and invalidation;
- model-derived investor implications; and
- confidence and transcript provenance.

Telegram messages are HTML-escaped and kept below 3,900 characters.

## Persistence and privacy

The runtime directory is `%LOCALAPPDATA%\YoutubeFinanceDigest`:

```text
config.toml             Non-secret settings
client_secret.json      Google desktop OAuth client
oauth_token.json        Refresh/access token
digest.db               SQLite state, runs, summaries, outbox
logs/                   Rotating operational logs
transcripts/            Normalized transcripts, retained for 30 days
tmp/                    Temporary downloads
```

Temporary audio is deleted after every transcription attempt. Metadata,
summaries, classifications, and delivery history are retained. Transcript files
older than 30 days are removed.

Do not copy the runtime directory into the repository. Before every release,
inspect staged files and scan for API keys, bot tokens, OAuth tokens, media, and
databases.

## Failure and recovery behavior

- A filesystem lock prevents simultaneous runs.
- Discovery uses a two-hour overlap and video-ID deduplication.
- Processing failures are retried up to three times.
- Telegram messages are written to an outbox before transmission.
- A restart resumes unsent outbox rows before creating a new digest.
- A crash after Telegram accepts a message but before the returned message ID
  is committed can cause one duplicate; the Telegram Bot API provides no
  idempotency key.
- Permanent inaccessible-video failures are retained in SQLite and summarized
  in a Telegram failure alert.

## Troubleshooting

### Ollama is unavailable

Run `ollama list`, then `ollama serve`. The application will try to start
Ollama hidden, but it cannot install Ollama or the model.

### GPU memory errors

Gemma is explicitly unloaded before Whisper starts. If CUDA Whisper still
cannot initialize, transcription falls back to CPU `int8`, which is slower.

### Captions or audio fail

Update `yt-dlp`:

```powershell
uv lock --upgrade-package yt-dlp
uv sync
```

Age-restricted, members-only, private, deleted, or bot-protected videos may
remain inaccessible and will be reported.

### Google authentication fails

Delete only `%LOCALAPPDATA%\YoutubeFinanceDigest\oauth_token.json`, then run
`youtube-digest auth` again. Do not delete the SQLite database.

### Telegram fails

Run `youtube-digest doctor`. Confirm the bot belongs to the destination chat
and that the chat ID includes its leading minus sign for groups.

## Development

```powershell
uv sync --extra dev
uv run ruff check .
uv run pytest
```

The automated tests use fakes and temporary databases. They do not contact
YouTube, Ollama, Telegram, or load Whisper.

## Financial-use boundary

This software generates research summaries. Creator claims and model-derived
implications can be wrong, incomplete, stale, or misleading. Output is not
personalized financial advice and the application never places trades.
