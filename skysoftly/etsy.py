"""Etsy order automation: read paid orders, parse the buyer's personalisation, build the gift pack.

Run it as `python -m skysoftly.etsy <subcommand>`:

    login              one-time OAuth sign-in (opens your browser, catches the redirect locally)
    whoami             show the Etsy user id and shop id the saved token belongs to
    watch              poll for new paid orders every N minutes and build each pack
    fetch --once       do one poll and stop
    parse TEXT         show how a personalisation text would be parsed (no Etsy needed)
    forget RECEIPT_ID  let a receipt be processed again on the next poll

Add `--dry-run FIXTURE.json` to watch/fetch to read receipts from a local file (fully offline).

Etsy Open API v3 facts this module relies on, and where they were checked (October 2026)
------------------------------------------------------------------------------------------
developers.etsy.com could not be fetched from the build container (DNS blocked), so the
facts below were checked against Etsy's own OpenAPI spec (as mirrored from
https://www.etsy.com/openapi/generated/oas/3.0.0.json, `x-last-validated: 2026-05-30`, copy at
https://github.com/api-evangelist/etsy/blob/main/openapi/_original/etsy-openapi-original.yml),
Etsy's GitHub announcement, search-engine extracts of the official docs pages, and the
`etsyv3` client on PyPI. Re-check the official pages when you set this up:

  https://developers.etsy.com/documentation/essentials/authentication
  https://developers.etsy.com/documentation/essentials/requests
  https://developers.etsy.com/documentation/essentials/rate-limits
  https://developers.etsy.com/documentation/reference#operation/getShopReceipts
  https://github.com/etsy/open-api/discussions/1529   (x-api-key change)
  https://pypi.org/project/etsyv3/                     (reference client: PKCE + token URLs)

* Authorize URL: https://www.etsy.com/oauth/connect with response_type=code, client_id
  (= keystring), redirect_uri, scope (space separated), state, code_challenge and
  code_challenge_method=S256. PKCE is mandatory; Etsy has no client-secret flow.
* Token URL: POST https://api.etsy.com/v3/public/oauth/token, form-encoded
  (application/x-www-form-urlencoded). Code exchange: grant_type=authorization_code,
  client_id, redirect_uri (must exactly match the one used to authorize and one registered
  on the app), code, code_verifier. Refresh: grant_type=refresh_token, client_id,
  refresh_token. (The spec's securitySchemes lists openapi.etsy.com for the token URL; the
  docs and live clients use api.etsy.com. We use api.etsy.com.)
* Lifetimes: access token expires_in 3600 s (1 hour); refresh token about 90 days.
  Refreshing returns a new refresh token, which we save straight away.
* The access token is "<numeric user id>.<token>": the prefix is the Etsy user_id.
* x-api-key header: "keystring:shared_secret" on every request. Etsy announced on
  2 February 2026 that from 9 February 2026 requests without the shared secret are rejected
  (discussion #1529; the spec's api_key description says the same).
* Scopes: getShopReceipts / getShopReceipt / getShopReceiptTransactionsByReceipt need
  `transactions_r`; GET /v3/application/users/me (returns user_id and shop_id) needs
  `shops_r`. Those two are all we request.
* Shop id: GET https://api.etsy.com/v3/application/users/me -> {"user_id", "shop_id"}.
  (Alternative: GET /v3/application/users/{user_id}/shops.)
* Receipts: GET https://api.etsy.com/v3/application/shops/{shop_id}/receipts with
  was_paid=true, was_shipped=false, was_canceled=false, min_created (unix seconds),
  sort_on=created, sort_order=asc, limit (max 100), offset. Response {"count", "results"};
  each ShopReceipt has receipt_id, status ("paid", "completed", "open",
  "payment processing", "canceled"), is_paid, is_shipped, created_timestamp,
  message_from_buyer, country_iso and a `transactions` array.
* Personalisation: each ShopReceiptTransaction has `variations`, an array of
  {property_id, value_id, formatted_name, formatted_value, question_id}. The spec calls it
  "Array of variations and personalizations the buyer chose"; formatted_value is "Value of the
  variation entered by the buyer" and question_id is "[Personalization only]". Listings with
  the newer multi-question personalisation give one entry per question.
* Rate limits: per app, per second and per day; a 429 response carries retry-after.

Could not verify: the exact formatted_name Etsy uses for classic single-box personalisation
(we match "personali..." case-insensitively, or any entry with question_id), and whether
formatted_value is HTML-escaped (we unescape it to be safe).
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import html
import json
import logging
import os
import re
import secrets
import smtplib
import stat
import sys
import time
import traceback
import urllib.parse
from dataclasses import asdict, dataclass, field
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Callable, Iterable

import requests

log = logging.getLogger("skysoftly.etsy")

AUTHORIZE_URL = "https://www.etsy.com/oauth/connect"
TOKEN_URL = "https://api.etsy.com/v3/public/oauth/token"
API_BASE = "https://api.etsy.com/v3/application"
SCOPES = ("transactions_r", "shops_r")
DEFAULT_REDIRECT_URI = "http://localhost:3003/callback"
REFRESH_TOKEN_DAYS = 90
DEFAULT_OUT = Path("output/orders")
DRY_RUN_OUT = Path("output/orders-dry-run")


class EtsyError(Exception):
    """Something went wrong talking to Etsy."""


class AuthError(EtsyError):
    """No usable token: run `python -m skysoftly.etsy login`."""


class RateLimited(EtsyError):
    """Etsy kept answering 429."""


# ---------------------------------------------------------------- config and token storage

def config_dir() -> Path:
    return Path(os.environ.get("SKYSOFTLY_CONFIG_DIR") or Path.home() / ".config" / "skysoftly")


@dataclass
class EtsyConfig:
    keystring: str
    shared_secret: str
    redirect_uri: str = DEFAULT_REDIRECT_URI
    shop_id: int | None = None

    @property
    def api_key_header(self) -> str:
        return f"{self.keystring}:{self.shared_secret}"

    def __repr__(self):  # never print the secret
        return f"EtsyConfig(keystring={self.keystring[:4]}..., redirect_uri={self.redirect_uri!r}, shop_id={self.shop_id})"


def load_config(path: Path | None = None) -> EtsyConfig:
    """Environment variables win; otherwise ~/.config/skysoftly/etsy.json."""
    path = path or config_dir() / "etsy.json"
    data: dict = {}
    if path.exists():
        _warn_if_readable_by_others(path)
        data = json.loads(path.read_text())
    keystring = os.environ.get("ETSY_KEYSTRING") or data.get("keystring")
    secret = os.environ.get("ETSY_SHARED_SECRET") or data.get("shared_secret")
    if not keystring or not secret:
        raise SystemExit(
            f"Etsy keystring and shared secret are missing. Set ETSY_KEYSTRING and ETSY_SHARED_SECRET, "
            f"or put them in {path} (see docs/ETSY-SETUP.md).")
    shop = os.environ.get("ETSY_SHOP_ID") or data.get("shop_id")
    return EtsyConfig(keystring=keystring.strip(), shared_secret=secret.strip(),
                      redirect_uri=(os.environ.get("ETSY_REDIRECT_URI") or data.get("redirect_uri") or DEFAULT_REDIRECT_URI).strip(),
                      shop_id=int(shop) if shop else None)


def _warn_if_readable_by_others(path: Path):
    try:
        if os.name == "posix" and path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            log.warning("%s can be read by other users. Run: chmod 600 %s", path, path)
    except OSError:
        pass


def write_private(path: Path, text: str):
    """Write a file only the current user can read (mode 600), atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def user_id_from_token(access_token: str) -> int | None:
    """Etsy access tokens look like '12345678.abcdef...': the prefix is the user id."""
    head = access_token.split(".", 1)[0]
    return int(head) if head.isdigit() else None


class TokenStore:
    def __init__(self, path: Path | None = None):
        self.path = path or config_dir() / "etsy_token.json"

    def load(self) -> dict | None:
        if not self.path.exists():
            return None
        return json.loads(self.path.read_text())

    def save(self, token_response: dict, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        tok = {
            "access_token": token_response["access_token"],
            "refresh_token": token_response["refresh_token"],
            "token_type": token_response.get("token_type", "Bearer"),
            "expires_at": now + int(token_response.get("expires_in", 3600)),
            "refresh_expires_at": now + REFRESH_TOKEN_DAYS * 86400,
            "user_id": user_id_from_token(token_response["access_token"]),
            "scope": " ".join(SCOPES),
            "saved_at": dt.datetime.fromtimestamp(now, dt.timezone.utc).isoformat(timespec="seconds"),
        }
        write_private(self.path, json.dumps(tok, indent=1))
        return tok


# ---------------------------------------------------------------- OAuth 2.0 with PKCE

_VERIFIER_CHARS = re.compile(r"^[A-Za-z0-9\-._~]{43,128}$")


def make_code_verifier(n_bytes: int = 48) -> str:
    """RFC 7636: 43 to 128 characters from [A-Z a-z 0-9 - . _ ~]. 48 random bytes give 64 characters."""
    v = secrets.token_urlsafe(n_bytes)
    assert _VERIFIER_CHARS.match(v)
    return v


def code_challenge(verifier: str) -> str:
    """S256: BASE64URL(SHA256(verifier)) with the '=' padding removed."""
    if not _VERIFIER_CHARS.match(verifier):
        raise ValueError("PKCE code verifier must be 43 to 128 unreserved characters")
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")


def authorize_url(cfg: EtsyConfig, state: str, challenge: str, scopes: Iterable[str] = SCOPES) -> str:
    q = {"response_type": "code", "client_id": cfg.keystring, "redirect_uri": cfg.redirect_uri,
         "scope": " ".join(scopes), "state": state, "code_challenge": challenge, "code_challenge_method": "S256"}
    return AUTHORIZE_URL + "?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote)


def _token_request(cfg: EtsyConfig, form: dict) -> dict:
    try:
        r = requests.request("POST", TOKEN_URL, data=form, timeout=30,
                             headers={"Accept": "application/json", "x-api-key": cfg.api_key_header})
    except requests.RequestException as e:
        raise EtsyError(f"Could not reach Etsy's token endpoint: {e.__class__.__name__}") from None
    if r.status_code != 200:
        try:
            err = r.json()
            detail = f"{err.get('error', '')} {err.get('error_description', '')}".strip()
        except ValueError:
            detail = r.text[:200]
        cls = AuthError if r.status_code in (400, 401) else EtsyError
        raise cls(f"Etsy token request failed ({r.status_code}): {detail}. "
                  + ("Run `python -m skysoftly.etsy login` again." if cls is AuthError else ""))
    data = r.json()
    if "access_token" not in data or "refresh_token" not in data:
        raise EtsyError("Etsy's token response was missing access_token or refresh_token")
    return data


def exchange_code(cfg: EtsyConfig, code: str, verifier: str) -> dict:
    return _token_request(cfg, {"grant_type": "authorization_code", "client_id": cfg.keystring,
                                "redirect_uri": cfg.redirect_uri, "code": code, "code_verifier": verifier})


def refresh_tokens(cfg: EtsyConfig, refresh_token: str) -> dict:
    return _token_request(cfg, {"grant_type": "refresh_token", "client_id": cfg.keystring,
                                "refresh_token": refresh_token})


def parse_callback(url_or_query: str, expected_state: str) -> str:
    """Pull the code out of the redirect, after checking state. Raises AuthError on any mismatch."""
    query = urllib.parse.urlsplit(url_or_query).query if "?" in url_or_query else url_or_query
    q = urllib.parse.parse_qs(query)
    if "error" in q:
        raise AuthError(f"Etsy said: {q['error'][0]} {q.get('error_description', [''])[0]}".strip())
    state = q.get("state", [""])[0]
    if not state or not secrets.compare_digest(state, expected_state):
        raise AuthError("The state value in the redirect did not match. Nothing was saved; run login again.")
    code = q.get("code", [""])[0]
    if not code:
        raise AuthError("The redirect had no authorisation code.")
    return code


class _CallbackServer(HTTPServer):
    allow_reuse_address = True

    def __init__(self, addr, path: str, state: str):
        super().__init__(addr, _CallbackHandler)
        self.expected_path, self.expected_state = path, state
        self.code: str | None = None
        self.error: str | None = None


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        srv: _CallbackServer = self.server  # type: ignore[assignment]
        parts = urllib.parse.urlsplit(self.path)
        if parts.path != srv.expected_path:
            self.send_response(404); self.end_headers()
            return
        try:
            srv.code = parse_callback(parts.query, srv.expected_state)
            body, status = "<h2>Signed in to Etsy.</h2><p>You can close this tab and go back to the terminal.</p>", 200
        except AuthError as e:
            srv.error = str(e)
            body, status = f"<h2>Sign-in failed</h2><p>{html.escape(str(e))}</p>", 400
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *args):  # keep the code out of logs
        pass


def wait_for_callback(redirect_uri: str, state: str, timeout: float = 300.0,
                      on_ready: Callable[[], None] | None = None) -> str:
    """One-shot local HTTP server on the redirect URI. Returns the code once state checks out."""
    u = urllib.parse.urlsplit(redirect_uri)
    if u.scheme != "http" or u.hostname not in ("localhost", "127.0.0.1"):
        raise SystemExit(f"The redirect URI {redirect_uri} is not a local http address. Use --paste instead.")
    srv = _CallbackServer((u.hostname, u.port or 80), u.path or "/", state)
    srv.timeout = 1.0
    try:
        if on_ready:
            on_ready()
        deadline = time.monotonic() + timeout
        while srv.code is None and srv.error is None:
            if time.monotonic() > deadline:
                raise AuthError("Timed out waiting for Etsy to redirect back. Run login again.")
            srv.handle_request()
    finally:
        srv.server_close()
    if srv.error:
        raise AuthError(srv.error)
    return srv.code  # type: ignore[return-value]


def login(cfg: EtsyConfig, store: TokenStore, open_browser: bool = True, paste: bool = False,
          timeout: float = 300.0) -> dict:
    verifier = make_code_verifier()
    state = secrets.token_urlsafe(24)
    url = authorize_url(cfg, state, code_challenge(verifier))
    if paste:
        print("Open this link, approve, then paste the full address your browser lands on:\n\n" + url + "\n")
        code = parse_callback(input("Redirected address: ").strip(), state)
    else:
        def ready():
            print("Opening Etsy in your browser. If nothing opens, visit:\n\n" + url + "\n")
            if open_browser:
                import webbrowser
                webbrowser.open(url)
        code = wait_for_callback(cfg.redirect_uri, state, timeout, on_ready=ready)
    tok = store.save(exchange_code(cfg, code, verifier))
    print(f"Signed in. Token saved to {store.path} (only you can read it).")
    return tok


# ---------------------------------------------------------------- API client

class EtsyClient:
    def __init__(self, cfg: EtsyConfig, store: TokenStore | None = None, sleep: Callable[[float], None] = time.sleep,
                 max_retries: int = 5):
        self.cfg, self.store, self.sleep, self.max_retries = cfg, store or TokenStore(), sleep, max_retries

    def access_token(self, force_refresh: bool = False) -> str:
        tok = self.store.load()
        if not tok:
            raise AuthError("Not signed in to Etsy. Run `python -m skysoftly.etsy login`.")
        if force_refresh or time.time() > tok.get("expires_at", 0) - 60:
            if time.time() > tok.get("refresh_expires_at", float("inf")):
                raise AuthError("The Etsy sign-in is older than 90 days. Run `python -m skysoftly.etsy login`.")
            log.info("Refreshing the Etsy access token")
            tok = self.store.save(refresh_tokens(self.cfg, tok["refresh_token"]))
        return tok["access_token"]

    def get(self, path: str, params: dict | None = None) -> dict:
        url = API_BASE + path
        refreshed = False
        for attempt in range(self.max_retries + 1):
            headers = {"x-api-key": self.cfg.api_key_header, "Authorization": f"Bearer {self.access_token()}",
                       "Accept": "application/json"}
            try:
                r = requests.request("GET", url, params=params, headers=headers, timeout=30)
            except requests.RequestException as e:
                if attempt == self.max_retries:
                    raise EtsyError(f"Network error calling Etsy: {e.__class__.__name__}") from None
                self.sleep(_backoff(attempt))
                continue
            if r.status_code == 401 and not refreshed:
                refreshed = True
                self.access_token(force_refresh=True)
                continue
            if r.status_code == 429 or r.status_code >= 500:
                if attempt == self.max_retries:
                    raise (RateLimited if r.status_code == 429 else EtsyError)(
                        f"Etsy answered {r.status_code} {self.max_retries + 1} times for {path}")
                wait = _retry_after(r.headers.get("retry-after")) if r.status_code == 429 else None
                wait = max(wait or 0, _backoff(attempt))
                log.warning("Etsy answered %s; waiting %.0fs before retrying", r.status_code, wait)
                self.sleep(wait)
                continue
            if r.status_code >= 400:
                try:
                    msg = r.json().get("error", "")
                except ValueError:
                    msg = r.text[:200]
                if r.status_code in (401, 403):
                    raise AuthError(f"Etsy refused access ({r.status_code}): {msg}")
                raise EtsyError(f"Etsy answered {r.status_code} for {path}: {msg}")
            return r.json()
        raise EtsyError("unreachable")

    def get_me(self) -> dict:
        return self.get("/users/me")

    def shop_id(self) -> int:
        if self.cfg.shop_id:
            return self.cfg.shop_id
        sid = self.get_me().get("shop_id")
        if not sid:
            raise EtsyError("This Etsy account has no shop.")
        self.cfg.shop_id = int(sid)
        return self.cfg.shop_id

    def paid_unshipped_receipts(self, min_created: int | None = None, page_size: int = 100) -> list[dict]:
        shop = self.shop_id()
        out, offset = [], 0
        while True:
            params = {"was_paid": "true", "was_shipped": "false", "was_canceled": "false", "sort_on": "created",
                      "sort_order": "asc", "limit": page_size, "offset": offset}
            if min_created:
                params["min_created"] = int(min_created)
            page = self.get(f"/shops/{shop}/receipts", params)
            results = page.get("results") or []
            out.extend(results)
            offset += len(results)
            if not results or len(results) < page_size or offset >= int(page.get("count", 0)):
                break
        for rec in out:  # receipts normally embed transactions; fetch them if not
            if not rec.get("transactions"):
                rec["transactions"] = self.get(f"/shops/{shop}/receipts/{rec['receipt_id']}/transactions").get("results", [])
        return out


def _backoff(attempt: int) -> float:
    return min(60.0, 2.0 ** attempt)


def _retry_after(value: str | None) -> float | None:
    try:
        return max(0.0, float(value)) if value is not None else None
    except ValueError:
        return None


# ---------------------------------------------------------------- personalisation parser

@dataclass
class StoryFields:
    name: str | None = None
    pronoun: str | None = None
    age: int | None = None
    any_night: bool = False
    animal: str | None = None
    colour: str | None = None
    born: dt.date | None = None
    city: str | None = None
    country: str | None = None
    giver: str | None = None
    message: str | None = None
    pronunciation: str | None = None
    lat: float | None = None   # the exact town we checked, so the story command can't pick a different one
    lon: float | None = None
    tz: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["born"] = self.born.isoformat() if self.born else None
        return d

    def story_argv(self, out_dir: Path, video: bool = False, no_audio: bool = False, blanks: bool = False) -> list[str]:
        """Arguments for `python -m skysoftly story ...`. With blanks=True, missing answers show as NAME? etc."""
        def val(v, ph):
            return v if v else (ph if blanks else None)
        a = ["story", "--name", val(self.name, "NAME?") or "", "--pronoun", val(self.pronoun, "she|he|they?") or "they"]
        if self.age or (blanks and not self.any_night):
            a += ["--age", str(self.age) if self.age else "AGE?"]
        for flag, v, ph in (("--animal", self.animal, "ANIMAL?"), ("--colour", self.colour, "COLOUR?"),
                            ("--from", self.giver, "FROM?"), ("--message", self.message, "MESSAGE?")):
            if val(v, ph):
                a += [flag, val(v, ph)]
        if self.born and self.city:
            a += ["--born", self.born.isoformat()]
            if self.lat is not None and self.lon is not None and self.tz:
                a += ["--lat", f"{self.lat:.5f}", "--lon", f"{self.lon:.5f}", "--tz", self.tz, "--place-name", self.city]
            else:
                a += ["--city", self.city]
            if self.country:
                a += ["--country", self.country]
        a += ["--out", str(out_dir)]
        if video:
            a.append("--video")
        if no_audio:
            a.append("--no-audio")
        return a


@dataclass
class ParseResult:
    fields: StoryFields
    problems: list[str] = field(default_factory=list)   # any problem sends the order to needs-review
    notes: list[str] = field(default_factory=list)      # worth a glance, but not blocking

    @property
    def ok(self) -> bool:
        return not self.problems


FIELDS = ("name", "pronoun", "age", "animal", "colour", "born_town", "giver", "message")

LABELS = {  # how buyers (or Etsy's multi-question personalisation) label each answer
    "name": r"(?:the\s+)?(?:child['’]?s?|kid['’]?s?|baby['’]?s?)?\s*(?:first\s+)?name",
    "pronoun": r"pronouns?|she,?\s*he,?\s*(?:or\s+)?they|she\s*/\s*he\s*/\s*they|he\s*/\s*she(?:\s*/\s*they)?|gender",
    "age": r"age(?:\s+(?:they['’]?re|they\s+are|he['’]?s|she['’]?s)\s+turning)?(?:\s*\(.*?\))?|turning|how\s+old",
    "animal": r"(?:favou?rite\s+)?animal",
    "colour": r"(?:favou?rite\s+)?colou?r",
    "born_town": r"(?:birth\s*(?:date|day)?(?:\s+(?:and|&)\s+(?:town|place|city))?(?:\s*\(.*?\))?|date\s+of\s+birth|d\.?o\.?b\.?|born|"
                 r"place\s+of\s+birth|birth\s*place|town)",
    "giver": r"(?:who\s+(?:it['’]?s|it\s+is|is\s+it|the\s+gift\s+is)\s+from|from|giver|gift\s+from|sender)",
    "message": r"(?:a\s+)?(?:short\s+)?message(?:\s+for\s+the\s+star(?:\s+to\s+read)?)?(?:\s*\(.*?\))?",
}

PRONOUNS = {"she": "she", "her": "she", "girl": "she", "he": "he", "him": "he", "boy": "he", "they": "they", "them": "they"}
NUMBER_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen "
    "eighteen nineteen twenty".split())}
ORDINAL_WORDS = {w: i + 1 for i, w in enumerate(
    "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth fifteenth "
    "sixteenth seventeenth eighteenth nineteenth twentieth".split())}
ANY_NIGHT = re.compile(r"^\W*(?:any\s*night|any|anynight|n/?a|none|no|not\s+a\s+birthday|no\s+birthday|bedtime|just\s+bedtime|-+)\W*$", re.I)
SKIP = re.compile(r"^\W*(?:n/?a|none|no|skip|-+|prefer\s+not(?:\s+to\s+say)?|not\s+sure|optional|no\s+thanks?|x)?\W*$", re.I)

# Colour words skysoftly.story.COLOUR_WORDS understands (copied so parsing never depends on render code).
KNOWN_COLOURS = {"purple", "lilac", "lavender", "violet", "pink", "red", "rose", "orange", "gold", "yellow", "brown",
                 "green", "blue", "teal", "turquoise"}
COLOUR_ALIASES = {"purpley": "purple", "mauve": "lilac", "magenta": "pink", "golden": "gold", "navy": "blue",
                  "aqua": "turquoise", "mint": "green", "emerald": "green", "scarlet": "red", "crimson": "red",
                  "sky blue": "blue", "light blue": "blue", "dark blue": "blue", "baby pink": "pink", "hot pink": "pink",
                  "light pink": "pink", "pale pink": "pink", "lime": "green", "peach": "orange"}
# Animals with their own starlight drawing in skysoftly.scenes; others still work in the story text.
DRAWN_ANIMALS = {"bunny", "rabbit", "fox", "cat", "kitten", "bear", "owl", "elephant", "dog"}

MONTHS = {m: i + 1 for i, m in enumerate(
    "january february march april may june july august september october november december".split())}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})
MONTHS["sept"] = 9
_MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"

COUNTRY_ALIASES = {
    "uk": "GB", "u.k.": "GB", "u.k": "GB", "united kingdom": "GB", "great britain": "GB", "britain": "GB", "gb": "GB",
    "england": "GB", "scotland": "GB", "wales": "GB", "northern ireland": "GB",
    "us": "US", "u.s.": "US", "usa": "US", "u.s.a.": "US", "united states": "US", "united states of america": "US",
    "america": "US", "ireland": "IE", "republic of ireland": "IE", "eire": "IE", "nz": "NZ", "uae": "AE",
}
US_STATE_CODES = {name: code for code, name in (pair.split(":") for pair in (
    "AL:alabama AK:alaska AZ:arizona AR:arkansas CA:california CO:colorado CT:connecticut DE:delaware FL:florida "
    "GA:georgia HI:hawaii ID:idaho IL:illinois IN:indiana IA:iowa KS:kansas KY:kentucky LA:louisiana ME:maine "
    "MD:maryland MA:massachusetts MI:michigan MN:minnesota MS:mississippi MO:missouri MT:montana NE:nebraska NV:nevada "
    "NH:new_hampshire NJ:new_jersey NM:new_mexico NY:new_york NC:north_carolina ND:north_dakota OH:ohio OK:oklahoma "
    "OR:oregon PA:pennsylvania RI:rhode_island SC:south_carolina SD:south_dakota TN:tennessee TX:texas UT:utah "
    "VT:vermont VA:virginia WA:washington WV:west_virginia WI:wisconsin WY:wyoming DC:district_of_columbia").split())}
US_STATE_CODES = {k.replace("_", " "): v for k, v in US_STATE_CODES.items()}
US_STATE_CODES.update({v.lower(): v for v in list(US_STATE_CODES.values())})
US_STATES = set(US_STATE_CODES)
UK_REGIONS = {"west yorkshire", "south yorkshire", "north yorkshire", "east yorkshire", "yorkshire", "lancashire", "kent",
              "essex", "surrey", "devon", "cornwall", "cumbria", "merseyside", "greater manchester", "west midlands",
              "county durham", "durham", "norfolk", "suffolk", "hampshire", "sussex", "east sussex", "west sussex"}

@dataclass
class Town:
    name: str
    country: str      # ISO 3166 alpha-2
    population: int
    tz: str
    lat: float
    lon: float
    admin1: str = ""  # e.g. US state code "CO"


TownLookup = Callable[[str], list]  # city -> [Town, ...] in any country


def _geonames_lookup(city: str) -> list[Town]:
    """The offline town list skysoftly.engine.find_place uses. Exact name matches win over alternate names."""
    import geonamescache
    gc = geonamescache.GeonamesCache()
    c = city.lower()
    cands = gc.search_cities(city, case_sensitive=False)
    hits = [h for h in cands if h["name"].lower() == c] or \
        [h for h in cands if c in [a.lower() for a in h.get("alternatenames", [])]]
    return [Town(h["name"], h["countrycode"], int(h["population"]), h.get("timezone", ""), float(h["latitude"]),
                 float(h["longitude"]), h.get("admin1code", "")) for h in hits]


_country_names: dict[str, str] | None = None


def country_codes(text: str) -> set[str]:
    """Possible ISO codes for a country-ish word: 'UK' -> {GB}, 'France' -> {FR}, 'Texas' -> {US},
    'CA' -> {US, CA} (California or Canada). Empty when it isn't a country."""
    global _country_names
    t = re.sub(r"^the\s+", "", text.strip().strip(".").lower())
    if t in COUNTRY_ALIASES:
        return {COUNTRY_ALIASES[t]}
    if t in UK_REGIONS:
        return {"GB"}
    if _country_names is None:
        _country_names = {}
        try:
            import geonamescache
            for iso, c in geonamescache.GeonamesCache().get_countries().items():
                _country_names[c["name"].lower()] = iso
                _country_names[iso.lower()] = iso
        except Exception:  # pragma: no cover - geonamescache is a project dependency
            pass
    out = set()
    if t in US_STATES:
        out.add("US")
    if t in _country_names:
        out.add(_country_names[t])
    return out


def _marker(n: int, delims: str) -> re.Pattern:
    # "1)", "1.", "1:", "1 -", "(1)", "#1", "Q1:" -- but not "1.5", "1/2" or "2021"
    return re.compile(rf"(?<![^\s,;(\[])(?:#|q|no\.?\s*)?\(?{n}\s*(?:{delims})(?![\d/.])", re.I)


def split_numbered(text: str) -> dict[int, str] | None:
    """Find answers '1) ... 2) ... 8) ...'. Returns {number: answer}, or None if it isn't numbered."""
    first = None
    for delims in (r"\)", r"\.", r":", r"\s-|-|–"):
        m = _marker(1, delims).search(text)
        if m and (first is None or m.start() < first[1].start()):
            first = (delims, m)
    if not first:
        return None
    style = first[0]
    marks = [(1, first[1])]
    pos = first[1].end()
    for n in range(2, 9):
        m = _marker(n, style).search(text, pos) or _marker(n, r"\)|\.|:|\s-").search(text, pos)
        if m:
            marks.append((n, m))
            pos = m.end()
    if len(marks) < 4:
        return None
    out = {}
    for i, (n, m) in enumerate(marks):
        end = marks[i + 1][1].start() if i + 1 < len(marks) else len(text)
        out[n] = text[m.end():end].strip(" \t\n\r,;")
    return out


def split_labelled(text: str) -> dict[str, str] | None:
    """Find answers 'Name: Isla, Age: 5, ...' (or one per line)."""
    hits = []
    for key, pat in LABELS.items():
        for m in re.finditer(rf"(?:^|(?<=[\n,;.]))\s*(?:\d\s*[).:]\s*)?(?:{pat})\s*[:=\-–]\s*", text, re.I):
            hits.append((m.start(), m.end(), key))
    hits.sort()
    keep, last_end = [], -1
    for h in hits:  # drop overlapping matches (e.g. "name" inside "first name")
        if h[0] >= last_end:
            keep.append(h)
            last_end = h[1]
    if len({k for _, _, k in keep}) < 3:
        return None
    out: dict[str, str] = {}
    for i, (s, e, key) in enumerate(keep):
        end = keep[i + 1][0] if i + 1 < len(keep) else len(text)
        out.setdefault(key, text[e:end].strip(" \t\n\r,;"))
    return out


def _strip_label(key: str, value: str) -> str:
    return re.sub(rf"^\s*(?:{LABELS[key]})\s*[:=\-–]\s*", "", value, flags=re.I).strip()


def parse_personalization(text: str | None, buyer_country: str | None = None, today: dt.date | None = None,
                          town_lookup: TownLookup | None = None) -> ParseResult:
    """Turn the buyer's personalisation answers into story fields.

    Never guesses: anything missing, contradictory or ambiguous goes into `problems`."""
    today = today or _today()
    f = StoryFields()
    res = ParseResult(f)
    text = html.unescape(text or "").replace("\r", "\n").strip()
    if not text:
        res.problems.append("No personalisation text on this order.")
        return res

    answers: dict[str, str] = {}
    numbered = split_numbered(text)
    if numbered:
        for n, v in numbered.items():
            answers[FIELDS[n - 1]] = _strip_label(FIELDS[n - 1], v)
        missing = [n for n in range(1, 9) if n not in numbered]
        for n in missing:
            if n != 6:
                res.problems.append(f"Answer {n} ({FIELDS[n - 1].replace('_', ' ')}) is missing from the numbered list.")
    else:
        labelled = split_labelled(text)
        if labelled:
            answers = labelled
        else:
            lines = [ln.strip(" -•*\t") for ln in text.split("\n") if ln.strip(" -•*\t")]
            if len(lines) == 8:
                answers = dict(zip(FIELDS, lines))
                res.notes.append("Answers were not numbered; read them one per line, in the listing's order.")
            else:
                res.problems.append("Could not find the numbered answers 1) to 8). Please read the text and fill in the order by hand.")
                return res

    _parse_name(answers.get("name"), f, res)
    _parse_pronoun(answers.get("pronoun"), f, res)
    _parse_age(answers.get("age"), f, res)
    _parse_animal(answers.get("animal"), f, res)
    _parse_colour(answers.get("colour"), f, res)
    _parse_born_town(answers.get("born_town"), f, res, buyer_country, today, town_lookup or _geonames_lookup)
    _parse_giver(answers.get("giver"), f, res)
    _parse_message(answers.get("message"), f, res)
    if f.born and f.age and not f.any_night:
        turning = today.year - f.born.year + (0 if (today.month, today.day) <= (f.born.month, f.born.day) else 1)
        if abs(turning - f.age) > 1:
            res.problems.append(f"Age {f.age} does not match the birth date {f.born:%d %B %Y} (they would be turning {turning}).")
    return res


def _today() -> dt.date:
    return dt.date.today()


def _clean(v: str | None) -> str:
    return re.sub(r"\s+", " ", (v or "")).strip().strip("\"'“”‘’").strip(" .,;!")


def _parse_name(v, f: StoryFields, res: ParseResult):
    v = _clean(v)
    m = re.search(r"\((?:pronounced|say|said|sounds like)?:?\s*([^)]*)\)", v, re.I) or \
        re.search(r"[,-]?\s*(?:pronounced|sounds like)\s*:?\s*(.+)$", v, re.I)
    if m:
        f.pronunciation = m.group(1).strip()
        v = _clean(v[:m.start()])
        res.notes.append(f"Buyer says the name is pronounced '{f.pronunciation}'. Listen carefully; spell it that way in --name for the audio if needed.")
    if not v:
        res.problems.append("Child's first name is missing.")
        return
    if re.search(r"[^\w\s'’\-.]", v) or re.search(r"\d", v) or len(v.split()) > 3:
        res.problems.append(f"Child's name '{v}' doesn't look like a first name.")
        return
    if v.islower() or v.isupper():
        v = " ".join(w[:1].upper() + w[1:].lower() for w in v.split())
        res.notes.append(f"Capitalised the name as '{v}'.")
    f.name = v
    if len(v.split()) > 1:
        res.notes.append(f"The name has more than one word ('{v}'). Check that's what they want read out.")


def _parse_pronoun(v, f: StoryFields, res: ParseResult):
    words = set(re.findall(r"[a-z]+", (v or "").lower()))
    found = {PRONOUNS[w] for w in words if w in PRONOUNS}
    if not found:
        res.problems.append(f"Pronoun (she, he or they) is missing or unclear: '{_clean(v)}'.")
    elif len(found) > 1:
        res.problems.append(f"More than one pronoun given ('{_clean(v)}'); not guessing.")
    else:
        f.pronoun = found.pop()


def _parse_age(v, f: StoryFields, res: ParseResult):
    v = _clean(v)
    if not v:
        res.problems.append("Age (or 'any night') is missing.")
        return
    if ANY_NIGHT.match(v) or re.search(r"\bany\s*night\b", v, re.I):
        f.any_night = True
        return
    low = v.lower()
    nums = [int(n) for n in re.findall(r"\b(\d{1,3})(?:st|nd|rd|th)?\b", low)]
    nums += [NUMBER_WORDS[w] for w in re.findall(r"[a-z]+", low) if w in NUMBER_WORDS]
    nums += [ORDINAL_WORDS[w] for w in re.findall(r"[a-z]+", low) if w in ORDINAL_WORDS]
    nums = sorted(set(nums))
    if len(nums) != 1:
        res.problems.append(f"Age '{v}' is unclear; expected one number or 'any night'.")
        return
    if re.search(r"\b(?:months?|weeks?|half)\b", low):
        res.problems.append(f"Age '{v}' mentions months or halves; the story counts whole birthdays.")
        return
    age = nums[0]
    if not 1 <= age <= 16:
        res.problems.append(f"Age {age} is outside 1 to 16; please check.")
        return
    f.age = age


def _parse_animal(v, f: StoryFields, res: ParseResult):
    v = re.sub(r"^(?:a|an|the|my|her|his|their)\s+", "", _clean(v).lower())
    if not v:
        res.problems.append("Favourite animal is missing.")
        return
    if len(v.split()) > 3 or re.search(r"\b(?:and|or)\b|[,/&]", v):
        res.problems.append(f"Favourite animal '{v}' is more than one animal; the story needs one.")
        return
    f.animal = v
    if v.split()[-1] not in DRAWN_ANIMALS:
        res.notes.append(f"'{v}' has no starlight drawing yet; the story text will use it, pictures may show a fox.")


def _parse_colour(v, f: StoryFields, res: ParseResult):
    v = _clean(v).lower()
    if not v:
        res.problems.append("Favourite colour is missing.")
        return
    if v in COLOUR_ALIASES:
        f.colour = COLOUR_ALIASES[v]
        return
    found = [w for w in re.findall(r"[a-z]+", v) if w in KNOWN_COLOURS or w in COLOUR_ALIASES]
    found = sorted({COLOUR_ALIASES.get(w, w) for w in found})
    if len(found) == 1:
        f.colour = found[0]
        if v != found[0]:
            res.notes.append(f"Colour '{v}' read as '{found[0]}'.")
    elif not found:
        res.problems.append(f"Colour '{v}' isn't one the nebula knows (purple, pink, red, gold, yellow, orange, green, blue...).")
    else:
        res.problems.append(f"Colour '{v}' names several colours ({', '.join(found)}); pick one.")


def _year(y: str, res: ParseResult, today: dt.date) -> int:
    if len(y) == 4:
        return int(y)
    yy = int(y)
    full = 2000 + yy if 2000 + yy <= today.year else 1900 + yy
    res.notes.append(f"Two-digit year '{y}' read as {full}.")
    return full


def find_date(text: str, res: ParseResult, buyer_country: str | None, today: dt.date) -> tuple[dt.date | None, str]:
    """Find one date in the text. Returns (date, text with the date removed)."""
    t = text
    found: list[tuple[dt.date | None, tuple[int, int]]] = []

    def add(build, m):
        try:
            found.append((build(), m.span()))
        except ValueError:
            found.append((None, m.span()))
            res.problems.append(f"'{m.group(0)}' is not a real date.")

    for m in re.finditer(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t):
        add(lambda m=m: dt.date(int(m[1]), int(m[2]), int(m[3])), m)
    for m in re.finditer(r"(?<![\d-])(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})(?![\d-])", t):
        a, b = int(m[1]), int(m[2])
        if b > 12 and a <= 12:  # clearly month-first (US style)
            res.notes.append(f"'{m.group(0)}' can only be month/day; read as {MONTH_NAMES[a]} {b}.")
            day, mon = b, a
        else:  # UK day-first
            day, mon = a, b
            if a <= 12 and b <= 12 and a != b and (buyer_country or "").upper() == "US":
                res.problems.append(f"Date '{m.group(0)}' could be day/month or month/day, and the buyer is in the US.")
        add(lambda m=m, day=day, mon=mon: dt.date(_year(m[3], res, today), mon, day), m)
    for m in re.finditer(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{_MON}\.?,?\s+(\d{{4}})\b", t, re.I):
        add(lambda m=m: dt.date(int(m[3]), MONTHS[m[2].lower()[:3]], int(m[1])), m)
    for m in re.finditer(rf"\b{_MON}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", t, re.I):
        if any(s[0] <= m.start() < s[1] for _, s in found):
            continue
        add(lambda m=m: dt.date(int(m[3]), MONTHS[m[1].lower()[:3]], int(m[2])), m)
    # de-duplicate overlapping matches (e.g. "2 May 2021" vs "May 2021")
    found.sort(key=lambda x: x[1])
    uniq: list[tuple[dt.date | None, tuple[int, int]]] = []
    for d, span in found:
        if uniq and span[0] < uniq[-1][1][1]:
            continue
        uniq.append((d, span))
    if not uniq:
        return None, t
    if len(uniq) > 1:
        res.problems.append("More than one date in the birth date answer.")
    d, (s, e) = uniq[0]
    rest = (t[:s] + " " + t[e:]).strip()
    if d and d > today:
        res.problems.append(f"Birth date {d:%d %B %Y} is in the future.")
        d = None
    elif d and (today - d).days > 18 * 366:
        res.notes.append(f"Birth date {d:%d %B %Y} is more than 18 years ago; fine for a grown-up gift, but check.")
    return d, rest


MONTH_NAMES = {i + 1: m.capitalize() for i, m in enumerate(
    "january february march april may june july august september october november december".split())}


def _parse_born_town(v, f: StoryFields, res: ParseResult, buyer_country, today, lookup: TownLookup):
    v = _clean(v)
    if not v or SKIP.match(v):
        return  # optional
    has_digits = bool(re.search(r"\d", v))
    date, rest = find_date(v, res, buyer_country, today)
    if date is None and has_digits and not any("date" in p for p in res.problems):
        res.problems.append(f"Couldn't read a birth date in '{v}'. Use a form like 2 May 2021 or 2021-05-02.")
        return
    place = re.sub(r"\b(?:born|in|at|on|the|town|city|of|was|and|&|near|hospital)\b", " ", rest, flags=re.I)
    place = re.sub(r"\s+", " ", place).strip(" ,.;:-–()")
    place = re.sub(r"\s*,\s*", ", ", place)
    if date and not place:
        res.problems.append("Birth date given but no town, so the real sky can't be worked out.")
        return
    if place and not date:
        res.problems.append(f"Town '{place}' given without a birth date.")
        return
    if not date:
        return
    parts = [p.strip() for p in place.split(",") if p.strip()]
    city = parts[0] if parts else ""
    if not city:
        res.problems.append(f"Couldn't read the town in '{place}'.")
        return
    cands: set[str] = set()
    state = None
    for extra in reversed(parts[1:]):  # "Leeds, West Yorkshire, UK": the last recognisable part wins
        cands = country_codes(extra)
        if cands:
            break
    for extra in parts[1:]:  # "Boulder, CO" or "Austin, Texas, USA"
        st = US_STATE_CODES.get(extra.strip(" .").lower())
        if st:
            state = st
    try:
        hits = lookup(city)
        if not hits and " " in city:  # "Leeds UK" with no comma
            head, tail = city.rsplit(" ", 1)
            if country_codes(tail):
                city, cands = head, country_codes(tail)
                hits = lookup(city)
    except Exception as e:  # pragma: no cover - lookup failure is a review case, not a crash
        res.problems.append(f"Couldn't check the town '{city}' ({e.__class__.__name__}).")
        return
    if cands:
        hits = [h for h in hits if h.country in cands]
    if state and any(h.country == "US" and h.admin1 == state for h in hits):
        hits = [h for h in hits if h.country != "US" or h.admin1 == state]
    if not hits:
        res.problems.append(f"Town '{city}'{' in ' + '/'.join(sorted(cands)) if cands else ''} isn't in the offline town "
                            f"list (towns over 15,000 people). Use the nearest big town, or --lat --lon --tz.")
        return
    countries = sorted({h.country for h in hits})
    biggest = max(hits, key=lambda h: h.population)
    if len(countries) == 1:
        country = countries[0]
    elif not cands and buyer_country and buyer_country.upper() == biggest.country:
        country = biggest.country
        res.notes.append(f"'{city}' exists in {', '.join(countries)}; chose {country} (the buyer's country, and the biggest).")
    else:
        res.problems.append(f"Town '{city}' exists in several countries ({', '.join(countries)}); which one?")
        return
    same = [h for h in hits if h.country == country]
    if len({h.tz for h in same}) > 1:
        res.problems.append(f"There are several towns called '{city}' in {country}, in different time zones; which one?")
        return
    top = max(same, key=lambda h: h.population)
    if len(same) > 1:
        res.notes.append(f"There is more than one '{city}' in {country}; the sky uses the biggest. Fine unless they are far apart.")
    f.born, f.city, f.country = date, top.name, country
    f.lat, f.lon, f.tz = top.lat, top.lon, top.tz


def _parse_giver(v, f: StoryFields, res: ParseResult):
    v = _clean(v)
    v2 = re.sub(r"^(?:(?:with\s+)?(?:lots\s+of\s+|all\s+our\s+|all\s+my\s+)?love\s+)?from\s+", "", v, flags=re.I).strip()
    if v2 != v:
        res.notes.append(f"Read 'who it's from' as '{v2}'.")
    if not v2:
        res.problems.append("Who the gift is from is missing.")
        return
    if len(v2) > 60:
        res.problems.append("The 'from' answer is very long; it should be a few words like 'Grandma and Grandpa'.")
        return
    f.giver = v2


def _parse_message(v, f: StoryFields, res: ParseResult):
    v = re.sub(r"\s+", " ", (v or "")).strip().strip("\"“”")
    if not v or SKIP.match(v):
        res.problems.append("The short message for the star to read is missing.")
        return
    n = len(v.split())
    if n > 40:
        res.problems.append(f"The message is {n} words; the listing allows 25. Shorten it with the buyer.")
        return
    if n > 25:
        res.notes.append(f"The message is {n} words (the listing says up to 25).")
    f.message = v


# ---------------------------------------------------------------- receipts -> order items

@dataclass
class OrderItem:
    transaction_id: int | None
    listing_id: int | None
    title: str
    quantity: int
    personalization: str | None
    other_choices: dict


def personalization_from_transaction(tx: dict) -> str | None:
    pers = [v for v in tx.get("variations") or []
            if v.get("question_id") is not None or "personali" in (v.get("formatted_name") or "").lower()]
    if not pers:
        return None
    if len(pers) == 1:
        return html.unescape(pers[0].get("formatted_value") or "")
    return "\n".join(f"{html.unescape(p.get('formatted_name') or '')}: {html.unescape(p.get('formatted_value') or '')}" for p in pers)


def order_items(receipt: dict) -> list[OrderItem]:
    items = []
    for tx in receipt.get("transactions") or []:
        others = {html.unescape(v.get("formatted_name") or ""): html.unescape(v.get("formatted_value") or "")
                  for v in tx.get("variations") or []
                  if v.get("question_id") is None and "personali" not in (v.get("formatted_name") or "").lower()}
        items.append(OrderItem(tx.get("transaction_id"), tx.get("listing_id"), html.unescape(tx.get("title") or ""),
                               int(tx.get("quantity") or 1), personalization_from_transaction(tx), others))
    return items


def is_new_paid_order(receipt: dict) -> bool:
    status = (receipt.get("status") or "").lower()
    return bool(receipt.get("is_paid")) and status not in ("completed", "canceled", "cancelled", "fully refunded") \
        and not receipt.get("is_shipped")


def load_fixture(path: Path) -> list[dict]:
    data = json.loads(Path(path).read_text())
    return data["results"] if isinstance(data, dict) else list(data)


# ---------------------------------------------------------------- processed-order state

class ProcessedState:
    """Receipt ids already handled, kept on disk so a restart never builds a pack twice."""

    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, dict] = json.loads(path.read_text()) if path.exists() else {}

    def __contains__(self, receipt_id) -> bool:
        return str(receipt_id) in self.data

    def mark(self, receipt_id, status: str, **extra):
        self.data[str(receipt_id)] = {"status": status, "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), **extra}
        self._save()

    def forget(self, receipt_id) -> bool:
        gone = self.data.pop(str(receipt_id), None) is not None
        self._save()
        return gone

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1, sort_keys=True))
        os.replace(tmp, self.path)


# ---------------------------------------------------------------- notifications

def notify(subject: str, body: str, env: dict | None = None) -> bool:
    """Email via SMTP when SMTP_HOST and SMTP_TO are set. Never raises."""
    env = os.environ if env is None else env
    host, to = env.get("SMTP_HOST"), env.get("SMTP_TO")
    if not host or not to:
        return False
    port = int(env.get("SMTP_PORT") or 587)
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, env.get("SMTP_FROM") or env.get("SMTP_USER") or to, to
    msg.set_content(body)
    try:
        if port == 465 or env.get("SMTP_SSL", "").lower() in ("1", "true", "yes"):
            s = smtplib.SMTP_SSL(host, port, timeout=30)
        else:
            s = smtplib.SMTP(host, port, timeout=30)
            if env.get("SMTP_STARTTLS", "true").lower() not in ("0", "false", "no"):
                s.starttls()
        with s:
            if env.get("SMTP_USER"):
                s.login(env["SMTP_USER"], env.get("SMTP_PASSWORD", ""))
            s.send_message(msg)
        return True
    except Exception as e:
        log.warning("Could not send the notification email: %s", e.__class__.__name__)
        return False


# ---------------------------------------------------------------- the order watcher

def build_pack_with_cli(argv: list[str]):
    """Build one pack with the existing `python -m skysoftly story` command."""
    from skysoftly.__main__ import main
    main(argv)


PACK_FILES = ["story.mp3", "storybook.pdf", "certificate.jpg", "How to enjoy your gift.txt", "cover.jpg"]
ETSY_FILE_LIMIT_MB = 20


class OrderWatcher:
    def __init__(self, out_root: Path = DEFAULT_OUT, video: bool = False, no_audio: bool = False,
                 build_pack: Callable[[list[str]], None] | None = None,
                 send: Callable[[str, str], bool] | None = None, town_lookup: TownLookup | None = None,
                 today: dt.date | None = None):
        self.out_root = Path(out_root)
        self.review_root = self.out_root / "needs-review"
        self.state = ProcessedState(self.out_root / "processed.json")
        self.video, self.no_audio = video, no_audio
        self.build_pack = build_pack or (lambda argv: build_pack_with_cli(argv))
        self.send = send or (lambda subject, body: notify(subject, body))
        self.town_lookup, self.today = town_lookup, today

    def process(self, receipts: Iterable[dict]) -> list[dict]:
        results = []
        for r in receipts:
            rid = r.get("receipt_id")
            if rid is None or not is_new_paid_order(r):
                continue
            if not str(rid).isdigit():  # receipt ids become folder names
                log.error("Skipping a receipt with a strange id: %r", rid)
                continue
            if rid in self.state:
                log.debug("Receipt %s already processed", rid)
                continue
            try:
                results.append(self.process_receipt(r))
            except Exception as e:  # one bad order must not stop the others
                log.error("Receipt %s failed: %s", rid, e)
                self._needs_review(r, [f"Unexpected error: {e.__class__.__name__}: {e}"], [], traceback.format_exc())
                results.append({"receipt_id": rid, "status": "needs-review"})
        return results

    def process_receipt(self, r: dict) -> dict:
        rid = r["receipt_id"]
        items = order_items(r)
        story_items = [it for it in items if it.personalization]
        problems: list[str] = []
        parsed: list[tuple[OrderItem, ParseResult]] = []
        if not story_items:
            problems.append("No personalisation found on any item in this order."
                            + (" The buyer left a note: see message_from_buyer in order.json." if r.get("message_from_buyer") else ""))
        for it in story_items:
            pr = parse_personalization(it.personalization, r.get("country_iso"), self.today, self.town_lookup)
            label = f"'{it.title[:40]}'" if len(story_items) > 1 else "The personalisation"
            problems += [f"{label}: {p}" for p in pr.problems]
            if it.quantity > 1:
                problems.append(f"{label}: quantity is {it.quantity} but there is only one set of answers.")
            parsed.append((it, pr))
        if problems:
            return self._needs_review(r, problems, parsed)

        out = self.out_root / str(rid)
        out.mkdir(parents=True, exist_ok=True)
        packs = []
        for it, pr in parsed:
            pack_dir = out / ("pack" if len(parsed) == 1 else f"pack-{it.transaction_id}")
            argv = pr.fields.story_argv(pack_dir, video=self.video, no_audio=self.no_audio)
            packs.append({"transaction_id": it.transaction_id, "dir": str(pack_dir), "argv": argv})
        self._write_order_json(out / "order.json", r, parsed, packs=packs)
        for p, (it, pr) in zip(packs, parsed):
            log.info("Receipt %s: building pack for %s", rid, pr.fields.name)
            try:
                self.build_pack(p["argv"])
            except SystemExit as e:  # the CLI exits on e.g. an unknown town
                return self._needs_review(r, [f"Building the pack stopped: {e}"], parsed, moved_from=out)
            except Exception as e:
                return self._needs_review(r, [f"Building the pack failed: {e.__class__.__name__}: {e}"], parsed,
                                          traceback.format_exc(), moved_from=out)
        others = [it for it in items if not it.personalization]
        ready = ready_text(r, parsed, packs, others, self.video)
        (out / "READY.txt").write_text(ready)
        self.state.mark(rid, "ready", folder=str(out))
        names = " and ".join(pr.fields.name or "?" for _, pr in parsed)
        self.send(f"Etsy order {rid}: {names}'s pack is ready", ready)
        log.info("Receipt %s ready: %s", rid, out)
        return {"receipt_id": rid, "status": "ready", "folder": str(out)}

    def _write_order_json(self, path: Path, r: dict, parsed, packs=None, problems=None):
        doc = {"receipt_id": r.get("receipt_id"), "status": r.get("status"), "created_timestamp": r.get("created_timestamp"),
               "buyer_name": r.get("name"), "buyer_country": r.get("country_iso"),
               "message_from_buyer": r.get("message_from_buyer"),
               "items": [{"transaction_id": it.transaction_id, "listing_id": it.listing_id, "title": it.title,
                          "quantity": it.quantity, "personalization": it.personalization,
                          "other_choices": it.other_choices, "fields": pr.fields.to_dict(), "problems": pr.problems,
                          "notes": pr.notes} for it, pr in parsed],
               "packs": packs or [], "problems": problems or [],
               "etsy_receipt": r}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=1, ensure_ascii=False, default=str))

    def _needs_review(self, r: dict, problems: list[str], parsed, tb: str | None = None, moved_from: Path | None = None) -> dict:
        rid = r.get("receipt_id")
        d = self.review_root / str(rid)
        d.mkdir(parents=True, exist_ok=True)
        if not parsed:
            parsed = [(it, parse_personalization(it.personalization, r.get("country_iso"), self.today, self.town_lookup))
                      for it in order_items(r) if it.personalization]
        self._write_order_json(d / "order.json", r, parsed, problems=problems)
        lines = [f"Etsy receipt {rid} needs a human.", "", "Why:"] + [f"  - {p}" for p in problems] + [""]
        for it, pr in parsed:
            lines += [f"Item: {it.title}", "Buyer's answers:", _indent(it.personalization or "(none)"), ""]
            lines += ["What we could read (fix the blanks, then run this yourself):",
                      "  python -m skysoftly " + " ".join(_shell_quote(a) for a in pr.fields.story_argv(
                          self.out_root / str(rid) / "pack", video=self.video, blanks=True)),
                      "  (add --born YYYY-MM-DD --city TOWN --country CC for the real birth-night sky)" if not pr.fields.born else "",
                      ""]
        if tb:
            lines += ["Technical detail:", _indent(tb)]
        lines += ["When it's fixed and built, mark the order complete on Etsy.",
                  f"To let the watcher try this order again: python -m skysoftly.etsy forget {rid}"]
        text = "\n".join(lines) + "\n"
        (d / "REASON.txt").write_text(text)
        if moved_from and moved_from.exists():
            (moved_from / "BUILD-FAILED.txt").write_text(f"See {d / 'REASON.txt'}\n")
        self.state.mark(rid, "needs-review", folder=str(d))
        self.send(f"Etsy order {rid} needs review", text)
        log.warning("Receipt %s needs review: %s", rid, "; ".join(problems))
        return {"receipt_id": rid, "status": "needs-review", "folder": str(d), "problems": problems}


def _indent(s: str) -> str:
    return "\n".join("    " + ln for ln in s.splitlines())


def _shell_quote(a: str) -> str:
    return a if re.fullmatch(r"[\w@%+=:,./-]+", a) else "'" + a.replace("'", "'\"'\"'") + "'"


def ready_text(r: dict, parsed, packs: list[dict], others: list[OrderItem], video: bool) -> str:
    rid = r.get("receipt_id")
    out = [f"Etsy order {rid} is ready to send.", ""]
    for (it, pr), p in zip(parsed, packs):
        fl = pr.fields
        out += [f"{fl.name}  ({fl.pronoun}, {'turning ' + str(fl.age) if fl.age else 'any night'}, {fl.animal}, {fl.colour}"
                + (f", born {fl.born:%d %B %Y} in {fl.city}{', ' + fl.country if fl.country else ''}" if fl.born else "") + ")",
                f"From: {fl.giver}", f"Message: {fl.message}", ""]
        if it.other_choices:
            out += ["Buyer chose: " + "; ".join(f"{k}: {v}" for k, v in it.other_choices.items())]
            if not video and any("video" in str(v).lower() for v in it.other_choices.values()):
                out += ["  !! They paid for the video, but this pack was built without it. Run the command in order.json with --video."]
            out.append("")
        if pr.notes:
            out += ["Worth a look:"] + [f"  - {n}" for n in pr.notes] + [""]
        pack = Path(p["dir"])
        out.append(f"Upload these from {pack}:")
        for name in PACK_FILES:
            fp = pack / name
            if fp.exists():
                mb = fp.stat().st_size / 1e6
                warn = f"  (over {ETSY_FILE_LIMIT_MB} MB: share by link instead)" if mb > ETSY_FILE_LIMIT_MB else ""
                out.append(f"  - {name}  {mb:.1f} MB{warn}")
            else:
                out.append(f"  - {name}  (not found yet)")
        zips = sorted(pack.glob("*-gift-pack.zip"))
        if zips:
            out.append(f"  (or just the one zip: {zips[0].name}  {zips[0].stat().st_size / 1e6:.1f} MB)")
        if video:
            out.append("  - story.mp4 is too big for Etsy: put it in your Google Drive or Dropbox and copy the share link.")
        out.append("")
    if others:
        out += ["This order also has items without personalisation. Fulfil them by hand:"] + [f"  - {o.title}" for o in others] + [""]
    out += ["Checklist:",
            "  [ ] Listen to the first minute of story.mp3. Is the name said right?",
            "  [ ] Flick through storybook.pdf. Is the name spelled right?",
            "  [ ] Open the order on Etsy (Shop Manager > Orders) and upload the files above.",
            "  [ ] Paste the video link in the order message." if video else "  [ ] (No video in this pack.)",
            "  [ ] Mark the order complete.", ""]
    return "\n".join(out)


# ---------------------------------------------------------------- polling loop

def poll_once(watcher: OrderWatcher, fetch: Callable[[], list[dict]]) -> list[dict]:
    receipts = fetch()
    new = [r for r in receipts if is_new_paid_order(r) and r.get("receipt_id") not in watcher.state]
    log.info("Found %d paid order(s), %d new", len(receipts), len(new))
    return watcher.process(receipts)


def watch_loop(watcher: OrderWatcher, fetch: Callable[[], list[dict]], every_minutes: float = 5.0,
               sleep: Callable[[float], None] = time.sleep, max_polls: int | None = None):
    """Poll forever (or max_polls times). Errors are logged and the loop carries on."""
    polls, failures, auth_warned = 0, 0, False
    while max_polls is None or polls < max_polls:
        polls += 1
        try:
            poll_once(watcher, fetch)
            failures, auth_warned = 0, False
        except AuthError as e:  # not transient: keep the normal interval and ask for a new login once
            failures = 0
            log.error("%s", e)
            if not auth_warned:
                watcher.send("Etsy order watcher needs you to sign in again", f"{e}\n\nRun: python -m skysoftly.etsy login\n")
                auth_warned = True
        except (EtsyError, requests.RequestException, OSError, ValueError) as e:
            failures += 1
            log.error("Poll failed (%s): %s", e.__class__.__name__, e)
        if max_polls is not None and polls >= max_polls:
            break
        wait = every_minutes * 60 * (min(2 ** max(failures - 1, 0), 6) if failures else 1)
        log.info("Next check in %.0f minutes", wait / 60)
        sleep(wait)


# ---------------------------------------------------------------- command line

def _fetcher(args) -> Callable[[], list[dict]]:
    if args.dry_run:
        path = Path(args.dry_run)
        return lambda: load_fixture(path)
    client = EtsyClient(load_config())
    since = int(time.time() - args.since * 86400)
    return lambda: client.paid_unshipped_receipts(min_created=since)


def main(argv: list[str] | None = None):
    ap = argparse.ArgumentParser(prog="python -m skysoftly.etsy", description="Etsy order automation for the gift packs.")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    lg = sub.add_parser("login", help="Sign in to Etsy once (OAuth with PKCE)")
    lg.add_argument("--no-browser", action="store_true", help="Print the link instead of opening a browser")
    lg.add_argument("--paste", action="store_true", help="Paste the redirected address by hand (no local server)")
    lg.add_argument("--timeout", type=float, default=300)
    sub.add_parser("whoami", help="Show the Etsy user id and shop id")
    for name in ("watch", "fetch"):
        p = sub.add_parser(name, help="Poll for new paid orders" if name == "watch" else "Check for new orders once")
        p.add_argument("--every", type=float, default=5, help="Minutes between checks (default 5)")
        p.add_argument("--once", action="store_true", help="Check once and stop")
        p.add_argument("--dry-run", metavar="FIXTURE.json", help="Read receipts from a local JSON file instead of Etsy")
        p.add_argument("--video", action="store_true", help="Also render story.mp4 (slow)")
        p.add_argument("--no-audio", action="store_true", help="Skip narration (fast test run)")
        p.add_argument("--out", help=f"Orders folder (default {DEFAULT_OUT}, or {DRY_RUN_OUT} with --dry-run)")
        p.add_argument("--since", type=float, default=14, help="Only look at orders from the last N days (default 14)")
    ps = sub.add_parser("parse", help="Show how a personalisation text is read")
    ps.add_argument("text", nargs="?", help="The text, or '-' / nothing to read from stdin")
    ps.add_argument("--buyer-country")
    fg = sub.add_parser("forget", help="Let a receipt be processed again")
    fg.add_argument("receipt_id"); fg.add_argument("--out", default=str(DEFAULT_OUT))
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M")
    logging.getLogger("urllib3").setLevel(logging.WARNING)  # keeps request URLs and headers out of the log

    if a.cmd == "login":
        cfg = load_config()
        store = TokenStore()
        login(cfg, store, open_browser=not a.no_browser, paste=a.paste, timeout=a.timeout)
        try:
            me = EtsyClient(cfg, store).get_me()
            print(f"Etsy user {me.get('user_id')}, shop id {me.get('shop_id')}. "
                  f"Add \"shop_id\": {me.get('shop_id')} to {config_dir() / 'etsy.json'} to skip this lookup.")
        except EtsyError as e:
            print(f"Signed in, but couldn't look up the shop: {e}")
    elif a.cmd == "whoami":
        me = EtsyClient(load_config()).get_me()
        print(f"user_id {me.get('user_id')}  shop_id {me.get('shop_id')}")
    elif a.cmd in ("watch", "fetch"):
        out = Path(a.out) if a.out else (DRY_RUN_OUT if a.dry_run else DEFAULT_OUT)
        watcher = OrderWatcher(out, video=a.video, no_audio=a.no_audio)
        fetch = _fetcher(a)
        if a.cmd == "fetch" or a.once:
            try:
                results = poll_once(watcher, fetch)
            except EtsyError as e:
                raise SystemExit(str(e))
            for res in results:
                print(f"  {res['receipt_id']}: {res['status']}  {res.get('folder', '')}")
            print(f"{len(results)} new order(s). Folder: {out}")
        else:
            print(f"Watching for new Etsy orders every {a.every:g} minutes. Press Ctrl+C to stop.")
            try:
                watch_loop(watcher, fetch, a.every)
            except KeyboardInterrupt:
                print("\nStopped.")
    elif a.cmd == "parse":
        text = sys.stdin.read() if a.text in (None, "-") else a.text
        res = parse_personalization(text, a.buyer_country)
        print(json.dumps({"fields": res.fields.to_dict(), "problems": res.problems, "notes": res.notes}, indent=1))
        if res.ok:
            print("\npython -m skysoftly " + " ".join(_shell_quote(x) for x in res.fields.story_argv(Path("output/stories/" + (res.fields.name or "x").lower()))))
    elif a.cmd == "forget":
        ok = ProcessedState(Path(a.out) / "processed.json").forget(a.receipt_id)
        print("Forgotten; it will be picked up on the next check." if ok else "That receipt wasn't in the list.")


if __name__ == "__main__":
    main()
