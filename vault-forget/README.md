# vault-forget

Forgetting pass for a Mind++ / Obsidian vault. Stdlib Python 3.9+, no dependencies, no LLM calls.

```
python3 forget.py ~/vault                       # dry run, prints report
python3 forget.py ~/vault --report "operational/daily/$(date +%F) Forgetting report.md"
python3 forget.py ~/vault --apply               # move ARCHIVE items to archive/
python3 test_forget.py                          # fixture test
```

**Archive tier** (moved on `--apply`, to `archive/<same path>`, logged in `archive/_forgetting-log.md`):
- ADR `status:` Superseded / Deprecated / Rejected
- `expires:` or `valid_until:` date in the past
- named in another note's `supersedes: "[[Note]]"`

**Review tier** (report only, never moved):
- possible conflict: same folder, title match ≥ 85%, different dates
- stale: older than 180 days and nothing links to it

Skipped: `archive/`, `templates/`, dot folders, `personal/` (unless `--include-personal`),
`meetings/` and `daily/` (episodic log), `Tasks *.md` and dashboards that are linked.
Reports carry the `vault-maintenance` tag and do not count as inbound links.

Nothing is deleted. Obsidian resolves `[[links]]` by filename, so moved notes stay linkable.
Run it in a committed vault so `git` can undo any move.
