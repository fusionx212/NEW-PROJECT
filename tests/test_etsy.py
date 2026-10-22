"""Offline tests for skysoftly.etsy: no network, no Etsy, no rendering."""
import base64
import datetime as dt
import hashlib
import json
import os
import stat
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pytest
import requests

from skysoftly import etsy
from skysoftly.etsy import (EtsyClient, EtsyConfig, OrderWatcher, Town, TokenStore, parse_personalization)

FIXTURE = Path(__file__).parent / "fixtures" / "etsy_receipts.json"
TODAY = dt.date(2026, 10, 22)

TOWNS = {
    "leeds": [Town("Leeds", "GB", 536280, "Europe/London", 53.79648, -1.54785, "ENG")],
    "manchester": [Town("Manchester", "GB", 395515, "Europe/London", 53.48095, -2.23743, "ENG"),
                   Town("Manchester", "US", 112109, "America/New_York", 42.99564, -71.45479, "NH")],
    "london": [Town("London", "GB", 8961989, "Europe/London", 51.50853, -0.12574, "ENG"),
               Town("London", "CA", 422324, "America/Toronto", 42.98339, -81.23304, "08")],
    "boulder": [Town("Boulder", "US", 106803, "America/Denver", 40.01499, -105.27055, "CO")],
    "springfield": [Town("Springfield", "US", 114394, "America/Chicago", 39.80172, -89.64371, "IL"),
                    Town("Springfield", "US", 154341, "America/New_York", 42.10148, -72.58981, "MA")],
}


def towns(city):
    return TOWNS.get(city.lower(), [])


def parse(text, country="GB"):
    return parse_personalization(text, country, TODAY, towns)


@pytest.fixture
def cfgdir(tmp_path, monkeypatch):
    d = tmp_path / "config"
    monkeypatch.setenv("SKYSOFTLY_CONFIG_DIR", str(d))
    for k in ("ETSY_KEYSTRING", "ETSY_SHARED_SECRET", "ETSY_SHOP_ID", "ETSY_REDIRECT_URI", "SMTP_HOST", "SMTP_TO"):
        monkeypatch.delenv(k, raising=False)
    return d


CFG = EtsyConfig(keystring="abc123keystring", shared_secret="s3cr3t", shop_id=5550001)


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body if body is not None else {}, headers or {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


# ---------------------------------------------------------------- PKCE and OAuth

def test_pkce_rfc7636_example():
    # RFC 7636 Appendix B
    assert etsy.code_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_pkce_verifier_shape_and_challenge():
    seen = set()
    for _ in range(20):
        v = etsy.make_code_verifier()
        assert 43 <= len(v) <= 128 and all(c.isalnum() or c in "-._~" for c in v)
        c = etsy.code_challenge(v)
        expect = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).decode().rstrip("=")
        assert c == expect and "=" not in c and len(c) == 43
        seen.add(v)
    assert len(seen) == 20
    with pytest.raises(ValueError):
        etsy.code_challenge("too-short")


def test_authorize_url_has_pkce_state_and_minimal_scopes():
    url = etsy.authorize_url(CFG, "st4te", "ch4llenge")
    u = urllib.parse.urlsplit(url)
    q = dict(urllib.parse.parse_qsl(u.query))
    assert f"{u.scheme}://{u.netloc}{u.path}" == "https://www.etsy.com/oauth/connect"
    assert q == {"response_type": "code", "client_id": "abc123keystring", "redirect_uri": "http://localhost:3003/callback",
                 "scope": "transactions_r shops_r", "state": "st4te", "code_challenge": "ch4llenge",
                 "code_challenge_method": "S256"}
    assert "%20" in url  # scopes space-separated


def test_parse_callback_checks_state():
    assert etsy.parse_callback("http://localhost:3003/callback?code=abc&state=xyz", "xyz") == "abc"
    with pytest.raises(etsy.AuthError):
        etsy.parse_callback("http://localhost:3003/callback?code=abc&state=evil", "xyz")
    with pytest.raises(etsy.AuthError):
        etsy.parse_callback("code=abc", "xyz")
    with pytest.raises(etsy.AuthError, match="access_denied"):
        etsy.parse_callback("error=access_denied&state=xyz", "xyz")


def _free_port():
    import socket
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    return p


@pytest.mark.parametrize("state,ok", [("good", True), ("bad", False)])
def test_one_shot_callback_server(state, ok):
    port = _free_port()
    redirect = f"http://127.0.0.1:{port}/callback"
    result = {}

    def run():
        try:
            result["code"] = etsy.wait_for_callback(redirect, "good", timeout=10)
        except etsy.AuthError as e:
            result["error"] = str(e)
    t = threading.Thread(target=run); t.start()
    deadline = time.time() + 5
    while True:  # wait for the server to come up
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/favicon.ico", timeout=1)
        except urllib.error.HTTPError:
            break
        except OSError:
            if time.time() > deadline:
                raise
            time.sleep(0.05)
    try:
        urllib.request.urlopen(f"{redirect}?code=thecode&state={state}", timeout=5)
    except urllib.error.HTTPError as e:
        assert e.code == 400
    t.join(10)
    assert (result.get("code") == "thecode") is ok
    assert ("error" in result) is (not ok)


def test_exchange_code_posts_pkce_form(monkeypatch):
    calls = []

    def fake(method, url, **kw):
        calls.append((method, url, kw))
        return FakeResponse(200, {"access_token": "12345678.AAA", "token_type": "Bearer", "expires_in": 3600,
                                  "refresh_token": "12345678.RRR"})
    monkeypatch.setattr(requests, "request", fake)
    tok = etsy.exchange_code(CFG, "the-code", "v" * 50)
    method, url, kw = calls[0]
    assert method == "POST" and url == "https://api.etsy.com/v3/public/oauth/token"
    assert kw["data"] == {"grant_type": "authorization_code", "client_id": "abc123keystring",
                          "redirect_uri": "http://localhost:3003/callback", "code": "the-code", "code_verifier": "v" * 50}
    assert kw["headers"]["x-api-key"] == "abc123keystring:s3cr3t"
    assert tok["access_token"] == "12345678.AAA"


def test_user_id_from_token():
    assert etsy.user_id_from_token("12345678.abcDEF") == 12345678
    assert etsy.user_id_from_token("nodot") is None


def test_token_file_is_private(cfgdir):
    store = TokenStore()
    store.save({"access_token": "12345678.A", "refresh_token": "12345678.R", "expires_in": 3600})
    assert store.path == cfgdir / "etsy_token.json"
    assert stat.S_IMODE(os.stat(store.path).st_mode) == 0o600
    assert store.load()["user_id"] == 12345678


def test_expired_token_is_refreshed_and_saved(cfgdir, monkeypatch):
    store = TokenStore()
    store.save({"access_token": "12345678.OLD", "refresh_token": "12345678.R1", "expires_in": 3600}, now=time.time() - 7200)
    calls = []

    def fake(method, url, **kw):
        calls.append((method, url, kw))
        if url == etsy.TOKEN_URL:
            return FakeResponse(200, {"access_token": "12345678.NEW", "token_type": "Bearer", "expires_in": 3600,
                                      "refresh_token": "12345678.R2"})
        assert kw["headers"]["Authorization"] == "Bearer 12345678.NEW"
        assert kw["headers"]["x-api-key"] == "abc123keystring:s3cr3t"
        return FakeResponse(200, {"user_id": 12345678, "shop_id": 5550001})
    monkeypatch.setattr(requests, "request", fake)
    me = EtsyClient(CFG, store).get_me()
    assert me["shop_id"] == 5550001
    assert calls[0][2]["data"] == {"grant_type": "refresh_token", "client_id": "abc123keystring", "refresh_token": "12345678.R1"}
    saved = store.load()
    assert saved["access_token"] == "12345678.NEW" and saved["refresh_token"] == "12345678.R2"
    assert saved["expires_at"] > time.time() + 3000
    assert stat.S_IMODE(os.stat(store.path).st_mode) == 0o600


def test_fresh_token_is_not_refreshed(cfgdir, monkeypatch):
    store = TokenStore()
    store.save({"access_token": "12345678.OK", "refresh_token": "12345678.R", "expires_in": 3600})
    urls = []
    monkeypatch.setattr(requests, "request", lambda m, u, **kw: urls.append(u) or FakeResponse(200, {"shop_id": 1}))
    EtsyClient(CFG, store).get_me()
    assert urls == [etsy.API_BASE + "/users/me"]


def test_refresh_rejected_asks_for_login(cfgdir, monkeypatch):
    store = TokenStore()
    store.save({"access_token": "1.A", "refresh_token": "1.R", "expires_in": 3600}, now=time.time() - 7200)
    monkeypatch.setattr(requests, "request", lambda m, u, **kw: FakeResponse(400, {"error": "invalid_grant"}))
    with pytest.raises(etsy.AuthError, match="login"):
        EtsyClient(CFG, store).get_me()


def test_not_logged_in(cfgdir):
    with pytest.raises(etsy.AuthError, match="login"):
        EtsyClient(CFG, TokenStore()).get_me()


def test_429_backs_off_then_succeeds(cfgdir, monkeypatch):
    store = TokenStore()
    store.save({"access_token": "1.A", "refresh_token": "1.R", "expires_in": 3600})
    answers = [FakeResponse(429, {"error": "slow down"}, {"retry-after": "3"}), FakeResponse(503),
               FakeResponse(200, {"shop_id": 9})]
    monkeypatch.setattr(requests, "request", lambda m, u, **kw: answers.pop(0))
    slept = []
    assert EtsyClient(CFG, store, sleep=slept.append).get_me() == {"shop_id": 9}
    assert slept[0] >= 3 and len(slept) == 2


def test_429_forever_raises_rate_limited(cfgdir, monkeypatch):
    store = TokenStore()
    store.save({"access_token": "1.A", "refresh_token": "1.R", "expires_in": 3600})
    monkeypatch.setattr(requests, "request", lambda m, u, **kw: FakeResponse(429, {}, {"retry-after": "1"}))
    with pytest.raises(etsy.RateLimited):
        EtsyClient(CFG, store, sleep=lambda s: None, max_retries=2).get_me()


def test_receipts_query_and_paging(cfgdir, monkeypatch):
    store = TokenStore()
    store.save({"access_token": "1.A", "refresh_token": "1.R", "expires_in": 3600})
    pages = json.loads(FIXTURE.read_text())["results"]
    seen = []

    def fake(method, url, params=None, **kw):
        seen.append((url, dict(params or {})))
        if url.endswith("/transactions"):
            return FakeResponse(200, {"count": 1, "results": [{"transaction_id": 1, "variations": []}]})
        off = params["offset"]
        chunk = pages[off:off + params["limit"]]
        if off == 0:
            chunk = [dict(chunk[0], transactions=[])] + chunk[1:]  # one receipt without embedded transactions
        return FakeResponse(200, {"count": len(pages), "results": chunk})
    monkeypatch.setattr(requests, "request", fake)
    got = EtsyClient(CFG, store).paid_unshipped_receipts(min_created=1790000000, page_size=4)
    assert len(got) == len(pages)
    url, p = seen[0]
    assert url == "https://api.etsy.com/v3/application/shops/5550001/receipts"
    assert p["was_paid"] == "true" and p["was_shipped"] == "false" and p["was_canceled"] == "false"
    assert p["min_created"] == 1790000000 and p["limit"] == 4
    assert seen[1][1]["offset"] == 4
    assert any(u.endswith(f"/receipts/{pages[0]['receipt_id']}/transactions") for u, _ in seen)


def test_config_from_file_and_env(cfgdir, monkeypatch):
    cfgdir.mkdir(parents=True)
    (cfgdir / "etsy.json").write_text(json.dumps({"keystring": "k", "shared_secret": "TOPSECRET", "shop_id": 42}))
    c = etsy.load_config()
    assert (c.keystring, c.shared_secret, c.shop_id, c.redirect_uri) == ("k", "TOPSECRET", 42, "http://localhost:3003/callback")
    assert "TOPSECRET" not in repr(c)
    monkeypatch.setenv("ETSY_SHARED_SECRET", "envsecret")
    monkeypatch.setenv("ETSY_REDIRECT_URI", "http://localhost:4000/cb")
    c = etsy.load_config()
    assert c.api_key_header == "k:envsecret" and c.redirect_uri == "http://localhost:4000/cb"


def test_missing_config_is_a_clear_error(cfgdir):
    with pytest.raises(SystemExit, match="ETSY_KEYSTRING"):
        etsy.load_config()


# ---------------------------------------------------------------- receipts fixture

def test_fixture_items_and_personalisation():
    receipts = etsy.load_fixture(FIXTURE)
    by_id = {r["receipt_id"]: r for r in receipts}
    isla = etsy.order_items(by_id[3801234567])[0]
    assert isla.personalization.startswith("1) Isla") and "Grandma & Grandpa" in isla.personalization
    assert isla.other_choices == {"Package": "Story + Nebula Video"}
    oliver = etsy.order_items(by_id[3801234568])[0].personalization
    assert "Child's first name: oliver" in oliver and "Who it's from: Love from Nana" in oliver
    assert etsy.order_items(by_id[3801234570])[0].personalization is None
    assert not etsy.is_new_paid_order(by_id[3801234571])  # completed
    assert all(etsy.is_new_paid_order(by_id[i]) for i in (3801234567, 3801234568, 3801234569, 3801234570, 3801234572))


def test_fixture_receipts_parse():
    receipts = {r["receipt_id"]: r for r in etsy.load_fixture(FIXTURE)}

    def parsed(rid):
        r = receipts[rid]
        return parse_personalization(etsy.order_items(r)[0].personalization, r["country_iso"], TODAY, towns)
    a = parsed(3801234567)
    assert a.ok and a.fields.name == "Isla" and a.fields.giver == "Grandma & Grandpa" and a.fields.country == "GB"
    b = parsed(3801234568)
    assert b.ok, b.problems
    f = b.fields
    assert (f.name, f.pronoun, f.age, f.animal, f.colour, f.born, f.city, f.country, f.giver) == \
        ("Oliver", "he", 4, "fox", "blue", dt.date(2022, 5, 2), "Manchester", "GB", "Nana")
    assert not parsed(3801234569).ok  # free text with no numbers or labels


# ---------------------------------------------------------------- the parser on messy input

def test_parse_clean_numbered():
    r = parse("1) Isla 2) she 3) 5 4) bunny 5) purple 6) 2 May 2021, Leeds UK 7) Grandma and Grandpa "
              "8) Happy fifth birthday, darling!")
    assert r.ok, r.problems
    f = r.fields
    assert (f.name, f.pronoun, f.age, f.animal, f.colour, f.born, f.city, f.country, f.giver, f.message) == (
        "Isla", "she", 5, "bunny", "purple", dt.date(2021, 5, 2), "Leeds", "GB", "Grandma and Grandpa",
        "Happy fifth birthday, darling!")
    argv = f.story_argv(Path("out/x"), video=True)
    assert argv[:4] == ["story", "--name", "Isla", "--pronoun"] and "--video" in argv
    assert argv[argv.index("--born") + 1] == "2021-05-02" and argv[argv.index("--tz") + 1] == "Europe/London"
    assert argv[argv.index("--place-name") + 1] == "Leeds" and argv[argv.index("--country") + 1] == "GB"


@pytest.mark.parametrize("answer,expect", [
    ("2 May 2021, Leeds", dt.date(2021, 5, 2)),
    ("02/05/2021 Leeds", dt.date(2021, 5, 2)),       # UK day-first
    ("2021-05-02 in Leeds, England", dt.date(2021, 5, 2)),
    ("2nd of May, 2021 - Leeds, West Yorkshire, UK", dt.date(2021, 5, 2)),
    ("May 2nd 2021, Leeds", dt.date(2021, 5, 2)),
    ("born 2.5.2021 at Leeds", dt.date(2021, 5, 2)),
])
def test_parse_date_formats(answer, expect):
    r = parse(f"1) Isla 2) she 3) 5 4) bunny 5) purple 6) {answer} 7) Mum 8) Sleep tight")
    assert r.ok, r.problems
    assert r.fields.born == expect and r.fields.city == "Leeds" and r.fields.country == "GB"


def test_parse_dot_numbered_lines_lowercase_and_labels_inside():
    r = parse("1. name: oliver\n2. He/him\n3. turning 4\n4. A Fox\n5. Blue\n6. 02/05/2022 Manchester\n"
              "7. Love from Nana\n8. We love you to the moon and back.")
    assert r.ok, r.problems
    assert (r.fields.name, r.fields.pronoun, r.fields.age, r.fields.animal, r.fields.city) == ("Oliver", "he", 4, "fox", "Manchester")
    assert any("Capitalised" in n for n in r.notes) and any("Manchester" in n for n in r.notes)


def test_parse_labelled_any_night_no_birth():
    r = parse("Name: Mia\nPronoun: they\nAge: any night\nFavourite animal: owl\nFavourite colour: sparkly pink\n"
              "Birth date and town: n/a\nFrom: Auntie Jo\nMessage: Sweet dreams, little star.", "US")
    assert r.ok, r.problems
    f = r.fields
    assert f.any_night and f.age is None and f.born is None and f.colour == "pink" and f.pronoun == "they"
    assert "--age" not in f.story_argv(Path("o")) and "--born" not in f.story_argv(Path("o"))


def test_parse_etsy_multi_question_labels_with_curly_quotes_and_pronunciation():
    r = parse("Child’s first name: Zoë (pronounced ZO-ee)\nShe, he or they: she\nAge they’re turning (or “any night”): seven\n"
              "Favourite animal: Elephant\nFavourite colour: yellow\nBirth date and town (optional): 9th June 2019, Boulder, CO\n"
              "Who it’s from: Granny\nA short message for the star to read: Happy birthday!", "US")
    assert r.ok, r.problems
    f = r.fields
    assert (f.name, f.pronunciation, f.age, f.animal, f.city, f.country, f.tz) == (
        "Zoë", "ZO-ee", 7, "elephant", "Boulder", "US", "America/Denver")


def test_parse_numbers_inside_answers_dont_confuse_markers():
    r = parse("1) Ava 2) she 3) 3 4) cat 5) red 6) 13/04/2023, Boulder, Colorado 7) Dad 8) 3 cheers for our 3 year old!", "US")
    assert r.ok, r.problems
    assert r.fields.age == 3 and r.fields.born == dt.date(2023, 4, 13) and r.fields.message == "3 cheers for our 3 year old!"


@pytest.mark.parametrize("text,country,problem", [
    ("1) Leo 2) he 3) 6 4) bear 5) green 6) 2020-03-14 London 7) Mum 8) Love you", "US", "several countries"),
    ("1) Ava 2) she 3) 3 4) cat 5) red 6) 03/04/2023, Boulder, CO 7) Dad 8) Night", "US", "day/month or month/day"),
    ("1) Ava 2) she 3) 3 4) cat 5) red and blue 7) Dad 8) Night", "GB", "several colours"),
    ("1) Ava 2) she or he 3) 3 4) cat 5) red 7) Dad 8) Night", "GB", "More than one pronoun"),
    ("1) Ava 2) she 3) 4 or 5 4) cat 5) red 7) Dad 8) Night", "GB", "Age '4 or 5' is unclear"),
    ("1) Ava 2) she 3) 3 4) cat 5) red 6) 2 May 2023 7) Dad 8) Night", "GB", "no town"),
    ("1) Ava 2) she 3) 3 4) cat 5) red 6) Leeds 7) Dad 8) Night", "GB", "without a birth date"),
    ("1) Ava 2) she 3) 3 4) cat 5) red 6) 2 May 2023, Atlantis 7) Dad 8) Night", "GB", "isn't in the offline town list"),
    ("1) Ava 2) she 3) 3 4) cat 5) red 6) 30/02/2023, Leeds 7) Dad 8) Night", "GB", "not a real date"),
    ("1) Ava 2) she 3) 3 4) cat 5) red 6) 2 May 2027, Leeds 7) Dad 8) Night", "GB", "in the future"),
    ("1) Ava 2) she 3) 9 4) cat 5) red 6) 2 May 2023, Leeds 7) Dad 8) Night", "GB", "does not match the birth date"),
    ("1) Ava 2) she 3) 3 4) cat 5) red 6) 2 May 2023, Springfield, USA 7) Dad 8) Night", "US", "different time zones"),
    ("1) Ava 2) she 3) 3 4) cat 5) silver 7) Dad 8) Night", "GB", "isn't one the nebula knows"),
    ("1) Ava 3) 3 4) cat 5) red 7) Dad 8) Night", "GB", "Answer 2"),
    ("1) Ava 2) she 3) 3 4) cat 5) red 7) Dad", "GB", "Answer 8"),
    ("1) 2) she 3) 3 4) cat 5) red 7) Dad 8) Night", "GB", "name is missing"),
    ("Ava, she, 3, cat, red, from Dad", "GB", "Could not find the numbered answers"),
    ("", "GB", "No personalisation"),
])
def test_parse_flags_instead_of_guessing(text, country, problem):
    r = parse(text, country)
    assert not r.ok
    assert any(problem in p for p in r.problems), r.problems


def test_parse_long_message_flagged():
    long = " ".join(["word"] * 45)
    assert not parse(f"1) Ava 2) she 3) 3 4) cat 5) red 7) Dad 8) {long}").ok
    mid = " ".join(["word"] * 30)
    r = parse(f"1) Ava 2) she 3) 3 4) cat 5) red 7) Dad 8) {mid}")
    assert r.ok and any("30 words" in n for n in r.notes)


def test_country_codes():
    assert etsy.country_codes("UK") == {"GB"} and etsy.country_codes("Scotland") == {"GB"}
    assert etsy.country_codes("USA") == {"US"} and etsy.country_codes("texas") == {"US"}
    assert etsy.country_codes("CA") == {"US", "CA"}
    assert etsy.country_codes("France") == {"FR"}
    assert etsy.country_codes("Yorkshire pudding") == set()


# ---------------------------------------------------------------- the watcher

def make_watcher(tmp_path, builds, sent=None, **kw):
    def build(argv):
        builds.append(argv)
        out = Path(argv[argv.index("--out") + 1])
        out.mkdir(parents=True, exist_ok=True)
        for n in ("story.mp3", "storybook.pdf", "certificate.jpg"):
            (out / n).write_bytes(b"x" * 1000)
    sent = [] if sent is None else sent
    return OrderWatcher(tmp_path / "orders", build_pack=build, send=lambda s, b: sent.append((s, b)) or True,
                        town_lookup=towns, today=TODAY, **kw)


def test_watcher_builds_reviews_and_skips(tmp_path):
    builds, sent = [], []
    w = make_watcher(tmp_path, builds, sent)
    receipts = etsy.load_fixture(FIXTURE)
    results = {r["receipt_id"]: r["status"] for r in w.process(receipts)}
    assert results == {3801234567: "ready", 3801234568: "ready", 3801234569: "needs-review",
                       3801234570: "needs-review", 3801234572: "ready"}  # 3801234571 is completed: ignored
    assert len(builds) == 3
    root = tmp_path / "orders"
    isla = root / "3801234567"
    order = json.loads((isla / "order.json").read_text())
    assert order["items"][0]["fields"]["name"] == "Isla" and order["packs"][0]["argv"] == builds[0]
    ready = (isla / "READY.txt").read_text()
    assert "story.mp3" in ready and "Mark the order complete" in ready and "Listen to the first minute" in ready
    assert builds[0][builds[0].index("--out") + 1] == str(isla / "pack")
    review = root / "needs-review" / "3801234570"
    assert "No personalisation" in (review / "REASON.txt").read_text()
    assert json.loads((review / "order.json").read_text())["message_from_buyer"].startswith("Sorry")
    assert (root / "needs-review" / "3801234569" / "REASON.txt").exists()
    assert len(sent) == 5 and any("needs review" in s for s, _ in sent)

    # same poll again, and again after a "restart": nothing is rebuilt
    assert w.process(receipts) == []
    w2 = make_watcher(tmp_path, builds)
    assert w2.process(receipts) == [] and len(builds) == 3
    state = json.loads((root / "processed.json").read_text())
    assert state["3801234567"]["status"] == "ready" and state["3801234570"]["status"] == "needs-review"

    # forgetting a receipt lets it be processed again
    assert w2.state.forget(3801234567)
    assert [r["receipt_id"] for r in make_watcher(tmp_path, builds).process(receipts)] == [3801234567]
    assert len(builds) == 4


def test_watcher_video_flag_and_build_failure(tmp_path):
    builds = []
    receipts = [r for r in etsy.load_fixture(FIXTURE) if r["receipt_id"] == 3801234567]
    w = make_watcher(tmp_path, builds, video=True)
    w.process(receipts)
    assert "--video" in builds[0]
    assert "video link" in (tmp_path / "orders" / "3801234567" / "READY.txt").read_text()

    def boom(argv):
        raise SystemExit("City not found offline")
    w3 = OrderWatcher(tmp_path / "orders3", build_pack=boom, send=lambda s, b: True, town_lookup=towns, today=TODAY)
    assert w3.process(receipts)[0]["status"] == "needs-review"
    assert "City not found" in (tmp_path / "orders3" / "needs-review" / "3801234567" / "REASON.txt").read_text()


def test_watch_loop_survives_errors(tmp_path):
    builds, sent = [], []
    w = make_watcher(tmp_path, builds, sent)
    receipts = etsy.load_fixture(FIXTURE)
    answers = [etsy.RateLimited("429"), requests.ConnectionError("down"), etsy.AuthError("login again"), receipts]

    def fetch():
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a
    slept = []
    etsy.watch_loop(w, fetch, every_minutes=5, sleep=slept.append, max_polls=4)
    assert len(builds) == 3 and not answers
    assert slept == [300, 600, 300]  # backs off after repeated failures, resets after an auth error
    assert any("sign in again" in s for s, _ in sent)


def test_notify_without_smtp_settings_does_nothing():
    assert etsy.notify("s", "b", env={}) is False


def test_notify_uses_smtp(monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            sent["host"] = (host, port)
        def starttls(self): sent["tls"] = True
        def login(self, u, p): sent["login"] = u
        def send_message(self, m): sent["msg"] = m
        def __enter__(self): return self
        def __exit__(self, *a): pass
    monkeypatch.setattr(etsy.smtplib, "SMTP", FakeSMTP)
    ok = etsy.notify("Ready", "Body", env={"SMTP_HOST": "smtp.example.com", "SMTP_TO": "me@example.com",
                                           "SMTP_USER": "me@example.com", "SMTP_PASSWORD": "pw"})
    assert ok and sent["host"] == ("smtp.example.com", 587) and sent["tls"] and sent["msg"]["Subject"] == "Ready"


def test_cli_dry_run_fetch_once(tmp_path, monkeypatch, capsys):
    builds = []
    monkeypatch.setattr(etsy, "build_pack_with_cli", lambda argv: builds.append(argv))
    monkeypatch.setattr(etsy, "_today", lambda: TODAY)
    etsy.main(["fetch", "--once", "--dry-run", str(FIXTURE), "--out", str(tmp_path / "o"), "--no-audio"])
    out = capsys.readouterr().out
    assert "5 new order(s)" in out and len(builds) == 3 and all("--no-audio" in b for b in builds)
    etsy.main(["fetch", "--dry-run", str(FIXTURE), "--out", str(tmp_path / "o")])
    assert "0 new order(s)" in capsys.readouterr().out and len(builds) == 3
