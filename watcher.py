"""
Decision Records prototype - folder watcher + Claude extractor.

Watches TRANSCRIPTS_FOLDER for new meeting transcripts (.txt, .vtt, .docx),
sends each one to Claude to extract the Decision + Context fields described
in README.md, and writes one Markdown file per meeting into
LIBRECHAT_FILE_SEARCH_FOLDER - the folder to feed into LibreChat's
file-search for this trial (see README.md for the manual upload step this
script does NOT do on its own).

First prototype only: single machine, run in a terminal, no
service/auto-restart wiring yet.
"""

import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path

import anthropic
from docx import Document
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

# ---------------- Config ----------------

BASE_DIR = Path(__file__).resolve().parent
TRANSCRIPTS_FOLDER = BASE_DIR / "transcripts_in"
OUTPUT_FOLDER = BASE_DIR / "librechat_file_search"
PROCESSED_LOG = BASE_DIR / ".processed.json"

# Override with DECISION_RECORDS_MODEL if you want a different Claude model.
MODEL = os.environ.get("DECISION_RECORDS_MODEL", "claude-sonnet-5")
SUPPORTED_EXTENSIONS = {".txt", ".vtt", ".docx"}
STABLE_CHECK_SECONDS = 2  # a file's size must stay unchanged this long before it's read

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger("decision-records-watcher")

# ---------------- Extraction schema/prompt ----------------
# Field names mirror a typical decision-log column list (for example a
# SharePoint list or a spreadsheet), so mapping this into real columns later
# is a rename, not a redesign.

SYSTEM_PROMPT = """You extract structured meeting information from a raw \
meeting transcript for a team's Decision Records log.

Read the transcript and return ONLY a single JSON object (no other text, no \
markdown code fences) with exactly these keys:

Decision fields:
- "date_or_meeting": the meeting's date and/or name, if mentioned; else "".
- "category": one of "Financial Review", "Account Planning", "GTM", \
"MIS & Business Ops", or "Other" - pick the closest fit.
- "question_considered": what was being decided, in one sentence.
- "assumptions": what was taken as given going into the decision.
- "evidence_reviewed": what data/evidence was actually looked at, if any.
- "decision_made": the actual decision(s). If more than one distinct \
decision was made, put each on its own line starting with "- ".
- "resulting_action": what happens next, matching each decision above \
line for line if there are multiple.
- "owner": who is accountable for the resulting action(s), by name if \
mentioned.
- "status": one of "Open", "In Progress", "Done", "Superseded".

Context fields:
- "account_client": the client/account this meeting concerns, if any; else "".
- "stakeholders_mentioned": people/roles mentioned, one per line.
- "requirements_mentioned": requirements or needs mentioned, one per line.
- "products_discussed": products/capabilities discussed, one per line.
- "open_questions": anything left unresolved, one per line.

Rules:
- Never invent information. If a field genuinely has nothing to report, use \
an empty string "" - do not guess or pad it with generic text.
- Base "category" and "status" only on what's actually said, not assumptions.
- Keep every field factual and traceable to something actually said in the \
transcript."""


def build_user_prompt(transcript_text: str) -> str:
    return f"Transcript:\n\n{transcript_text}"


# ---------------- Transcript reading ----------------

_VTT_CUE_RE = re.compile(r"^\d{2}:\d{2}:\d{2}[.,]\d{3} --> .*$", re.MULTILINE)


def read_transcript_text(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".vtt":
        # Strip WEBVTT header/timing-cue/cue-number lines - keeps the actual
        # spoken text, cuts token noise. Not required, just cheaper/cleaner.
        text = _VTT_CUE_RE.sub("", text)
        text = re.sub(r"(?m)^WEBVTT.*$", "", text)
        text = re.sub(r"(?m)^\d+$", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------- Claude extraction ----------------

def extract_fields(client: anthropic.Anthropic, transcript_text: str) -> dict:
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_user_prompt(transcript_text)}],
    )
    raw = next(b.text for b in response.content if b.type == "text").strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    return json.loads(raw)


# ---------------- Markdown rendering ----------------

def _block(value: str) -> str:
    value = (value or "").strip()
    return value if value else "-"


def render_markdown(fields: dict, source_filename: str) -> str:
    return f"""# {fields.get('date_or_meeting') or source_filename}

**Source transcript:** `{source_filename}`
**Processed:** {datetime.now().strftime('%Y-%m-%d %H:%M')}

## Decision

- **Category:** {fields.get('category', '')}
- **Question Considered:** {fields.get('question_considered', '')}
- **Assumptions:** {fields.get('assumptions', '')}
- **Data/Evidence Reviewed:** {fields.get('evidence_reviewed', '')}
- **Owner:** {fields.get('owner', '')}
- **Status:** {fields.get('status', '')}

**Decision Made:**
{_block(fields.get('decision_made', ''))}

**Resulting Action:**
{_block(fields.get('resulting_action', ''))}

## Context

- **Account/Client:** {fields.get('account_client', '')}

**Stakeholders Mentioned:**
{_block(fields.get('stakeholders_mentioned', ''))}

**Requirements Mentioned:**
{_block(fields.get('requirements_mentioned', ''))}

**Products/Capabilities Discussed:**
{_block(fields.get('products_discussed', ''))}

**Open Questions:**
{_block(fields.get('open_questions', ''))}
"""


# ---------------- Processed-file tracking ----------------

def load_processed() -> set:
    if PROCESSED_LOG.exists():
        return set(json.loads(PROCESSED_LOG.read_text(encoding="utf-8")))
    return set()


def mark_processed(name: str, processed: set) -> None:
    processed.add(name)
    PROCESSED_LOG.write_text(json.dumps(sorted(processed), indent=2), encoding="utf-8")


# ---------------- Wait for a file to finish being written ----------------

def wait_until_stable(path: Path, check_seconds: int = STABLE_CHECK_SECONDS) -> bool:
    """Polls the file's size until it stops changing, so a file still being
    copied/synced (e.g. by a cloud-sync client) isn't read half-written.
    Returns False if the file disappears before it stabilizes."""
    last_size = -1
    while True:
        if not path.exists():
            return False
        size = path.stat().st_size
        if size == last_size:
            return True
        last_size = size
        time.sleep(check_seconds)


# ---------------- Core processing ----------------

def process_file(path: Path, client: anthropic.Anthropic, processed: set) -> None:
    if path.name in processed or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return

    log.info("New transcript detected: %s", path.name)
    if not wait_until_stable(path):
        log.warning("File disappeared before it stabilized, skipping: %s", path.name)
        return

    try:
        transcript_text = read_transcript_text(path)
        if not transcript_text:
            log.warning("Transcript is empty, skipping: %s", path.name)
            return

        fields = extract_fields(client, transcript_text)
        markdown = render_markdown(fields, path.name)

        OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
        out_path = OUTPUT_FOLDER / f"{path.stem}.md"
        out_path.write_text(markdown, encoding="utf-8")

        mark_processed(path.name, processed)
        log.info("Wrote %s", out_path.name)
    except json.JSONDecodeError:
        log.error("Claude's response wasn't valid JSON for %s - not marking processed, will retry next run.", path.name)
    except Exception:
        log.exception("Failed to process %s - not marking processed, will retry next run.", path.name)


# ---------------- Watchdog handler ----------------

class TranscriptHandler(FileSystemEventHandler):
    def __init__(self, client: anthropic.Anthropic, processed: set):
        self.client = client
        self.processed = processed

    def on_created(self, event):
        if not event.is_directory:
            process_file(Path(event.src_path), self.client, self.processed)

    def on_moved(self, event):
        # Some sync tools write to a temp name then rename into place - catch
        # that pattern too, not just on_created.
        if not event.is_directory:
            process_file(Path(event.dest_path), self.client, self.processed)


# ---------------- Entry point ----------------

def main():
    TRANSCRIPTS_FOLDER.mkdir(parents=True, exist_ok=True)
    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    processed = load_processed()

    # Catch anything already sitting in the folder before the watcher started.
    for existing in sorted(TRANSCRIPTS_FOLDER.iterdir()):
        process_file(existing, client, processed)

    handler = TranscriptHandler(client, processed)
    observer = Observer()
    observer.schedule(handler, str(TRANSCRIPTS_FOLDER), recursive=False)
    observer.start()
    log.info("Watching %s for new transcripts... (Ctrl+C to stop)", TRANSCRIPTS_FOLDER)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
