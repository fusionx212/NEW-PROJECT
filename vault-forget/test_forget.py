import datetime as dt, subprocess, sys, tempfile, textwrap
from pathlib import Path
import forget

TODAY = dt.date(2026, 10, 26)

def w(root, rel, body):
    p = root / rel; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")

def build(root):
    d = "clients/acme/decisions"
    w(root, f"{d}/001 Use Postgres.md", """
        ---
        title: Use Postgres
        date: 2025-01-10
        status: Superseded by [[002 Use CockroachDB]]
        ---
        # ADR-001""")
    w(root, f"{d}/002 Use CockroachDB.md", """
        ---
        title: Use CockroachDB
        date: 2026-03-01
        status: Accepted
        ---
        Replaces [[001 Use Postgres]].""")
    w(root, "clients/acme/references/Pricing 2025.md", """
        ---
        title: Pricing 2025
        date: 2025-02-01
        valid_until: 2025-12-31
        ---""")
    w(root, "clients/acme/references/Pricing 2026.md", """
        ---
        title: Pricing 2026
        date: 2026-01-05
        supersedes: "[[Old rate card]]"
        ---""")
    w(root, "clients/acme/references/Old rate card.md", "---\ntitle: Old rate card\ndate: 2024-06-01\n---\n")
    w(root, "clients/acme/meetings/2026-02-01 Weekly sync.md", "---\ntitle: Weekly sync\n---\n")
    w(root, "clients/acme/meetings/2026-09-01 Weekly sync.md", "---\ntitle: Weekly sync\n---\n")
    w(root, "operational/notes/2026-05-01 Hosting setup.md", "---\ntitle: Hosting setup\n---\nOn Netlify\n")
    w(root, "operational/notes/2026-10-01 Hosting setup.md", "---\ntitle: Hosting setup\n---\nOn Fastly\n")
    w(root, "operational/notes/2025-01-01 Forgotten idea.md", "no frontmatter\n")
    w(root, "operational/notes/2025-01-02 Linked idea.md", "x\n")
    w(root, "clients/acme/Acme.md", "---\ntitle: Acme\ndate: 2026-10-01\n---\nSee [[2025-01-02 Linked idea]]\n")
    w(root, "personal/notes/2020-01-01 Diary.md", "x\n")
    w(root, "clients/acme/Tasks Acme.md", "---\ndate: 2020-01-01\n---\n")
    w(root, "archive/2019-01-01 Already gone.md", "---\nstatus: Superseded\n---\n")

def run(root, *extra):
    return forget.main([str(root), "--today", str(TODAY), *extra])

def test_dry_run_and_apply():
    with tempfile.TemporaryDirectory() as t:
        root = Path(t); build(root)
        notes = forget.load(root)
        archive, review = forget.find(notes, TODAY, 180, 0.85, False)
        assert set(archive) == {"001 Use Postgres", "Pricing 2025", "Old rate card"}, archive
        rv = dict(review)
        assert "conflict" in rv["2026-05-01 Hosting setup"]
        assert not any("Weekly sync" in k for k in rv)    # episodic log left alone
        assert "2025-01-01 Forgotten idea" in rv          # stale, unlinked
        assert "2025-01-02 Linked idea" not in rv          # linked from dashboard
        assert "2020-01-01 Diary" not in rv                # personal excluded
        assert "Tasks Acme" not in rv                      # living file
        assert "Pricing 2025" not in rv                    # already archive tier
        # "Pricing 2025" vs "Pricing 2026" title match is 92%: flagged, by design
        # dry run moves nothing
        run(root, "--report", "operational/daily/2026-10-26 Forgetting report.md")
        assert (root / "clients/acme/decisions/001 Use Postgres.md").exists()
        # saved report must not rescue stale notes on the next pass
        notes = forget.load(root)
        _, review2 = forget.find(notes, TODAY, 180, 0.85, False)
        assert "2025-01-01 Forgotten idea" in dict(review2)
        # apply
        run(root, "--apply")
        assert not (root / "clients/acme/decisions/001 Use Postgres.md").exists()
        assert (root / "archive/clients/acme/decisions/001 Use Postgres.md").exists()
        assert (root / "archive/clients/acme/references/Old rate card.md").exists()
        assert (root / "operational/notes/2025-01-01 Forgotten idea.md").exists()  # review never moved
        log = (root / "archive/_forgetting-log.md").read_text()
        assert log.count("→") == 3
        # idempotent
        notes = forget.load(root)
        assert forget.find(notes, TODAY, 180, 0.85, False)[0] == {}

if __name__ == "__main__":
    test_dry_run_and_apply(); print("ok")
