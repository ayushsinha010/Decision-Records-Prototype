<p align="center"><img src="docs/logo.png" alt="Logo" width="320"></p>

# Decision Records - transcript watcher prototype

A small, local prototype that turns meeting transcripts into structured decision records. You drop a transcript (`.txt`, `.vtt` or `.docx`) into a folder; a Python script notices it, sends the text to Claude with a fixed extraction prompt, and writes one Markdown file per meeting containing the decision (question considered, assumptions, evidence, decision made, resulting action, owner, status) and its context (client, stakeholders, requirements, products, open questions). The Markdown files land in a second folder that you can feed into [LibreChat](https://www.librechat.ai/) file search (or any other tool that reads Markdown). It is aimed at developers who want to try the "decisions as structured data instead of meeting-notes prose" idea quickly, and to judge extraction quality before building anything bigger.

This is a first prototype: one script, one machine, run in a terminal.

## Features

- Watches `transcripts_in/` for new files (files already present at start-up are processed first).
- Supports `.txt`, `.vtt` (WebVTT header, timing cues and cue numbers are stripped before sending) and `.docx` (paragraph text).
- Waits for a file's size to stop changing before reading it, so a file that is still being copied or synced is not read half-written.
- Also reacts to rename-into-place (`on_moved`), which some sync tools use.
- Sends the transcript to Claude with a system prompt that asks for one JSON object with 14 fields (listed below) and tells the model not to invent anything.
- Accepts the model's JSON with or without markdown code fences.
- Renders each result as `librechat_file_search/<transcript name>.md`.
- Remembers processed file names in `.processed.json`, so a restart does not reprocess everything. A file whose processing fails (invalid JSON, API error) is not marked processed and is retried on the next start-up.

## Tech stack

- Python (see Prerequisites)
- [`anthropic`](https://pypi.org/project/anthropic/) SDK (`>=1.0.0`; 1.15.0 was installed when this was tested)
- [`watchdog`](https://pypi.org/project/watchdog/) for folder events (`>=4.0.0`; 6.0.0 tested)
- [`python-docx`](https://pypi.org/project/python-docx/) for `.docx` transcripts (`>=1.1.0`; 1.2.0 tested)
- Default model ID: `claude-sonnet-5` (changeable, see Configuration)

## Project structure

```
Decision-Records-Prototype/
|-- watcher.py                    # the whole tool: watch, read, extract, render
|-- requirements.txt
|-- .env.example                  # documents the environment variables
|-- .gitignore
|-- docs/logo.png
|-- samples/sample_meeting.txt    # tiny synthetic transcript (invented people and numbers)
|-- tests/test_watcher_offline.py # offline tests with a stub client (no API key needed)
|-- transcripts_in/               # put transcripts here (empty, .gitkeep only)
`-- librechat_file_search/        # generated Markdown records (empty, .gitkeep only)
```

## Prerequisites

- Python 3.10 or newer (the `anthropic` 1.x SDK requires it). Tested on Python 3.14.7 on Windows 11.
- An Anthropic API key, only needed to process real transcripts (the tests do not need one).
- Network access to the Anthropic API.
- Optional: a LibreChat instance if you want to search the generated records. This project does not talk to LibreChat itself.

## Setup and run

Windows PowerShell:

```powershell
git clone <your-repo-url> Decision-Records-Prototype
cd Decision-Records-Prototype
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

$env:ANTHROPIC_API_KEY = "your-api-key-here"
python watcher.py
```

macOS / Linux:

```bash
git clone <your-repo-url> Decision-Records-Prototype
cd Decision-Records-Prototype
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export ANTHROPIC_API_KEY="your-api-key-here"
python watcher.py
```

On start the script creates `transcripts_in/` and `librechat_file_search/` if they are missing, processes anything already in `transcripts_in/`, and then logs a line like `Watching <path>\transcripts_in for new transcripts... (Ctrl+C to stop)`. There is no web server and no port.

Try it with the synthetic sample (in a second terminal, from the project root):

```powershell
# PowerShell
Copy-Item samples\sample_meeting.txt transcripts_in\
```

```bash
# macOS / Linux
cp samples/sample_meeting.txt transcripts_in/
```

A few seconds later `librechat_file_search/sample_meeting.md` appears, and `.processed.json` lists `sample_meeting.txt`. Press `Ctrl+C` to stop the watcher.

Note: the commands above were verified on Windows. The macOS/Linux commands follow the same steps but were not run (not verified). Processing a transcript with the live Claude API was also not verified here, see "Notes and limitations".

## Configuration

| Name | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | none (required to process transcripts) | API credentials, read by the `anthropic` SDK. The script does not load `.env` files itself; export the variable in your shell. |
| `DECISION_RECORDS_MODEL` | `claude-sonnet-5` | Claude model ID used for extraction. |

Constants at the top of `watcher.py` (edit the file to change them): `TRANSCRIPTS_FOLDER` (`transcripts_in/`), `OUTPUT_FOLDER` (`librechat_file_search/`), `PROCESSED_LOG` (`.processed.json`), `SUPPORTED_EXTENSIONS` (`.txt`, `.vtt`, `.docx`), `STABLE_CHECK_SECONDS` (2). The category list (`Financial Review`, `Account Planning`, `GTM`, `MIS & Business Ops`, `Other`) lives inside `SYSTEM_PROMPT`; change it there to suit your own meetings.

`.env.example` only documents the two variables above.

## What the record contains

The model is asked for exactly these keys, and each is rendered into the Markdown file:

| Group | Fields |
|---|---|
| Decision | `date_or_meeting`, `category`, `question_considered`, `assumptions`, `evidence_reviewed`, `decision_made`, `resulting_action`, `owner`, `status` (`Open`, `In Progress`, `Done` or `Superseded`) |
| Context | `account_client`, `stakeholders_mentioned`, `requirements_mentioned`, `products_discussed`, `open_questions` |

Empty values are shown as `-` in the multi-line fields. The field names mirror a typical decision-log column list, so moving the output into a spreadsheet or a SharePoint list later is a rename, not a redesign.

## Data and storage

- Input: `transcripts_in/` (you provide the files; contents are git-ignored except `.gitkeep`).
- Output: `librechat_file_search/*.md` (generated; git-ignored except `.gitkeep`). If two transcripts share a file stem (for example `a.txt` and `a.vtt`) the second overwrites the first.
- State: `.processed.json` in the project root, a sorted JSON list of processed file names.
- To reprocess everything, delete `.processed.json` (and, if you like, the generated `.md` files) and restart the watcher. To reprocess one file, remove its name from `.processed.json`.
- There is no database and no demo data besides `samples/sample_meeting.txt`, which is invented (fictional people, client and numbers).

## Tests / quality checks

```powershell
python -m py_compile watcher.py tests\test_watcher_offline.py
python -m unittest discover -s tests -v
```

On macOS / Linux use `/` instead of `\`.

The 15 tests in `tests/test_watcher_offline.py` use a stub client that returns canned JSON, so they need no API key and no network. They cover: reading `.txt`, `.vtt` and `.docx` transcripts; unwrapping fenced JSON; failing on a non-JSON reply; rendering the Markdown (including empty fields); an end-to-end run of the sample transcript through `process_file` (output file written, `.processed.json` updated, no second API call for the same file); skipping unsupported and empty files; not marking a file processed when the reply is not valid JSON; and the stability check.

Last run (Windows, Python 3.14.7, fresh virtual environment): `py_compile` clean, 15 of 15 tests passed. In a separate scratch run, `main()` was also started with a stub client: the file already in `transcripts_in/` was processed at start-up and a `.vtt` file dropped in while the watcher was running was picked up by the folder watcher and written out.

## Notes and limitations

- **Live model calls are not verified.** No API key was used while preparing this repository, so the real Claude request, the quality of the extraction and whether the model always returns clean JSON were not tested. The model ID `claude-sonnet-5` is the default carried over from the original prototype; override it with `DECISION_RECORDS_MODEL` if it is not available to your account. Read a few generated records yourself before relying on them.
- Without a key the watcher still starts and watches normally; each file then fails with an authentication error in the log and is not marked processed.
- **Nothing is uploaded to LibreChat automatically.** `librechat_file_search/` is just a folder of `.md` files. Adding them to LibreChat file search is a manual step through its UI or API. This integration is not implemented and was not tested.
- Not connected to SharePoint or any other repository: output is local Markdown only.
- Not a service: closing the terminal stops it, and there is no auto-restart.
- A file failing to process (API error, invalid JSON) is retried only the next time the script starts, not automatically.
- Processed files are tracked by file name only. An edited transcript that keeps its name is not reprocessed; a different transcript reusing a processed name is skipped.
- The whole transcript is sent in a single request with `max_tokens=4096` for the reply. Very long transcripts are not chunked or truncated.
- The model writes one record per transcript (more than one decision is put on separate lines inside the same record), not one record per decision.
- Privacy: transcripts are sent to the Anthropic API. Do not use confidential recordings unless that is acceptable under your data policy. `transcripts_in/` and the generated records are git-ignored so they are not committed by accident.
- The rename-into-place handler (`on_moved`) is code-reviewed only; it was not exercised in a test.
- Never commit your API key. `.env` files are git-ignored.

## License

Released under the MIT License: see [LICENSE](LICENSE). Replace it with another license if you prefer.
