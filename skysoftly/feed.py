"""Podcast RSS 2.0 feed (with Apple Podcasts tags) for a folder of nightly episodes."""
from __future__ import annotations

import datetime as dt
import email.utils
import json
from pathlib import Path
from xml.sax.saxutils import escape


def build_feed(folder: Path, base_url: str, city: str, author: str = "Tonight's Sky, Softly",
               email_addr: str = "hello@example.com") -> Path:
    eps = [json.loads(p.read_text()) for p in folder.glob("*/episode.json")]
    base = base_url.rstrip("/")
    items = []
    for e in sorted(eps, key=lambda e: e["date"], reverse=True):
        pub = dt.datetime.fromisoformat(e["date"] + "T17:00:00").replace(tzinfo=dt.timezone.utc)
        url = f"{base}/{e['slug']}/{e['audio']}"
        items.append(f"""    <item>
      <title>{escape(e['title'])}</title>
      <description>{escape(e['summary'])}</description>
      <enclosure url="{escape(url)}" length="{e['bytes']}" type="audio/mpeg"/>
      <guid isPermaLink="false">{escape(e['slug'])}</guid>
      <pubDate>{email.utils.format_datetime(pub)}</pubDate>
      <itunes:duration>{int(e['duration_s'])}</itunes:duration>
      <itunes:explicit>false</itunes:explicit>
      <itunes:episodeType>full</itunes:episodeType>
    </item>""")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>{escape(f"Tonight's Sky, Softly: {city}")}</title>
    <link>{escape(base)}</link>
    <language>en</language>
    <description>{escape(f"A gentle bedtime broadcast of the real sky over {city}, every night: the Moon, the planets, the stars above your roof, and one small sky fact. Look out of the window, then lights out.")}</description>
    <itunes:author>{escape(author)}</itunes:author>
    <itunes:owner><itunes:name>{escape(author)}</itunes:name><itunes:email>{escape(email_addr)}</itunes:email></itunes:owner>
    <itunes:image href="{escape(base)}/cover.png"/>
    <itunes:category text="Kids &amp; Family"/>
    <itunes:category text="Science"><itunes:category text="Astronomy"/></itunes:category>
    <itunes:explicit>false</itunes:explicit>
{chr(10).join(items)}
  </channel>
</rss>
"""
    out = folder / "feed.xml"
    out.write_text(xml)
    return out
