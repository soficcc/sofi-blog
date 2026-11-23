#!/usr/bin/env python3
"""sofi-blog: add and edit entries for Sofia’s little grimoire, then rebuild the site.

Run it with ./sofi-blog.sh (which sets up and activates the conda environment),
then just answer the questions. Arrow keys move, Enter picks, Ctrl+C goes back.
"""
import datetime as dt
import functools
import http.server
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import unicodedata
import urllib.parse
import webbrowser
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import questionary
import requests
from questionary import Choice, Separator, Style

ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "data" / "entries.json"
CONFIG_FILE = ROOT / "config.toml"
DOCS = ROOT / "docs"  # the folder GitHub Pages publishes
SHARED = DOCS / "shared"
COVERS = SHARED / "covers"

KINDS = ["book", "film", "series", "album", "game"]
STATUSES = {
    "book": ["finished", "reading", "backlog", "dropped"],
    "film": ["watched", "backlog"],
    "series": ["finished", "watching", "backlog", "dropped"],
    "album": [],
    "game": ["finished", "playing", "backlog", "dropped"],
}
IN_PROGRESS = {"reading", "watching", "playing"}
TITLE_Q = {
    "book": "title?",
    "film": "title?",
    "series": "title?",
    "album": "album title?",
    "game": "title?",
}
CREATOR_Q = {
    "book": "author?",
    "film": "director?",
    "series": "creator?",
    "album": "artist?",
    "game": "developer?",
}
DATE_Q = {
    "finished": "finished on?",
    "watched": "watched on?",
    "dropped": "stopped on?",
    "": "added on?",
}
STARTED_Q = {
    "reading": "started reading on?",
    "watching": "started watching on?",
    "playing": "started playing on?",
}
VERBS = {
    "book": {"finished": "finished reading", "reading": "started reading", "backlog": "added to the reading pile", "dropped": "put down"},
    "film": {"watched": "watched", "backlog": "added to the watchlist"},
    "series": {"finished": "finished watching", "watching": "started watching", "backlog": "added to the watchlist", "dropped": "stopped watching"},
    "album": {"": "added to the album shelf"},
    "game": {"finished": "finished playing", "playing": "started playing", "backlog": "added to the game backlog", "dropped": "stopped playing"},
}
SOURCE_NAME = {"book": "Open Library", "film": "Wikidata", "series": "TVmaze", "album": "MusicBrainz", "game": "Wikidata"}

STYLE = Style([
    ("qmark", "fg:#AE99B2 bold"),
    ("question", "bold"),
    ("answer", "fg:#C0AB6A bold"),
    ("pointer", "fg:#C0AB6A bold"),
    ("highlighted", "fg:#C0AB6A bold"),
    ("selected", "fg:#C0AB6A"),
    ("instruction", "fg:#776B89 italic"),
])
QMARK = "✦"


# ───────────────────────── small helpers ─────────────────────────

class Cancel(Exception):
    """Raised when you press Ctrl+C at a question: goes back to the main menu."""


def ask(question):
    answer = question.ask()
    if answer is None:
        raise Cancel
    return answer


def select(message, choices, default=None, search=False, instruction=None):
    if search and instruction is None:
        instruction = "(type to filter, arrows to move)"
    return ask(questionary.select(
        message, choices=choices, default=default, qmark=QMARK, style=STYLE,
        use_search_filter=search, use_jk_keys=not search, instruction=instruction))


def text(message, default="", validate=None, instruction=None):
    return ask(questionary.text(
        message, default=default, qmark=QMARK, style=STYLE,
        validate=validate, instruction=instruction)).strip()


def confirm(message, default=True):
    return ask(questionary.confirm(message, default=default, qmark=QMARK, style=STYLE))


def say(msg=""):
    print(msg)


def today():
    return dt.date.today().isoformat()


def now_iso():
    return dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def slugify(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:60] or "untitled"


def stars(r):
    if r is None:
        return ""
    full = int(r)
    half = r - full >= 0.5
    return "★" * full + ("½" if half else "") + "☆" * (5 - full - (1 if half else 0))


def load_config():
    if not CONFIG_FILE.exists():
        return {}
    try:
        with open(CONFIG_FILE, "rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as ex:
        print(f"  ✗ config.toml has a mistake ({ex}). Addresses and text need quotes, "
              f'like playlist = "https://soundcloud.com/…". Ignoring the file until it\'s fixed.')
        return {}


CONF = load_config()


def reload_config():
    """Read config.toml again, so edits made while the helper is open count."""
    CONF.clear()
    CONF.update(load_config())


def music_source():
    """Reads the playlist address from config.toml and works out what it is.
    Returns (settings for the page, a note for the terminal; empty when all is well)."""
    url = str(CONF.get("music", {}).get("playlist", "")).strip()
    if not url:
        where = "config.toml" if CONFIG_FILE.exists() else "config.toml (it doesn't exist yet: copy config.example.toml)"
        return {}, f"no playlist: add playlist = \"https://www.youtube.com/playlist?list=…\" under [music] in {where}"
    if not url.startswith("http"):
        url = "https://" + url
    parts = urllib.parse.urlparse(url)
    host = parts.netloc.lower()
    if "youtube.com" in host or "youtu.be" in host:
        query = urllib.parse.parse_qs(parts.query)
        playlist = query.get("list", [""])[0]
        video = query.get("v", [""])[0] or (parts.path.strip("/") if "youtu.be" in host else "")
        if playlist.startswith(("RD", "LM", "WL", "LL")):
            return {}, ("that's one of YouTube's automatic lists (a mix, liked songs or watch later), which only "
                        "plays inside YouTube. Make your own playlist, set it to public or unlisted, and copy its address")
        if playlist:
            return dict(provider="youtube", list=playlist, video=video,
                        playlist=f"https://www.youtube.com/playlist?list={playlist}"), ""
        if video:
            return (dict(provider="youtube", list="", video=video, playlist=f"https://www.youtube.com/watch?v={video}"),
                    "that's a single video, so it will play just that one song (playlist addresses contain list=)")
        return {}, "that YouTube address has no playlist in it: open the playlist and copy the address that contains list="
    if "soundcloud.com" in host:
        url = url.split("?")[0].rstrip("/").replace("://m.soundcloud.com", "://soundcloud.com")
        if "on.soundcloud.com" in url:
            return dict(provider="soundcloud", playlist=url), ("that's a short share link, which the player can't always "
                                                               "open. Open it in your browser and copy the full address instead")
        return dict(provider="soundcloud", playlist=url), "" if "/sets/" in url else "that's not a playlist address, so it will play just that one thing"
    return {}, "that address isn't a YouTube or SoundCloud link"


def user_agent():
    contact = CONF.get("site", {}).get("contact") or "no-contact-set"
    return f"sofi-blog/1.0 ( {contact} )"


def http_get(url, **kw):
    headers = kw.pop("headers", {})
    headers.setdefault("User-Agent", user_agent())
    r = requests.get(url, headers=headers, timeout=20, **kw)
    r.raise_for_status()
    return r


def load_data():
    if DATA_FILE.exists():
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    else:
        data = {}
    data.setdefault("version", 1)
    data.setdefault("now", [])
    data.setdefault("links", [])
    data.setdefault("entries", [])
    data.setdefault("posts", [])
    data.setdefault("made", "")
    for e in data["entries"]:
        if "started" not in e:
            # older entries kept one date; for things in progress, that date was when they started
            in_progress = e.get("status") in IN_PROGRESS
            e["started"] = e.get("date") if in_progress else None
            if in_progress:
                e["date"] = None
    return data


def save_data(data):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(DATA_FILE)


def entry_label(e):
    bits = [e["title"]]
    if e.get("creator"):
        bits.append(f"— {e['creator']}")
    if e.get("year"):
        bits.append(f"({e['year']})")
    return " ".join(bits)


# ───────────────────────── validators ─────────────────────────

def v_nonempty(s):
    return True if s.strip() else "please type something"


def parse_date(s):
    s = s.strip().lower()
    if s == "today":
        return today()
    if s == "yesterday":
        return (dt.date.today() - dt.timedelta(days=1)).isoformat()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def v_date(s):
    if not s.strip() or parse_date(s):
        return True
    return "use a date like 2026-11-22, or type today / yesterday (or leave it empty)"


def ask_date(message, existing=None):
    """An optional date: empty means no date."""
    hint = "(empty removes it)" if existing else "(enter to skip; or today, yesterday, 2026-11-22)"
    answer = text(message, default=existing or "", validate=v_date, instruction=hint)
    return parse_date(answer) if answer.strip() else None


def parse_rating(s):
    s = s.strip().replace(",", ".")
    if not s:
        return "skip"
    try:
        r = float(s)
    except ValueError:
        return None
    if 0 <= r <= 5 and (r * 2).is_integer():
        return r
    return None


def v_rating(s):
    return True if parse_rating(s) is not None else "a number from 0 to 5, in steps of 0.5 (or enter to skip)"


def v_year(s):
    return True if not s.strip() or re.fullmatch(r"\d{4}", s.strip()) else "four digits, like 1974 (or enter to skip)"


# ───────────────────────── long text / editor ─────────────────────────

def open_editor(initial=""):
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or ("notepad" if os.name == "nt" else "nano")
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(initial)
        path = f.name
    try:
        subprocess.call(shlex.split(editor) + [path])
        return Path(path).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        say(f"  couldn't open the editor '{editor}'. type it here instead (Esc then Enter to finish).")
        return ask(questionary.text("", default=initial, multiline=True, qmark=QMARK, style=STYLE)).strip()
    finally:
        os.unlink(path)


def ask_long(message, existing=""):
    if existing:
        preview = existing if len(existing) < 70 else existing[:67] + "…"
        say(f"  current: {preview}")
        what = select(message, ["keep it", "edit it in your text editor", "remove it"])
        if what == "keep it":
            return existing
        if what == "remove it":
            return ""
        return open_editor(existing)
    answer = text(message, instruction="(type it, or type e and press enter to open your text editor; enter to skip)")
    if answer.lower() == "e":
        return open_editor("")
    return answer


# ───────────────────────── metadata sources ─────────────────────────

def lucene(s):
    return re.sub(r'([+\-!(){}\[\]^"~*?:\\/]|&&|\|\|)', r"\\\1", s)


def search_book(title, _extra=""):
    fields = "key,title,author_name,first_publish_year,cover_i,edition_count"

    def run(q):
        j = http_get("https://openlibrary.org/search.json", params={"q": q, "fields": fields, "limit": 8}).json()
        return j.get("docs", [])

    docs = run(title)
    if not docs:  # forgiving second try for typos
        docs = run(" ".join(w + "~" if len(w) > 3 else w for w in title.split()))
    out = []
    for d in docs:
        n = d.get("edition_count") or 0
        out.append(dict(
            title=d.get("title", ""),
            creator=", ".join((d.get("author_name") or [])[:2]),
            year=d.get("first_publish_year"),
            detail=f"{n} edition{'s' if n != 1 else ''}" if n else "",
            cover_url=f"https://covers.openlibrary.org/b/id/{d['cover_i']}-L.jpg?default=false" if d.get("cover_i") else None,
            link="https://openlibrary.org" + d["key"],
            source="openlibrary", source_id=d["key"]))
    return out


WIKIDATA = "https://www.wikidata.org/w/api.php"
# Wikidata classes that count as a film: film, feature film, animated film, TV film,
# silent film, short film, documentary film
FILM_CLASSES = ["Q11424", "Q24869", "Q202866", "Q506240", "Q226730", "Q24862", "Q93204"]


def wikidata(**params):
    params["format"] = "json"
    return http_get(WIKIDATA, params=params).json()


def claim_values(entity, prop):
    out = []
    for c in entity.get("claims", {}).get(prop, []):
        snak = c.get("mainsnak", {})
        if snak.get("snaktype") == "value":
            out.append(snak.get("datavalue", {}).get("value"))
    return out


def wikidata_find(title, classes):
    """Search Wikidata for items of the given kinds; returns [(id, entity)] best match first."""
    only = "haswbstatement:" + "|".join(f"P31={q}" for q in classes)

    def run(q):
        j = wikidata(action="query", list="search", srsearch=f"{q} {only}", srnamespace=0,
                     srlimit=8, srinfo="suggestion")
        hits = [h["title"] for h in j.get("query", {}).get("search", [])]
        suggestion = j.get("query", {}).get("searchinfo", {}).get("suggestion", "")
        return hits, re.sub(r"haswbstatement:\S+", "", suggestion).strip()

    ids, suggestion = run(title)
    if not ids and suggestion:  # Wikidata's "did you mean", for typos
        ids, _ = run(suggestion)
    if not ids:
        return []
    ids = ids[:6]
    ents = wikidata(action="wbgetentities", ids="|".join(ids), props="labels|descriptions|claims|sitelinks",
                    languages="en", sitefilter="enwiki").get("entities", {})
    return [(i, ents.get(i, {})) for i in ids]


def wikidata_labels(ids):
    ids = [i for i in dict.fromkeys(ids) if i][:50]
    if not ids:
        return {}
    got = wikidata(action="wbgetentities", ids="|".join(ids), props="labels", languages="en").get("entities", {})
    return {k: v.get("labels", {}).get("en", {}).get("value", "") for k, v in got.items()}


def wiki_title(entity):
    return entity.get("sitelinks", {}).get("enwiki", {}).get("title", "")


def wikipedia_image(title):
    """The main image of an English Wikipedia article (for films and games, the poster or cover art)."""
    j = http_get("https://en.wikipedia.org/w/api.php", params={
        "action": "query", "prop": "pageimages", "titles": title, "pithumbsize": 600,
        "pilicense": "any", "redirects": 1, "format": "json"}).json()
    for page in j.get("query", {}).get("pages", {}).values():
        src = page.get("thumbnail", {}).get("source")
        if src:
            return src
    return None


def item_ids(entity, prop):
    return [v["id"] for v in claim_values(entity, prop) if isinstance(v, dict) and "id" in v]


def first_year(entity):
    years = [int(v["time"][1:5]) for v in claim_values(entity, "P577")
             if isinstance(v, dict) and v.get("time", "")[1:5].isdigit()]
    return min(years) if years else None


def search_film(title, _extra=""):
    """Films come from Wikidata (no key needed). Posters come from OMDb if you set its key."""
    found = wikidata_find(title, FILM_CLASSES)
    names = wikidata_labels([d for _, e in found for d in item_ids(e, "P57")])
    omdb_key = CONF.get("omdb", {}).get("api_key", "")
    out = []
    for i, e in found:
        label = e.get("labels", {}).get("en", {}).get("value") or i
        directors = [names.get(d, "") for d in item_ids(e, "P57")]
        imdb = next(iter(claim_values(e, "P345")), "")
        letterboxd = next(iter(claim_values(e, "P6127")), "")
        tmdb_id = next(iter(claim_values(e, "P4947")), "")
        poster = next(iter(claim_values(e, "P3383")), "")
        if letterboxd:
            link = f"https://letterboxd.com/film/{letterboxd}/"
        elif imdb:
            link = f"https://letterboxd.com/imdb/{imdb}/"
        elif tmdb_id:
            link = f"https://letterboxd.com/tmdb/{tmdb_id}/"
        else:
            link = f"https://www.wikidata.org/wiki/{i}"
        # places to look for a poster, tried in order (only for the film you pick)
        cover = []
        if omdb_key and imdb:
            cover.append(f"omdb:{imdb}")
        if wiki_title(e):
            cover.append(f"wiki:{wiki_title(e)}")
        if poster:
            cover.append("https://commons.wikimedia.org/wiki/Special:FilePath/" + requests.utils.quote(poster) + "?width=500")
        out.append(dict(
            title=label, creator=", ".join(d for d in directors if d)[:80],
            year=first_year(e),
            detail=film_detail(e.get("descriptions", {}).get("en", {}).get("value", "")),
            cover_url=cover, link=link, source="wikidata", source_id=i))
    return out


def film_detail(desc):
    """Keep Wikidata's description only when it adds something (“short film”, a country…)."""
    return "" if re.fullmatch(r"\d{4} film( directed)?( by .+)?", desc.strip()) else desc


def omdb_poster(imdb_id):
    key = CONF.get("omdb", {}).get("api_key", "")
    if not key:
        return None
    j = http_get("https://www.omdbapi.com/", params={"i": imdb_id, "apikey": key}).json()
    poster = j.get("Poster", "")
    return poster if poster.startswith("http") else None


def series_link(show):
    pref = CONF.get("links", {}).get("series", "tvmaze")
    imdb = (show.get("externals") or {}).get("imdb")
    if pref == "trakt" and imdb:
        return f"https://trakt.tv/search/imdb/{imdb}?id_type=show"
    if pref == "imdb" and imdb:
        return f"https://www.imdb.com/title/{imdb}/"
    return show.get("url") or f"https://www.tvmaze.com/shows/{show['id']}"


def search_series(title, _extra=""):
    """Series come from TVmaze (no key needed)."""
    results = http_get("https://api.tvmaze.com/search/shows", params={"q": title}).json()[:6]
    out = []
    for r in results:
        s = r.get("show", {})
        creators = []
        try:
            crew = http_get(f"https://api.tvmaze.com/shows/{s['id']}/crew").json()
            creators = [c["person"]["name"] for c in crew if c.get("type") == "Creator"]
        except requests.RequestException:
            pass
        where = (s.get("network") or s.get("webChannel") or {}).get("name", "")
        detail = ", ".join(x for x in [where, "ended" if s.get("status") == "Ended" else ""] if x)
        out.append(dict(
            title=s.get("name", ""), creator=", ".join(creators[:2]),
            year=int(s["premiered"][:4]) if s.get("premiered") else None,
            detail=detail,
            cover_url=(s.get("image") or {}).get("original"),
            link=series_link(s), source="tvmaze", source_id=s.get("id")))
    return out


def album_link(mbid, title, artist):
    pref = CONF.get("links", {}).get("albums", "musicbrainz")
    q = requests.utils.quote(f"{artist} {title}".strip())
    if pref == "spotify":
        return f"https://open.spotify.com/search/{q}"
    if pref == "bandcamp":
        return f"https://bandcamp.com/search?q={q}&item_type=a"
    if pref == "youtube":
        return f"https://music.youtube.com/search?q={q}"
    return f"https://musicbrainz.org/release-group/{mbid}"


def search_album(title, artist=""):
    def run(t, a, fuzzy=False):
        f = (lambda s: " ".join(w + "~" for w in lucene(s).split())) if fuzzy else lucene
        q = f"releasegroup:({f(t)})" + (f" AND artist:({f(a)})" if a else "")
        j = http_get("https://musicbrainz.org/ws/2/release-group/", params={"query": q, "fmt": "json", "limit": 8}).json()
        return j.get("release-groups", [])

    groups = run(title, artist) or run(title, artist, fuzzy=True)
    out = []
    for g in groups:
        credit = "".join(ac.get("name", "") + ac.get("joinphrase", "") for ac in g.get("artist-credit", []))
        kinds = [g.get("primary-type") or ""] + (g.get("secondary-types") or [])
        date = g.get("first-release-date") or ""
        out.append(dict(
            title=g.get("title", ""), creator=credit,
            year=int(date[:4]) if date[:4].isdigit() else None,
            detail=" + ".join(k.lower() for k in kinds if k),
            cover_url=f"https://coverartarchive.org/release-group/{g['id']}/front-500",
            link=album_link(g["id"], g.get("title", ""), credit),
            source="musicbrainz", source_id=g["id"]))
    return out


GAME_CLASSES = ["Q7889"]  # video game


def search_game(title, _extra=""):
    """Games come from Wikidata (no key needed). Links go to Backloggd through the IGDB name
    Wikidata keeps; covers come from the Steam store when the game is on Steam."""
    found = wikidata_find(title, GAME_CLASSES)
    names = wikidata_labels([x for _, e in found for x in item_ids(e, "P178") + item_ids(e, "P400")])
    out = []
    for i, e in found:
        label = e.get("labels", {}).get("en", {}).get("value") or i
        devs = [names.get(d, "") for d in item_ids(e, "P178")]
        plats = [names.get(d, "") for d in item_ids(e, "P400")]
        plats = [p for p in plats if p]
        igdb_slug = next(iter(claim_values(e, "P5794")), "")
        steam = next(iter(claim_values(e, "P1733")), "")
        if igdb_slug:
            link = f"https://www.backloggd.com/games/{igdb_slug}/"
        elif steam:
            link = f"https://store.steampowered.com/app/{steam}/"
        else:
            link = f"https://www.wikidata.org/wiki/{i}"
        out.append(dict(
            title=label, creator=", ".join(d for d in devs if d)[:80], year=first_year(e),
            detail=", ".join(plats[:4]) + (" …" if len(plats) > 4 else ""),
            cover_url=([f"steam:{steam}"] if steam else []) + ([f"wiki:{wiki_title(e)}"] if wiki_title(e) else []),
            link=link, source="wikidata", source_id=i))
    return out


def steam_cover(appid):
    """The tall Steam library cover if there is one, otherwise the wide store header."""
    for u in (f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900_2x.jpg",
              f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900_2x.jpg"):
        try:
            if http_get(u).status_code == 200:
                return u
        except requests.RequestException:
            pass
    try:
        j = http_get("https://store.steampowered.com/api/appdetails", params={"appids": appid}).json()
        return j.get(str(appid), {}).get("data", {}).get("header_image")
    except (requests.RequestException, ValueError):
        return None


SEARCH = {"book": search_book, "film": search_film, "series": search_series, "album": search_album, "game": search_game}


def cand_label(c):
    s = c["title"] or "(untitled)"
    if c.get("creator"):
        s += f" — {c['creator']}"
    if c.get("year"):
        s += f" ({c['year']})"
    if c.get("detail"):
        s += f" · {c['detail']}"
    return s


# ───────────────────────── finding a title ─────────────────────────

def manual_candidate(kind, title):
    say("  ok, entering it by hand.")
    title = text("title?", default=title, validate=v_nonempty)
    creator = text(CREATOR_Q[kind], instruction="(enter to skip)")
    year = text("year?", validate=v_year, instruction="(enter to skip)")
    link = text("link?", instruction="(where clicking it should go; enter to skip)")
    cover = text("cover image?", instruction="(path to an image file, or an image URL; enter to skip)")
    return dict(title=title, creator=creator, year=int(year) if year else None, detail="",
                cover_url=cover.strip("'\"") or None, link=link, source="", source_id="")


def find_title(kind, title="", artist=""):
    """Ask for a title, search for it, and let you confirm the right match."""
    while True:
        title = text(TITLE_Q[kind], default=title, validate=v_nonempty)
        if kind == "album":
            artist = text("artist?", default=artist, instruction="(enter to skip, but it helps narrow things down)")
        say(f"  searching {SOURCE_NAME[kind]}…")
        try:
            cands = SEARCH[kind](title, artist)
        except requests.RequestException as ex:
            say(f"  couldn't reach {SOURCE_NAME[kind]} ({ex.__class__.__name__}).")
            cands = None
        if cands:
            if len(cands) == 1:
                if confirm(f"found {cand_label(cands[0])}. is this it?"):
                    return cands[0]
            else:
                pick = select("which one did you mean?",
                              [Choice(cand_label(c), value=i) for i, c in enumerate(cands[:6])] + [
                                  Separator(),
                                  Choice("none of these, search again", value="again"),
                                  Choice("none of these, enter it by hand", value="manual")])
                if isinstance(pick, int):
                    return cands[pick]
                if pick == "manual":
                    return manual_candidate(kind, title)
                continue
        elif cands is not None:
            say(f'  nothing found for "{title}".')
        what = select("what now?", ["search again with different words", "enter it by hand"])
        if what == "enter it by hand":
            return manual_candidate(kind, title)


# ───────────────────────── covers ─────────────────────────

def cover_target(e, ext):
    COVERS.mkdir(parents=True, exist_ok=True)
    return COVERS / f"{e['id']}{ext}"


def remove_cover_file(e):
    if e.get("cover"):
        p = DOCS / e["cover"]
        if p.exists() and p.parent == COVERS:
            p.unlink()


def store_cover(e, source):
    """Save a cover into docs/shared/covers/. `source` is an image URL, a file on this computer,
    or a list of places to try in order (the first one that gives an image wins)."""
    if isinstance(source, list):
        return any(store_one_cover(e, s, quiet=True) for s in source)
    return store_one_cover(e, source)


def store_one_cover(e, source, quiet=False):
    if not source:
        return False
    source = source.strip().strip("'\"")
    try:
        if source.startswith("omdb:"):
            source = omdb_poster(source[5:])
        elif source.startswith("steam:"):
            source = steam_cover(source[6:])
        elif source.startswith("wiki:"):
            source = wikipedia_image(source[5:])
        if not source:
            return False
        if re.match(r"https?://", source):
            r = http_get(source)
            ctype = r.headers.get("Content-Type", "")
            ext = ".png" if "png" in ctype else ".webp" if "webp" in ctype else ".jpg"
            data = r.content
            if len(data) < 1000:  # placeholder pixel, not a cover
                return False
            remove_cover_file(e)
            target = cover_target(e, ext)
            target.write_bytes(data)
        else:
            src = Path(os.path.expanduser(source))
            if not src.is_file():
                say(f"  couldn't find the file {src}.")
                return False
            remove_cover_file(e)
            target = cover_target(e, src.suffix.lower() or ".jpg")
            shutil.copyfile(src, target)
    except (requests.RequestException, ValueError):
        if not quiet:
            say("  couldn't download the cover; the entry is saved without one.")
        return False
    e["cover"] = target.relative_to(DOCS).as_posix()
    return True


# ───────────────────────── entries ─────────────────────────

def unique_id(data, base):
    ids = {e["id"] for e in data["entries"]} | {p["id"] for p in data["posts"]}
    i, cand = 2, base
    while cand in ids:
        cand, i = f"{base}-{i}", i + 1
    return cand


def ask_rating(existing=None):
    default = "" if existing is None else (str(int(existing)) if float(existing).is_integer() else str(existing))
    r = parse_rating(text("rating?", default=default, validate=v_rating, instruction="(0–5, halves ok; enter to skip)"))
    return None if r == "skip" else r


def ask_details(e, previous_status=None):
    """Status, rating, review, date and homepage, adapting to the status."""
    kind = e["type"]
    if STATUSES[kind]:
        e["status"] = select("status?", STATUSES[kind], default=e.get("status") or STATUSES[kind][0])
    else:
        e["status"] = ""
    st = e["status"]
    if st == "backlog":
        e["rating"], e["date"] = None, None
        e["review"] = e.get("review", "")
    elif st in IN_PROGRESS:
        e["rating"], e["date"] = None, None
        e["review"] = ask_long("thoughts so far?", e.get("review", ""))
        e["started"] = ask_date(STARTED_Q[st], e.get("started"))
    else:
        e["rating"] = ask_rating(e.get("rating"))
        e["review"] = ask_long("review?", e.get("review", ""))
        e["date"] = ask_date(DATE_Q.get(st, "date?"), e.get("date"))
    if st != previous_status:
        home = confirm("post it on the homepage?", default=st != "backlog")
        e["home"] = home
        if home:
            e["posted"] = now_iso()


def print_card(e):
    line = "─" * 46
    say(line)
    say(f" {entry_label(e)}")
    bits = []
    verb = VERBS[e["type"]].get(e.get("status", ""), "")
    if verb:
        when = e.get("started") if e.get("status") in IN_PROGRESS else e.get("date")
        bits.append(verb + (f" {pretty_date(when)}" if when else ""))
    if e.get("rating") is not None:
        bits.append(stars(e["rating"]))
    bits.append("on the homepage" if e.get("home") else "not on the homepage")
    say(" " + " · ".join(bits))
    if e.get("review"):
        r = e["review"].replace("\n", " ")
        say(f" “{r[:80]}{'…' if len(r) > 80 else ''}”")
    if e.get("link"):
        say(f" link → {e['link']}")
    if e.get("cover"):
        say(f" cover → docs/{e['cover']}")
    elif e.get("_cover_src"):
        say(" cover → will be downloaded on save")
    else:
        say(" cover → none yet")
    say(line)


def pretty_date(iso):
    try:
        d = dt.date.fromisoformat(iso)
    except (TypeError, ValueError):
        return ""
    return f"{d.day} {d.strftime('%b').lower()}" + ("" if d.year == dt.date.today().year else f" {d.year}")


def add_entry(data):
    kind = select("what kind of entry?", KINDS)
    c = find_title(kind)
    dupe = next((x for x in data["entries"] if x["type"] == kind and (
        (c["source_id"] and str(x.get("source_id")) == str(c["source_id"])) or
        x["title"].lower() == c["title"].lower())), None)
    if dupe and not confirm(f"you already have {entry_label(dupe)}. add it again anyway?", default=False):
        if confirm("edit the existing one instead?"):
            edit_one(data, dupe)
        return
    e = dict(id=unique_id(data, f"{kind}-{slugify(c['title'])}"), type=kind, title=c["title"],
             creator=c.get("creator", ""), year=c.get("year"), cover=None, link=c.get("link", ""),
             status="", rating=None, review="", date=None, started=None, home=False, posted=None,
             added=now_iso(), source=c.get("source", ""), source_id=c.get("source_id", ""))
    e["_cover_src"] = c.get("cover_url")
    ask_details(e)
    if e["link"]:
        e["link"] = text("link?", default=e["link"], instruction="(enter keeps it, or paste a different one)")
    else:
        e["link"] = text("link?", instruction="(where clicking it should go; enter to skip)")
    print_card(e)
    if not confirm("save and rebuild the site?"):
        say("  not saved.")
        return
    src = e.pop("_cover_src", None)
    if src:
        say("  fetching the cover…")
        if not store_cover(e, src):
            say("  no cover found online; add one any time with “edit an entry” → cover.")
    data["entries"].append(e)
    save_and_build(data, f"added {e['title']}")


def pick_entry(data, message="which entry?"):
    es = sorted(data["entries"], key=lambda e: e.get("added", ""), reverse=True)
    if not es:
        say("  there are no entries yet.")
        return None
    eid = select(message, [Choice(f"{e['type']:<7} {entry_label(e)}", value=e["id"]) for e in es], search=True)
    return next(e for e in data["entries"] if e["id"] == eid)


def edit_entry(data):
    e = pick_entry(data)
    if e:
        edit_one(data, e)


def edit_one(data, e):
    changed = False
    while True:
        print_card(e)
        date_opt = None if e.get("status") == "backlog" else (
            "start date" if e.get("status") in IN_PROGRESS else "date")
        opts = ["status" if STATUSES[e["type"]] else None, "rating", "review", date_opt,
                "homepage: " + ("take it off" if e.get("home") else "post it"),
                "link", "cover", "title, creator and year", "delete this entry", "done"]
        what = select("what do you want to change?", [o for o in opts if o], default="done")
        if what == "done":
            break
        if what == "status":
            prev = e.get("status")
            ask_details(e, previous_status=prev)
        elif what == "rating":
            e["rating"] = ask_rating(e.get("rating"))
        elif what == "review":
            e["review"] = ask_long("review?", e.get("review", ""))
        elif what == "start date":
            e["started"] = ask_date(STARTED_Q[e["status"]], e.get("started"))
        elif what == "date":
            e["date"] = ask_date(DATE_Q.get(e.get("status", ""), "date?"), e.get("date"))
        elif what.startswith("homepage"):
            e["home"] = not e.get("home")
            if e["home"] and not e.get("posted"):
                e["posted"] = now_iso()
            elif e["home"] and confirm("post it as new (moves it to the top of the homepage)?", default=False):
                e["posted"] = now_iso()
        elif what == "link":
            e["link"] = text("link?", default=e.get("link", ""))
        elif what == "cover":
            how = select("new cover from where?", [
                "an image file on this computer", "an image URL", f"search {SOURCE_NAME[e['type']]} again",
                "remove the cover", "never mind"])
            if how == "an image file on this computer":
                store_cover(e, text("path to the image?", instruction="(tip: drag the file into this window)", validate=v_nonempty))
            elif how == "an image URL":
                store_cover(e, text("image URL?", validate=v_nonempty))
            elif how.startswith("search"):
                c = find_title(e["type"], e["title"])
                if not (c.get("cover_url") and store_cover(e, c["cover_url"])):
                    say("  no cover found for that match.")
            elif how == "remove the cover":
                remove_cover_file(e)
                e["cover"] = None
        elif what == "title, creator and year":
            e["title"] = text("title?", default=e["title"], validate=v_nonempty)
            e["creator"] = text(CREATOR_Q[e["type"]], default=e.get("creator") or "")
            y = text("year?", default=str(e.get("year") or ""), validate=v_year)
            e["year"] = int(y) if y else None
        elif what == "delete this entry":
            if confirm(f"delete {e['title']} for good?", default=False):
                remove_cover_file(e)
                data["entries"].remove(e)
                save_and_build(data, f"deleted {e['title']}")
                return
            continue
        changed = True
    if changed:
        save_and_build(data, f"updated {e['title']}")


def fill_missing(data):
    todo = [e for e in data["entries"] if not e.get("cover")]
    if not todo:
        say("  every entry already has a cover.")
        return
    say(f"  {len(todo)} entr{'y has' if len(todo) == 1 else 'ies have'} no cover. Ctrl+C stops at any point.")
    done = looked = 0
    for e in todo:
        try:
            if not confirm(f"look up {entry_label(e)}?"):
                continue
            c = find_title(e["type"], e["title"])
        except Cancel:
            break
        looked += 1
        for k in ("creator", "year"):
            if not e.get(k) and c.get(k):
                e[k] = c[k]
        if c.get("source_id"):
            e["source"], e["source_id"] = c["source"], c["source_id"]
            if c.get("link"):
                e["link"] = c["link"]
        if c.get("cover_url") and store_cover(e, c["cover_url"]):
            done += 1
    if looked:
        save_and_build(data, f"filled in {done} cover{'s' if done != 1 else ''}")


# ───────────────────────── posts, right now, links ─────────────────────────

def write_post(data):
    title = text("title?", instruction="(enter for none)")
    body = text("what's on your mind?", instruction="(type it, or type e and press enter to open your text editor)")
    if body.lower() == "e":
        body = open_editor("")
    if not body and not title:
        say("  empty post, nothing saved.")
        return
    say("─" * 46)
    if title:
        say(f" {title}")
    say(" " + body[:200].replace("\n", " ") + ("…" if len(body) > 200 else ""))
    say("─" * 46)
    if not confirm("post it and rebuild the site?"):
        return
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    data["posts"].append(dict(id=unique_id(data, f"note-{stamp}"), title=title, text=body, posted=now_iso()))
    save_and_build(data, "new post")


def edit_post(data):
    if not data["posts"]:
        say("  there are no posts yet.")
        return
    ps = sorted(data["posts"], key=lambda p: p["posted"], reverse=True)
    pid = select("which post?", [Choice(f"{p['posted'][:10]}  {(p.get('title') or p['text'])[:50]}", value=p["id"]) for p in ps], search=True)
    p = next(x for x in data["posts"] if x["id"] == pid)
    what = select("what do you want to change?", ["the text", "the title", "delete this post", "never mind"])
    if what == "the text":
        p["text"] = open_editor(p["text"])
    elif what == "the title":
        p["title"] = text("title?", default=p.get("title", ""))
    elif what == "delete this post":
        if not confirm("delete it for good?", default=False):
            return
        data["posts"].remove(p)
    else:
        return
    save_and_build(data, "updated a post")


def edit_now(data):
    say("  the right now box also shows what you're reading, watching and playing automatically.")
    while True:
        for n in data["now"]:
            say(f"  {n['label']}: {n['value']}")
        what = select("change what?", [Choice(f"edit “{n['label']}”", value=i) for i, n in enumerate(data["now"])] +
                      ["add a line", "done"], default="done")
        if what == "done":
            break
        if what == "add a line":
            label = text("label?", instruction="(like feeling, or drinking)", validate=v_nonempty)
            data["now"].append(dict(label=label, value=text(f"{label}?", validate=v_nonempty)))
        else:
            n = data["now"][what]
            value = text(f"{n['label']}?", default=n["value"], instruction="(empty removes the line)")
            if value:
                n["value"] = value
            else:
                data["now"].pop(what)
    save_and_build(data, "updated the right now box")


def edit_links(data):
    say("  links in the “elsewhere” group also show in the sidebar.")
    while True:
        for l in data["links"]:
            say(f"  [{l['group']}] {l['label']} → {l['url']}")
        what = select("change what?", ["add a link"] +
                      [Choice(f"edit {l['label']}", value=i) for i, l in enumerate(data["links"])] + ["done"], default="done")
        if what == "done":
            break
        if what != "add a link":
            how = select(f"{data['links'][what]['label']}:", ["edit it", "remove it", "never mind"])
            if how == "remove it":
                data["links"].pop(what)
                continue
            if how == "never mind":
                continue
        link = {} if what == "add a link" else data["links"][what]
        groups = sorted({l["group"] for l in data["links"]} | {"elsewhere"})
        g = select("which group?", groups + ["a new group"], default=link.get("group", "elsewhere"))
        if g == "a new group":
            g = text("group name?", validate=v_nonempty)
        link["group"] = g
        link["label"] = text("label?", default=link.get("label", ""), validate=v_nonempty)
        link["url"] = text("address?", default=link.get("url", ""), validate=v_nonempty,
                           instruction="(a web address, or mailto:you@example.com for email)")
        link["note"] = text("short note?", default=link.get("note", ""), instruction="(enter to skip)")
        if what == "add a link":
            data["links"].append(link)
    save_and_build(data, "updated the links")


def edit_made(data):
    say("  this is the text on the “made” page. a blank line starts a new paragraph;")
    say("  *italic*, **bold** and [link text](https://…) work too.")
    if data["made"]:
        what = select("the made page:", ["edit it in your text editor", "clear it", "never mind"])
        if what == "never mind":
            return
        data["made"] = "" if what == "clear it" else open_editor(data["made"])
    else:
        data["made"] = open_editor("")
    save_and_build(data, "updated the made page")


# ───────────────────────── deleting ─────────────────────────

def backup(data):
    """Keep a copy of the data before deleting, in data/backups/ (not uploaded)."""
    folder = DATA_FILE.parent / "backups"
    folder.mkdir(exist_ok=True)
    stamp = f"{dt.datetime.now():%Y%m%d-%H%M%S}"
    path, i = folder / f"entries-{stamp}.json", 2
    while path.exists():
        path, i = folder / f"entries-{stamp}-{i}.json", i + 1
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def prune_covers(data):
    """Delete cover files that no entry uses any more."""
    used = {(DOCS / e["cover"]).resolve() for e in data["entries"] if e.get("cover")}
    removed = 0
    if COVERS.exists():
        for f in COVERS.iterdir():
            if f.is_file() and f.name != ".gitkeep" and f.resolve() not in used:
                f.unlink()
                removed += 1
    return removed


def everything_list(data):
    """Every deletable thing, as checkbox choices."""
    choices = []
    for e in sorted(data["entries"], key=lambda e: e.get("added", ""), reverse=True):
        choices.append(Choice(f"{e['type']:<7} {entry_label(e)}", value=("entry", e["id"])))
    for p in sorted(data["posts"], key=lambda p: p["posted"], reverse=True):
        label = (p.get("title") or re.sub(r"[*_]", "", p["text"]).replace("\n", " "))[:50]
        choices.append(Choice(f"post    {p['posted'][:10]}  {label}", value=("post", p["id"])))
    for i, l in enumerate(data["links"]):
        choices.append(Choice(f"link    [{l['group']}] {l['label']}", value=("link", i)))
    for i, n in enumerate(data["now"]):
        choices.append(Choice(f"now     {n['label']}: {n['value']}", value=("now", i)))
    if data["made"]:
        preview = data["made"].replace("\n", " ")
        choices.append(Choice(f"made    page text: {preview[:40]}{'…' if len(preview) > 40 else ''}", value=("made", 0)))
    return choices


def delete_things(data):
    choices = everything_list(data)
    if not choices:
        say("  there's nothing to delete: the site is empty.")
        return
    how = select("delete what?", [
        "pick things from a list",
        "everything (entries, posts, links, right now, made page and covers)",
        "never mind"])
    if how == "never mind":
        return
    if how.startswith("everything"):
        if not confirm(f"delete all {len(choices)} things and every cover, so the site starts empty?", default=False):
            return
        path = backup(data)
        data.update(now=[], links=[], entries=[], posts=[], made="")
    else:
        picks = ask(questionary.checkbox(
            "which ones?", choices=choices, qmark=QMARK, style=STYLE,
            use_search_filter=True, use_jk_keys=False,
            instruction="(space ticks, type to filter, enter when done)"))
        if not picks:
            say("  nothing ticked, nothing deleted.")
            return
        names = {c.value: c.title for c in choices}
        for v in picks:
            say(f"  ✗ {names[v].strip()}")
        if not confirm(f"delete {'this' if len(picks) == 1 else f'these {len(picks)}'}?", default=False):
            return
        path = backup(data)
        gone = set(picks)
        data["entries"] = [e for e in data["entries"] if ("entry", e["id"]) not in gone]
        data["posts"] = [p for p in data["posts"] if ("post", p["id"]) not in gone]
        data["links"] = [l for i, l in enumerate(data["links"]) if ("link", i) not in gone]
        data["now"] = [n for i, n in enumerate(data["now"]) if ("now", i) not in gone]
        if ("made", 0) in gone:
            data["made"] = ""
    n = prune_covers(data)
    save_and_build(data, "deleted" + (f", plus {n} cover{'s' if n != 1 else ''}" if n else ""))
    say(f"  (a copy of everything from before is in data/backups/{path.name}, just in case)")


# ───────────────────────── building the site ─────────────────────────

def feed_items(data):
    items = [("entry", e) for e in data["entries"] if e.get("home") and e.get("posted")]
    items += [("post", p) for p in data["posts"]]
    items.sort(key=lambda t: t[1]["posted"], reverse=True)
    return items


def build_feed(data):
    site = CONF.get("site", {})
    base = (site.get("url") or "https://example.github.io/sofi-blog").rstrip("/")
    style = site.get("default_style", "witchy")
    title = site.get("title", "Sofia’s little grimoire")
    out = []
    for kind, x in feed_items(data)[:30]:
        if kind == "entry":
            verb = VERBS[x["type"]].get(x.get("status", ""), "")
            t = f"{verb} {x['title']}".strip()
            desc = entry_label(x) + (f" {stars(x['rating'])}" if x.get("rating") is not None else "")
            if x.get("review"):
                desc += "\n\n" + x["review"]
        else:
            t = x.get("title") or re.sub(r"[*_]", "", x["text"]).split("\n")[0]
            if len(t) > 70:
                t = t[:70].rsplit(" ", 1)[0] + "…"
            desc = x["text"]
        when = dt.datetime.fromisoformat(x["posted"])
        if when.tzinfo is None:
            when = when.astimezone()
        html_desc = "".join(f"<p>{xml_escape(p).replace(chr(10), '<br>')}</p>" for p in desc.split("\n\n"))
        out.append(
            f"<item><title>{xml_escape(t)}</title><link>{base}/{style}/#post-{x['id']}</link>"
            f"<guid isPermaLink=\"false\">{x['id']}</guid><pubDate>{format_datetime(when)}</pubDate>"
            f"<description>{xml_escape(html_desc)}</description></item>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
            f"<title>{xml_escape(title)}</title><link>{base}/</link>"
            f"<description>books, films, series, albums, games and writing</description>"
            + "\n".join(out) + "</channel></rss>\n")


def build(data):
    reload_config()
    SHARED.mkdir(parents=True, exist_ok=True)
    site = CONF.get("site", {})
    payload = dict(
        site=dict(title=site.get("title", "Sofia’s little grimoire")),
        music=music_source()[0],
        now=data["now"], links=data["links"], entries=data["entries"], posts=data["posts"], made=data["made"],
        built=now_iso())
    js = ("/* made by sofi-blog.py from data/entries.json: run ./sofi-blog.sh instead of editing this */\n"
          "window.SOFIBLOG = " + json.dumps(payload, ensure_ascii=False, indent=1).replace("</", "<\\/") + ";\n")
    (SHARED / "data.js").write_text(js, encoding="utf-8")
    (DOCS / "feed.xml").write_text(build_feed(data), encoding="utf-8")
    (DOCS / ".nojekyll").touch()
    style = site.get("default_style", "witchy")
    (DOCS / "index.html").write_text(
        f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>{payload["site"]["title"]}</title>'
        f'<meta http-equiv="refresh" content="0; url={style}/"></head>'
        f'<body><a href="{style}/">enter the site</a></body></html>\n', encoding="utf-8")


def save_and_build(data, what="saved"):
    save_data(data)
    build(data)
    say(f"  ✦ {what}. the site is rebuilt.")
    music, note = music_source()
    where = {"youtube": "YouTube", "soundcloud": "SoundCloud"}.get(music.get("provider"), "")
    if music and not note:
        say(f"  ♪ music: {where}, {music['playlist']}")
    else:
        say(f"  ♪ music: {note}")


def preview(_data):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(DOCS))
    handler.log_message = lambda *a, **k: None
    for port in range(8000, 8020):
        try:
            server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
            break
        except OSError:
            continue
    else:
        say("  couldn't find a free port for the preview.")
        return
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://localhost:{port}/"
    say(f"  the site is running at {url}")
    webbrowser.open(url)
    try:
        input("  press enter to stop the preview…")
    except (KeyboardInterrupt, EOFError):
        pass
    server.shutdown()


def publish(_data):
    if not (ROOT / ".git").exists():
        say("  this folder isn't a git repository yet. the README has the one-time GitHub Pages setup.")
        return
    msg = text("describe the update?", default="update the site")
    for cmd in (["git", "add", "-A"], ["git", "commit", "-m", msg], ["git", "push"]):
        r = subprocess.run(cmd, cwd=ROOT)
        if r.returncode != 0 and cmd[1] != "commit":
            say("  that didn't work; the message above says why.")
            return
    say("  ✦ published. GitHub Pages usually updates within a minute or two.")


# ───────────────────────── main menu ─────────────────────────

MENU = [
    ("add an entry", add_entry),
    ("edit an entry", edit_entry),
    ("write a text post", write_post),
    ("edit a text post", edit_post),
    ("update the right now box", edit_now),
    ("edit links", edit_links),
    ("edit the made page", edit_made),
    ("delete things", delete_things),
    ("fill in missing covers", fill_missing),
    ("preview the site in your browser", preview),
    ("publish to GitHub", publish),
    ("rebuild the site", lambda d: save_and_build(d, "rebuilt")),
]


def main():
    data = load_data()
    say("\n  ✦ sofi-blog ✦  (arrows to move, enter to pick, Ctrl+C to go back)\n")
    while True:
        try:
            pick = select("what do you want to do?", [m[0] for m in MENU] + [Separator(), "quit"])
        except Cancel:
            break
        if pick == "quit":
            break
        try:
            dict(MENU)[pick](data)
        except Cancel:
            say("  ok, back to the menu.")
            data = load_data()  # drop anything half-done
        say()


if __name__ == "__main__":
    main()
