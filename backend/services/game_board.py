"""Deterministic daily board + title matching (extracted from v1 main.py)."""
import os
import asyncio
import datetime
import re
from zoneinfo import ZoneInfo

from rapidfuzz import fuzz
from dotenv import load_dotenv
from services.tmdb_utils import search_actor_by_name, get_actor_filmography, get_actor_details

load_dotenv()

TMDB_API_KEY = os.getenv("TMDB_API_KEY")
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p"

# All "daily" logic (rotation, caching) rolls over at midnight US Eastern
EASTERN = ZoneInfo("America/New_York")

_raw_override = os.getenv("ACTOR_OVERRIDE", "").strip()
if not _raw_override:
    ACTOR_OVERRIDE = 19292  # Adam Sandler — launch actor; set env var or remove to rotate
else:
    try:
        ACTOR_OVERRIDE = int(_raw_override)
    except ValueError:
        ACTOR_OVERRIDE = _raw_override

# ----------------------------------------------------------------------
# DAILY CACHE
# ----------------------------------------------------------------------
_cache = {}  # actor_id -> {"date": "YYYY-MM-DD", "movies": [...], "details": {...}}


def board_date_key() -> str:
    """Today's date in US Eastern — the key for daily actor rotation & cache."""
    return datetime.datetime.now(EASTERN).strftime("%Y-%m-%d")


ACTOR_LIST = [
    31,     # Tom Hanks
    2888,   # Will Smith
    85,     # Johnny Depp
    1892,   # Matt Damon
    192,    # Morgan Freeman
    10859,  # Ryan Reynolds
    380,    # Robert De Niro
    6193,   # Leonardo DiCaprio
    287,    # Brad Pitt
    62,     # Bruce Willis
    2231,   # Samuel L. Jackson
    2963,   # Nicolas Cage
    6384,   # Keanu Reeves
    3223,   # Robert Downey Jr.
    1245,   # Scarlett Johansson
    54693,  # Emma Stone
    10990,  # Emma Watson
    72129,  # Jennifer Lawrence
    5064,   # Meryl Streep
    5292,   # Denzel Washington
    # --- 90s / 2000s era stars ---
    500,    # Tom Cruise
    3,      # Harrison Ford
    1204,   # Julia Roberts
    18277,  # Sandra Bullock
    206,    # Jim Carrey
    2157,   # Robin Williams
    934,    # Russell Crowe
    4173,   # Anthony Hopkins
    1038,   # Jodie Foster
    1158,   # Al Pacino
    514,    # Jack Nicholson
    2461,   # Mel Gibson
    1100,   # Arnold Schwarzenegger
    3896,   # Liam Neeson
    204,    # Kate Winslet
    819,    # Edward Norton
    880,    # Ben Affleck
    11701,  # Angelina Jolie
    524,    # Natalie Portman
    3894,   # Christian Bale
]


async def get_daily_actor_id() -> int:
    """Resolve today's actor ID (override or rotation)."""
    if ACTOR_OVERRIDE is not None:
        if isinstance(ACTOR_OVERRIDE, int):
            return ACTOR_OVERRIDE
        search_results = await search_actor_by_name(ACTOR_OVERRIDE)
        if not search_results:
            raise ValueError(f"Actor '{ACTOR_OVERRIDE}' not found on TMDb")
        return search_results[0]["id"]
    day_of_year = datetime.datetime.now(EASTERN).timetuple().tm_yday
    return ACTOR_LIST[day_of_year % len(ACTOR_LIST)]


async def get_cached_actor_details(actor_id: int) -> dict:
    today = board_date_key()
    entry = _cache.get(actor_id)
    if entry and entry["date"] == today and "details" in entry:
        return entry["details"]
    details = await get_actor_details(actor_id)
    if entry and entry["date"] == today:
        entry["details"] = details
    else:
        _cache[actor_id] = {"date": today, "details": details}
    return details


async def warm_daily_cache():
    """Pre-fetch today's actor details + filmography. Safe to call often."""
    try:
        actor_id = await get_daily_actor_id()
        today = board_date_key()
        entry = _cache.get(actor_id)
        if entry and entry["date"] == today and "details" in entry:
            return
        details = await get_actor_details(actor_id)
        movies = await get_actor_filmography(actor_id)
        _cache[actor_id] = {"date": today, "movies": movies, "details": details}
    except Exception:
        pass


async def get_ranked_board(actor_id: int) -> list[dict]:
    """Deterministically ranked board (popularity desc, movie id asc tiebreak)."""
    today = board_date_key()
    entry = _cache.get(actor_id)

    if entry and entry["date"] == today and "movies" in entry:
        movies = entry["movies"]
    else:
        movies = await get_actor_filmography(actor_id)
        if entry and entry["date"] == today:
            entry["movies"] = movies
        else:
            _cache[actor_id] = {"date": today, "movies": movies}

    available_movies = sorted(
        movies,
        key=lambda m: (-(m.get("popularity") or 0), m.get("id") or 0)
    )

    total = len(available_movies)
    ranked_movies = []
    for rank_idx, movie in enumerate(available_movies):
        rank = rank_idx + 1
        percentage = max(5, int(((total - rank_idx) / total) * 100))
        poster_path = movie.get("poster_path")
        poster_url = f"{TMDB_IMAGE_BASE_URL}/w92{poster_path}" if poster_path else None
        release_date = movie.get("release_date") or ""
        ranked_movies.append({
            "title": movie["title"],
            "id": movie["id"],
            "rank": rank,
            "percentage": percentage,
            "poster_url": poster_url,
            "year": release_date[:4] or None,
        })

    return ranked_movies


# ----------------------------------------------------------------------
# TITLE NORMALIZATION & MATCHING (unchanged from v1)
# ----------------------------------------------------------------------

LEADING_ARTICLES = ("the ", "a ", "an ")

WORD_TO_NUM = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
    "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
    "eighteen": "18", "nineteen": "19", "twenty": "20"
}
ROMAN_TO_NUM = {
    "i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5",
    "vi": "6", "vii": "7", "viii": "8", "ix": "9", "x": "10",
    "xi": "11", "xii": "12"
}


def _normalize(title: str) -> str:
    t = title.lower().strip()
    t = t.replace("&", " and ")
    t = re.sub(r"[^\w\s]", " ", t)
    tokens = []
    for tok in t.split():
        if tok in WORD_TO_NUM:
            tokens.append(WORD_TO_NUM[tok])
        elif tok in ROMAN_TO_NUM:
            tokens.append(ROMAN_TO_NUM[tok])
        else:
            tokens.append(tok)
    return " ".join(tokens)


def _strip_article(title: str) -> str:
    for article in LEADING_ARTICLES:
        if title.startswith(article):
            return title[len(article):]
    return title


def _title_variants(title: str) -> tuple[list[str], list[str]]:
    """Returns (primary, heads): primary = full + colon-stripped variants;
    heads = short first-3/4-word variants of long titles (fuzzy only)."""
    norm = _normalize(title)
    primary = [norm]

    if ':' in title:
        main_part = _normalize(title.split(':', 1)[0])
        if main_part and main_part != norm:
            primary.append(main_part)

    heads = []
    words = norm.split()
    if len(words) >= 5:
        for head in (' '.join(words[:4]), ' '.join(words[:3])):
            if head not in primary and head not in heads:
                heads.append(head)

    return primary, heads


def find_title_match(guess: str, choices) -> str | None:
    """Match a guess against candidate titles (exact tiers, then fuzzy)."""
    norm_guess = _normalize(guess)
    choice_variants = {c: _title_variants(c) for c in choices}

    # Tier 1a: exact match on the full normalized title
    for choice, (primary, _) in choice_variants.items():
        if primary[0] == norm_guess:
            return choice
        if _strip_article(primary[0]) == norm_guess:
            return choice
        if primary[0] == _strip_article(norm_guess):
            return choice

    # Tier 1b: exact match on colon-stripped main parts
    for choice, (primary, _) in choice_variants.items():
        for variant in primary[1:]:
            if variant == norm_guess:
                return choice
            if _strip_article(variant) == norm_guess:
                return choice
            if variant == _strip_article(norm_guess):
                return choice

    # Tier 2: fuzzy match against all variants
    best_choice = None
    best_score = 0
    best_variant_len = 0
    for choice, (primary, heads) in choice_variants.items():
        for variant in primary + heads:
            score = fuzz.token_set_ratio(norm_guess, variant)
            if score > best_score:
                best_score = score
                best_choice = choice
                best_variant_len = len(variant)

    if best_score < 82:
        return None
    if len(norm_guess) < 0.4 * best_variant_len:
        return None
    return best_choice
