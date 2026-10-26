#!/usr/bin/env python3
"""Forgetting pass for a Mind++ (Obsidian) vault.

Finds notes that should stop feeding the agent and, with --apply, moves the
certain ones into archive/ (same relative path). Nothing is ever deleted.

Two tiers:
  ARCHIVE  certain, rule-based, moved on --apply
           - ADR with status Superseded / Deprecated / Rejected
           - any note with expires: or valid_until: in the past
           - any note named in another note's `supersedes:` frontmatter
  REVIEW   heuristic, report only, never moved
           - possible conflicts: two active notes in the same folder with
             near-identical titles and different dates (newer probably wins)
           - stale: older than --stale-days, nothing links to it

Stdlib only. Default is a dry run.
"""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

SKIP_DIRS = {".git", ".obsidian", ".trash", "archive", "templates", ".auto-memory"}
# Living files that are expected to sit untouched for a long time.
NEVER_STALE = re.compile(r"^(Tasks .*|Open Tasks|CLAUDE|README|index)\.md$", re.I)
DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})")
WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")
DEAD_STATUS = re.compile(r"^\s*(superseded|deprecated|rejected)\b", re.I)
LOG_NAME = "_forgetting-log.md"
# Episodic log folders: recurring titles are normal and age is not staleness.
EPISODIC = {"meetings", "daily"}


@dataclass
class Note:
    path: Path  # relative to vault root
    meta: dict
    links: set[str]
    date: dt.date | None
    date_source: str
    inbound: set[str] = field(default_factory=set)

    @property
    def stem(self) -> str:
        return self.path.stem

    @property
    def title(self) -> str:
        t = str(self.meta.get("title") or self.stem)
        return DATE_PREFIX.sub("", t).strip(" -_")


def parse_frontmatter(text: str) -> dict:
    """Minimal YAML frontmatter: flat `key: value` and `- item` lists."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    meta: dict = {}
    key = None
    for line in text[3:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if m:
            key, val = m.group(1).lower(), m.group(2).strip()
            val = val.strip("'\"")
            if val.startswith("[") and val.endswith("]") and not val.startswith("[["):
                meta[key] = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
            else:
                meta[key] = val
        elif key and re.match(r"^\s*-\s+", line):
            item = re.sub(r"^\s*-\s+", "", line).strip().strip("'\"")
            if not isinstance(meta.get(key), list):
                meta[key] = [] if meta.get(key) in ("", None) else [meta[key]]
            meta[key].append(item)
    return meta


def to_date(val) -> dt.date | None:
    if not val:
        return None
    m = re.search(r"\d{4}-\d{2}-\d{2}", str(val))
    if not m:
        return None
    try:
        return dt.date.fromisoformat(m.group(0))
    except ValueError:
        return None


def link_targets(val) -> list[str]:
    """Wikilink targets from a frontmatter value (string or list)."""
    vals = val if isinstance(val, list) else [val]
    out = []
    for v in vals:
        found = WIKILINK.findall(str(v))
        out.extend(found or ([str(v)] if v else []))
    return [Path(t.strip()).stem for t in out if t.strip()]


def load(vault: Path) -> dict[str, Note]:
    notes: dict[str, Note] = {}
    for root, dirs, files in os.walk(vault):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for f in files:
            if not f.endswith(".md"):
                continue
            full = Path(root) / f
            rel = full.relative_to(vault)
            text = full.read_text(encoding="utf-8", errors="replace")
            meta = parse_frontmatter(text)
            date, src = to_date(meta.get("date")), "frontmatter"
            if not date and (m := DATE_PREFIX.match(f)):
                date, src = to_date(m.group(1)), "filename"
            if not date:
                date, src = dt.date.fromtimestamp(full.stat().st_mtime), "mtime"
            links = {Path(t.strip()).stem for t in WIKILINK.findall(text)}
            note = Note(rel, meta, links, date, src)
            # Obsidian resolves links by basename; first one wins on collision.
            notes.setdefault(note.stem, note)
    for n in notes.values():
        tags = n.meta.get("tags") or []
        if "vault-maintenance" in (tags if isinstance(tags, list) else [tags]):
            continue  # our own reports must not keep stale notes alive
        for t in n.links:
            if t in notes and t != n.stem:
                notes[t].inbound.add(n.stem)
    return notes


def find(notes: dict[str, Note], today: dt.date, stale_days: int,
         similarity: float, include_personal: bool):
    archive: dict[str, str] = {}
    review: list[tuple[str, str]] = []

    for n in notes.values():
        status = str(n.meta.get("status", ""))
        if DEAD_STATUS.match(status):
            archive[n.stem] = f"status: {status}"
        for k in ("expires", "valid_until"):
            d = to_date(n.meta.get(k))
            if d and d < today:
                archive.setdefault(n.stem, f"{k} {d} has passed")
        for target in link_targets(n.meta.get("supersedes")):
            if target in notes and target != n.stem:
                archive.setdefault(target, f"superseded by [[{n.stem}]]")

    def eligible(n: Note) -> bool:
        if n.stem in archive:
            return False
        top = n.path.parts[0] if len(n.path.parts) > 1 else ""
        if EPISODIC & set(n.path.parts[:-1]):
            return False
        return include_personal or top != "personal"

    # Possible conflicts: same folder, similar title, different dates.
    by_dir: dict[Path, list[Note]] = {}
    for n in notes.values():
        if eligible(n) and not NEVER_STALE.match(n.path.name):
            by_dir.setdefault(n.path.parent, []).append(n)
    for group in by_dir.values():
        group.sort(key=lambda x: x.date or dt.date.min)
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if a.date == b.date:
                    continue
                r = difflib.SequenceMatcher(None, a.title.lower(), b.title.lower()).ratio()
                if r >= similarity:
                    review.append((a.stem, f"possible conflict with newer [[{b.stem}]] "
                                           f"(title match {r:.0%}); keep one, archive or mark the other"))

    # Stale and unreferenced.
    cutoff = today - dt.timedelta(days=stale_days)
    for n in notes.values():
        if not eligible(n) or NEVER_STALE.match(n.path.name):
            continue
        top = n.path.parts[0] if len(n.path.parts) > 1 else ""
        if top == "inbox":
            continue  # inbox age is the auditor's job
        if n.date and n.date < cutoff and not n.inbound:
            review.append((n.stem, f"stale: dated {n.date} ({n.date_source}), nothing links to it"))

    return archive, review


def report(vault, notes, archive, review, today, applied) -> str:
    mtime_dated = sum(1 for n in notes.values() if n.date_source == "mtime")
    out = [
        "---", f"title: Forgetting report {today}", f"date: {today}",
        "tags:", "  - vault-maintenance", "---", "",
        f"# Forgetting report — {today}", "",
        f"Scanned {len(notes)} notes. {len(archive)} to archive, {len(review)} to review."
        + (" Archive moves APPLIED." if applied else " Dry run: nothing moved."), "",
    ]
    if mtime_dated:
        out += [f"> {mtime_dated} notes have no date in frontmatter or filename; their age "
                "comes from file mtime, which a git clone or sync resets.", ""]
    out += [f"## Archive ({len(archive)})", ""]
    out += [f"- [[{s}]] `{notes[s].path}` — {why}" for s, why in sorted(archive.items())] or ["- none"]
    out += ["", f"## Review ({len(review)})", ""]
    out += [f"- [[{s}]] — {why}" for s, why in sorted(review)] or ["- none"]
    return "\n".join(out) + "\n"


def apply_moves(vault: Path, notes, archive, today) -> list[str]:
    moved, log = [], []
    for stem, why in sorted(archive.items()):
        src = vault / notes[stem].path
        dst = vault / "archive" / notes[stem].path
        if dst.exists():
            print(f"skip {src}: {dst} already exists", file=sys.stderr)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        moved.append(str(notes[stem].path))
        log.append(f"- {today} `{notes[stem].path}` → `archive/{notes[stem].path}` — {why}")
    if log:
        logf = vault / "archive" / LOG_NAME
        head = "" if logf.exists() else "# Forgetting log\n\nMoves made by forget.py. Reverse with `git mv` or by moving the file back.\n\n"
        with logf.open("a", encoding="utf-8") as fh:
            fh.write(head + "\n".join(log) + "\n")
    return moved


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("vault", type=Path, help="vault root")
    p.add_argument("--apply", action="store_true", help="move ARCHIVE items into archive/")
    p.add_argument("--stale-days", type=int, default=180)
    p.add_argument("--similarity", type=float, default=0.85, help="title match threshold for conflicts")
    p.add_argument("--include-personal", action="store_true")
    p.add_argument("--report", type=Path, help="write report here (relative paths are inside the vault)")
    p.add_argument("--today", type=dt.date.fromisoformat, default=dt.date.today())
    a = p.parse_args(argv)

    vault = a.vault.resolve()
    if not vault.is_dir():
        p.error(f"{vault} is not a directory")
    notes = load(vault)
    archive, review = find(notes, a.today, a.stale_days, a.similarity, a.include_personal)
    text = report(vault, notes, archive, review, a.today, a.apply)
    if a.apply:
        apply_moves(vault, notes, archive, a.today)
    if a.report:
        dest = a.report if a.report.is_absolute() else vault / a.report
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
