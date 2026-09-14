import os
import sqlite3
from pathlib import Path
import re
import math
import asyncio
import aiohttp
import json
import re
import html
import time
from pathlib import Path

from difflib import SequenceMatcher
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv

from zoneinfo import ZoneInfo
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from urllib.parse import quote



# ============================================================
# FOOTBALL AI ANALYST V47
# ============================================================
# V47
#
# + Market-aware Value rankingainian / English / fuzzy search
# + TOP-5 leagues
# + Recent form
# + Home / away form
# + H2H
# + Opponent strength
# + Separate attack / defence model
# + Goals by halves
# + Separate Over / Under model
# + Separate BTTS model
# + xG
# + Poisson
# + Most likely score
# + Real bookmaker odds
# + Value
# + Confidence
# ============================================================


load_dotenv()


# ============================================================
# CONFIG
# ============================================================

FOOTBALL_DATA_TOKEN = os.getenv("FOOTBALL_DATA_TOKEN")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
BBS_API_KEY = os.getenv("BBS_API_KEY")



if not FOOTBALL_DATA_TOKEN:
    raise RuntimeError("Не знайдено FOOTBALL_DATA_TOKEN у .env")

if not ODDS_API_KEY:
    raise RuntimeError("Не знайдено ODDS_API_KEY у .env")


FOOTBALL_BASE_URL = "https://api.football-data.org/v4"
ODDS_BASE_URL = "https://api.the-odds-api.com/v4"
BBS_BASE_URL = "https://api.bigballsdata.com/v1"


# ============================================================
# SEASONS
# ============================================================

CURRENT_SEASON = 2026

HISTORY_SEASONS = [
    2026,
    2025,
    2024,
]


# ============================================================
# TOP 5
# ============================================================

TOP5_LEAGUES = {

    "CL": {
        "name": "Європа — Ліга чемпіонів UEFA",
        "odds_key": "soccer_uefa_champs_league",
    },

    "PL": {
        "name": "Англія — Premier League",
        "odds_key": "soccer_epl",
    },

    "PD": {
        "name": "Іспанія — La Liga",
        "odds_key": "soccer_spain_la_liga",
    },

    "SA": {
        "name": "Італія — Serie A",
        "odds_key": "soccer_italy_serie_a",
    },

    "BL1": {
        "name": "Німеччина — Bundesliga",
        "odds_key": "soccer_germany_bundesliga",
    },

    "FL1": {
        "name": "Франція — Ligue 1",
        "odds_key": "soccer_france_ligue_one",
    },
}


# ============================================================
# UEFA CHAMPIONS LEAGUE
# ============================================================
# football-data.org: CL
# The Odds API: soccer_uefa_champs_league
# Реальні коефіцієнти беруться з Odds API.


# ============================================================
# MODEL SETTINGS
# ============================================================

FORM_MATCHES = 5
HISTORY_FORM_MATCHES = 10
H2H_MATCHES = 10

MIN_HISTORY = 5

MIN_VALUE = 0.03
MIN_CONFIDENCE = 55.0

MAX_GOALS = 10


# ============================================================
# CACHE
# ============================================================

TEAM_CACHE = {}
HISTORY_CACHE = {}
COMPETITION_CACHE = {}
ODDS_CACHE = {}
H2H_CACHE = {}

# Persistent SMART CACHE.
# Stored beside this backend file so a server restart does not throw away
# successfully collected Football-Data / FotMob data.
CACHE_DIR = Path(__file__).resolve().parent / ".football_ai_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

CACHE_TTL_FOOTBALL_HISTORY = 12 * 60 * 60
CACHE_TTL_FOTMOB_TEAM = 6 * 60 * 60
CACHE_TTL_FOTMOB_MATCH = 30 * 24 * 60 * 60


def _cache_safe_key(value):
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value))


def _disk_cache_path(key):
    return CACHE_DIR / f"{_cache_safe_key(key)}.json"


def _disk_cache_load(key, ttl=None, allow_stale=False):
    path = _disk_cache_path(key)
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        saved_at = float(data.get("_saved_at", 0) or 0)
        if ttl is not None and not allow_stale:
            if saved_at <= 0 or (time.time() - saved_at) > ttl:
                return None
        return data.get("payload")
    except Exception:
        return None


def _disk_cache_save(key, payload):
    path = _disk_cache_path(key)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        body = {
            "_saved_at": time.time(),
            "payload": payload,
        }
        tmp.write_text(
            json.dumps(body, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        tmp.replace(path)
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass


# ============================================================
# SESSIONS
# ============================================================

FOOTBALL_SESSION = None
ODDS_SESSION = None
SOFASCORE_SESSION = None
BBS_SESSION = None
BBS_AUTH_FAILED = False
BBS_MATCH_STATS_CACHE = {}


async def get_football_session():

    global FOOTBALL_SESSION

    if FOOTBALL_SESSION is None:

        FOOTBALL_SESSION = aiohttp.ClientSession(
            headers={
                "X-Auth-Token": FOOTBALL_DATA_TOKEN
            }
        )

    return FOOTBALL_SESSION


async def get_odds_session():

    global ODDS_SESSION

    if ODDS_SESSION is None:

        ODDS_SESSION = aiohttp.ClientSession()

    return ODDS_SESSION


async def get_bbs_session():
    global BBS_SESSION

    if BBS_SESSION is None:
        if not BBS_API_KEY:
            return None
        BBS_SESSION = aiohttp.ClientSession(
            headers={
                "Authorization": f"Bearer {BBS_API_KEY}",
                "Accept": "application/json",
            }
        )

    return BBS_SESSION


async def bbs_api_get(path, params=None):
    global BBS_AUTH_FAILED

    if BBS_AUTH_FAILED:
        return None

    session = await get_bbs_session()
    if session is None:
        return None

    url = f"{BBS_BASE_URL}{path}"

    async with session.get(
        url,
        params=params or {},
        timeout=aiohttp.ClientTimeout(total=20),
    ) as response:
        text = await response.text()

        if response.status == 401:
            BBS_AUTH_FAILED = True
            raise RuntimeError(
                "BBS HTTP 401: invalid API key. "
                "Перевір BBS_API_KEY у .env (ключ має починатися з bbs_live_)."
            )

        if response.status == 429:
            retry_after = response.headers.get("Retry-After", "5")
            try:
                delay = max(1, min(60, int(float(retry_after))))
            except (TypeError, ValueError):
                delay = 5
            await asyncio.sleep(delay)
            raise RuntimeError(
                f"BBS HTTP 429: rate limit, retry-after={delay}s"
            )

        if response.status != 200:
            raise RuntimeError(
                f"BBS HTTP {response.status}: {text[:500]}"
            )

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"BBS invalid JSON: {text[:500]}"
            ) from e


async def get_sofascore_session():
    """Окрема сесія SofaScore з вимкненою перевіркою SSL.

    На деяких Windows-системах локальний certificate store не бачить
    ланцюжок сертифікатів SofaScore, через що виникає
    SSLCertVerificationError. Для цього API використовуємо окрему
    aiohttp-сесію з TCPConnector(ssl=False), не змінюючи інші API.
    """
    global SOFASCORE_SESSION

    if SOFASCORE_SESSION is None:
        SOFASCORE_SESSION = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=False),
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": "https://www.sofascore.com/",
                "Origin": "https://www.sofascore.com",
                "Accept-Language": "en-US,en;q=0.9,uk;q=0.8,ru;q=0.7",
            },
        )

    return SOFASCORE_SESSION


async def close_sessions():

    global FOOTBALL_SESSION
    global ODDS_SESSION
    global SOFASCORE_SESSION

    if FOOTBALL_SESSION:

        await FOOTBALL_SESSION.close()
        FOOTBALL_SESSION = None

    if ODDS_SESSION:

        await ODDS_SESSION.close()
        ODDS_SESSION = None

    if SOFASCORE_SESSION:

        await SOFASCORE_SESSION.close()
        SOFASCORE_SESSION = None

    global BBS_SESSION
    if BBS_SESSION:
        await BBS_SESSION.close()
        BBS_SESSION = None


# ============================================================
# NORMALIZE
# ============================================================

def normalize_name(name):

    if not name:
        return ""

    name = str(name).lower().strip()

    replacements = {

        "&": " and ",

        "á": "a",
        "à": "a",
        "ä": "a",
        "â": "a",
        "ã": "a",
        "å": "a",

        "é": "e",
        "è": "e",
        "ë": "e",
        "ê": "e",

        "í": "i",
        "ì": "i",
        "ï": "i",
        "î": "i",

        "ó": "o",
        "ò": "o",
        "ö": "o",
        "ô": "o",
        "õ": "o",

        "ú": "u",
        "ù": "u",
        "ü": "u",
        "û": "u",

        "ñ": "n",
        "ç": "c",

        "ý": "y",
        "ÿ": "y",

        "ć": "c",
        "č": "c",
        "š": "s",
        "ž": "z",
        "đ": "d",
        "ł": "l",

        "’": " ",
        "'": " ",
        "-": " ",
        "_": " ",
        ".": " ",
    }

    for old, new in replacements.items():
        name = name.replace(old, new)

    name = re.sub(
        r"[^a-zа-яіїєґ0-9 ]+",
        " ",
        name
    )

    # Часті службові суфікси, які відрізняються між football-data.org
    # та The Odds API: FC, CF, AFC, SC, FK тощо.
    name = re.sub(
        r"\b(fc|cf|afc|sc|fk|sk|sv|kv|ac|calcio|club|osc|balompie|balompié)\b",
        " ",
        name
    )

    name = re.sub(
        r"\s+",
        " ",
        name
    )

    return name.strip()


# ============================================================
# UKRAINIAN TRANSLITERATION
# ============================================================

UKR_TO_LATIN = {

    "а": "a",
    "б": "b",
    "в": "v",
    "г": "h",
    "ґ": "g",
    "д": "d",
    "е": "e",
    "є": "ye",
    "ж": "zh",
    "з": "z",
    "и": "y",
    "і": "i",
    "ї": "yi",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "kh",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "shch",
    "ь": "",
    "ю": "yu",
    "я": "ya",
    "ё": "yo",
    "э": "e",
    "ы": "y",
    "ъ": "",
}


def transliterate_ukrainian(text):

    text = normalize_name(text)

    result = []

    for char in text:

        result.append(
            UKR_TO_LATIN.get(
                char,
                char
            )
        )

    return re.sub(
        r"\s+",
        " ",
        "".join(result)
    ).strip()


# ============================================================
# ALIASES
# ============================================================

ALIASES = {

    "арсенал": ["arsenal", "arsenal fc"],
    "астон вілла": ["aston villa", "aston villa fc"],
    "брентфорд": ["brentford", "brentford fc"],
    "брайтон": [
        "brighton",
        "brighton and hove albion",
        "brighton hove albion",
    ],
    "бернлі": ["burnley", "burnley fc"],
    "борнмут": ["bournemouth", "afc bournemouth"],
    "вест хем": ["west ham", "west ham united"],
    "вулвергемптон": [
        "wolves",
        "wolverhampton",
        "wolverhampton wanderers",
    ],
    "вулверхемптон": [
        "wolves",
        "wolverhampton",
        "wolverhampton wanderers",
    ],
    "кристал пелес": ["crystal palace"],
    "крістал пелес": ["crystal palace"],
    "ліверпуль": ["liverpool", "liverpool fc"],
    "манчестер сіті": ["manchester city"],
    "ман сіті": ["manchester city"],
    "манчестер юнайтед": ["manchester united"],
    "ман юнайтед": ["manchester united"],
    "ньюкасл": ["newcastle", "newcastle united"],
    "ноттінгем": ["nottingham forest"],
    "нотвінгем": ["nottingham forest"],
    "тоттенгем": ["tottenham", "tottenham hotspur"],
    "тоттенхем": ["tottenham", "tottenham hotspur"],
    "челсі": ["chelsea"],
    "фулгем": ["fulham"],
    "фулхем": ["fulham"],

    "барселона": ["barcelona", "fc barcelona", "barca"],
    "реал мадрид": ["real madrid", "real madrid cf"],
    "реал": ["real madrid"],
    "атлетіко мадрид": [
        "atletico madrid",
        "atletico de madrid",
    ],
    "атлетико": ["atletico madrid"],
    "севілья": ["sevilla", "sevilla fc"],
    "вільярреал": ["villarreal", "villarreal cf"],
    "бетіс": ["real betis", "real betis balompie"],
    "бетіc": ["real betis"],
    "реал бетіс": ["real betis"],
    "валенсія": ["valencia", "valencia cf"],
    "реал сосьєдад": ["real sociedad"],
    "більбао": ["athletic club", "athletic bilbao"],
    "атлетік": ["athletic club", "athletic bilbao"],
    "осасуна": ["osasuna", "ca osasuna"],
    "мальорка": ["mallorca", "rcd mallorca"],
    "майорка": ["mallorca", "rcd mallorca"],
    "хетафе": ["getafe", "getafe cf"],
    "селта": ["celta", "celta vigo", "rc celta"],
    "жирона": ["girona", "girona fc"],
    "райо вальєкано": ["rayo vallecano"],
    "алмерія": ["almeria", "ud almeria"],
    "малага": ["malaga", "malaga cf"],
    "еспаньйол": ["espanyol", "rcd espanyol"],

    "ювентус": ["juventus", "juventus fc"],
    "інтер": [
        "inter",
        "inter milan",
        "internazionale",
        "fc internazionale milano",
    ],
    "інтер мілан": [
        "inter",
        "inter milan",
        "internazionale",
    ],
    "мілан": ["milan", "ac milan"],
    "рома": ["roma", "as roma"],
    "лаціо": ["lazio", "ss lazio"],
    "наполи": ["napoli", "ssc napoli"],
    "неаполь": ["napoli", "ssc napoli"],
    "фіорентина": ["fiorentina", "acf fiorentina"],
    "болонья": ["bologna"],
    "торіно": ["torino"],
    "дженоа": ["genoa"],
    "генуя": ["genoa"],
    "аталанта": ["atalanta"],
    "удінезе": ["udinese"],
    "лічче": ["lecce"],
    "монца": ["monza"],
    "сардинія": ["cagliari", "cagliari calcio"],

    "баварія": [
        "bayern munich",
        "bayern",
        "fc bayern munich",
    ],
    "бавария": [
        "bayern munich",
        "bayern",
        "fc bayern munich",
    ],
    "боруссія дортмунд": [
        "borussia dortmund",
        "bvb",
        "bvb 09",
    ],
    "боруссия дортмунд": [
        "borussia dortmund",
        "bvb",
    ],
    "дортмунд": ["borussia dortmund", "bvb"],
    "байєр": [
        "bayer leverkusen",
        "bayer 04 leverkusen",
        "bayer",
    ],
    "байер": [
        "bayer leverkusen",
        "bayer 04 leverkusen",
        "bayer",
    ],
    "байєр леверкузен": ["bayer leverkusen"],
    "байер леверкузен": ["bayer leverkusen"],
    "лайпциг": ["rb leipzig", "rasenballsport leipzig"],
    "рб лейпциг": ["rb leipzig"],
    "шальке": ["schalke 04", "fc schalke 04"],
    "вольфсбург": ["wolfsburg", "vfl wolfsburg"],
    "штутгарт": ["stuttgart", "vfb stuttgart"],
    "фрайбург": ["freiburg", "sc freiburg"],
    "хофенгайм": ["hoffenheim", "tsg hoffenheim"],
    "хоффенгайм": ["hoffenheim", "tsg hoffenheim"],
    "майнц": ["mainz", "mainz 05"],
    "вердер": ["werder bremen"],
    "айнтрахт франкфурт": ["eintracht frankfurt"],
    "айнтрахт": ["eintracht frankfurt"],
    "уніон берлін": ["union berlin"],

    "псж": [
        "paris saint germain",
        "paris saint-germain",
        "psg",
    ],
    "парі сен жермен": [
        "paris saint germain",
        "psg",
    ],
    "марсель": [
        "marseille",
        "olympique de marseille",
        "om",
    ],
    "ліон": [
        "lyon",
        "olympique lyonnais",
        "olympique lyon",
        "ol",
    ],
    "ренн": ["rennes", "stade rennais"],
    "монако": ["monaco", "as monaco"],
    "ліль": ["lille", "lille osc", "losc lille"],
    "ніцца": ["nice", "ogc nice"],
    "ланс": ["lens", "rc lens"],
    "тулуза": ["toulouse"],
    "монпельє": ["montpellier"],
    "нанти": ["nantes"],
    "нант": ["nantes"],
    "страсбург": ["strasbourg"],
    "брест": ["brest", "stade brestois 29"],
    "реймс": ["reims", "stade de reims"],
    "осер": ["auxerre", "aj auxerre"],
}


# ============================================================
# UEFA CHAMPIONS LEAGUE 2026/27 — UNIVERSAL TEAM REGISTRY
# ============================================================
# One canonical name for all 36 league-phase teams.
# Used by Telegram input, Football-Data.org, The Odds API and FotMob.
# ============================================================

CL_TEAM_CANONICAL = {
    "aek athens": ["pae aek", "aek", "aek athens", "aek fc"],
    "arsenal": ["arsenal", "arsenal fc"],
    "aston villa": ["aston villa", "aston villa fc"],
    "atletico madrid": ["atletico madrid", "atletico de madrid", "atleti", "club atletico de madrid"],
    "barcelona": ["barcelona", "fc barcelona", "barca"],
    "bayern munich": ["bayern munich", "bayern munchen", "bayern münchen", "bayern", "fc bayern munich", "fc bayern münchen"],
    "bodo glimt": ["bodo glimt", "bodoe glimt", "bodo/glimt", "bodo glimt fk", "fk bodo glimt"],
    "borussia dortmund": ["borussia dortmund", "b. dortmund", "bvb", "bvb 09", "dortmund"],
    "club brugge": ["club brugge", "club brugge kv", "club brugge fc"],
    "como": ["como", "como 1907", "como fc"],
    "fenerbahce": ["fenerbahce", "fenerbahçe", "fenerbahce istanbul", "fenerbahce sk"],
    "feyenoord": ["feyenoord", "feyenoord rotterdam", "feyenoord fc"],
    "galatasaray": ["galatasaray", "galatasaray istanbul", "galatasaray sk"],
    "inter": ["inter", "inter milan", "internazionale", "internazionale milano", "fc internazionale milano", "inter milano"],
    "lask": ["lask", "lask linz", "lask linz fc", "lask linz fk"],
    "leipzig": ["leipzig", "rb leipzig", "rasenballsport leipzig", "rasenballsport leipzig e.v."],
    "lens": ["lens", "rc lens", "racing club de lens"],
    "lille": ["lille", "lille osc", "losc lille", "losc"],
    "liverpool": ["liverpool", "liverpool fc"],
    "manchester city": ["man city", "manchester city", "manchester city fc"],
    "manchester united": ["man utd", "man united", "manchester united", "manchester united fc"],
    "napoli": ["napoli", "ssc napoli", "napoli fc"],
    "paris saint germain": ["paris", "psg", "paris saint germain", "paris saint-germain", "paris sg", "paris saint germain fc"],
    "porto": ["porto", "fc porto", "fc porto portugal"],
    "psv eindhoven": ["psv", "psv eindhoven", "psv eindhoven fc", "psv eindhoven nv"],
    "real betis": ["real betis", "real betis balompie", "real betis balompié", "real betis seville", "real betis sevilla"],
    "real madrid": ["real madrid", "real madrid cf", "real madrid fc"],
    "roma": ["roma", "as roma", "as roma fc", "roma fc"],
    "sabah": ["sabah", "sabah fk", "sabah fc"],
    "shakhtar donetsk": ["shakhtar", "shakhtar donetsk", "shakhtar donetsk fc", "fc shakhtar donetsk"],
    "slavia praha": ["slavia praha", "slavia prague", "slavia", "sk slavia praha"],
    "slovan bratislava": ["slovan bratislava", "s. bratislava", "sk slovan bratislava", "slovan"],
    "sporting cp": ["sporting cp", "sporting lisbon", "sporting clube de portugal", "sporting portugal", "sporting"],
    "stuttgart": ["stuttgart", "vfb stuttgart", "vfb stuttgart 1893"],
    "viking": ["viking", "viking fk", "viking stavanger", "viking fk stavanger"],
    "villarreal": ["villarreal", "villarreal cf", "villarreal club de futbol"],
}

CL_TEAM_LOCAL_ALIASES = {
    "аек афіни": "aek athens", "пае аек": "aek athens", "аек": "aek athens",
    "арсенал": "arsenal", "астон вілла": "aston villa",
    "атлетіко": "atletico madrid", "атлетико": "atletico madrid", "атлетіко мадрид": "atletico madrid", "атлетико мадрид": "atletico madrid",
    "барселона": "barcelona", "баварія": "bayern munich", "бавария": "bayern munich",
    "боруссія дортмунд": "borussia dortmund", "боруссия дортмунд": "borussia dortmund", "дортмунд": "borussia dortmund",
    "бодо глімт": "bodo glimt", "бодо глимт": "bodo glimt", "клуб брюгге": "club brugge", "комо": "como",
    "фенербахче": "fenerbahce", "фенербахче": "fenerbahce", "фейєноорд": "feyenoord", "фейеноорд": "feyenoord", "феєнорд": "feyenoord",
    "галатасарай": "galatasaray", "інтер": "inter", "інтер мілан": "inter", "интер": "inter", "интер милан": "inter",
    "ласк": "lask", "ласк лінц": "lask", "ласк линц": "lask", "лайпциг": "leipzig", "рб лайпциг": "leipzig", "ланс": "lens", "ліль": "lille", "лиль": "lille",
    "ліверпуль": "liverpool", "ливерпуль": "liverpool", "манчестер сіті": "manchester city", "манчестер сити": "manchester city", "ман сіті": "manchester city", "ман сити": "manchester city",
    "манчестер юнайтед": "manchester united", "манчестер юнайтед": "manchester united", "ман юнайтед": "manchester united", "ман юнайтед": "manchester united",
    "наполи": "napoli", "неаполь": "napoli", "псж": "paris saint germain", "парі сен жермен": "paris saint germain", "париж": "paris saint germain", "пари сен жермен": "paris saint germain",
    "порту": "porto", "псв": "psv eindhoven", "псв ейндховен": "psv eindhoven", "реал бетіс": "real betis", "реал бетис": "real betis", "бетіс": "real betis", "бетис": "real betis",
    "реал мадрид": "real madrid", "рома": "roma", "сабах": "sabah", "шахтар": "shakhtar donetsk", "шахтар донецьк": "shakhtar donetsk", "шахтер": "shakhtar donetsk", "шахтер донецк": "shakhtar donetsk",
    "славія прага": "slavia praha", "славия прага": "slavia praha", "славія": "slavia praha", "славия": "slavia praha", "слован братислава": "slovan bratislava", "слован": "slovan bratislava",
    "спортинг": "sporting cp", "спортінг": "sporting cp", "спортинг лісабон": "sporting cp", "спортинг лиссабон": "sporting cp", "штутгарт": "stuttgart", "вікінг": "viking", "викинг": "viking", "вільярреал": "villarreal", "вильярреал": "villarreal",
}


def cl_canonical_team(name):
    n = normalize_name(name)
    if not n:
        return ""
    if n in CL_TEAM_LOCAL_ALIASES:
        return CL_TEAM_LOCAL_ALIASES[n]
    for canonical, aliases in CL_TEAM_CANONICAL.items():
        if n == normalize_name(canonical):
            return canonical
        if any(n == normalize_name(alias) for alias in aliases):
            return canonical
    return ""


# Make the same aliases available to Telegram team search.
for _canonical, _names in CL_TEAM_CANONICAL.items():
    ALIASES.setdefault(_canonical, []).extend(_names)
for _alias, _canonical in CL_TEAM_LOCAL_ALIASES.items():
    ALIASES.setdefault(_alias, []).append(_canonical)


# ============================================================
# RUSSIAN TEAM SEARCH ALIASES
# ============================================================
# Пользователь может вводить названия клубов кириллицей по-русски.
# Значения справа — реальные названия/варианты Football-Data.org.
RUSSIAN_TEAM_ALIASES = {
    # England
    "арсенал": ["arsenal", "arsenal fc"],
    "астон вилла": ["aston villa", "aston villa fc"],
    "брентфорд": ["brentford", "brentford fc"],
    "брайтон": ["brighton", "brighton and hove albion", "brighton hove albion"],
    "бернли": ["burnley", "burnley fc"],
    "борнмут": ["bournemouth", "afc bournemouth"],
    "вест хэм": ["west ham", "west ham united"],
    "вест хем": ["west ham", "west ham united"],
    "вулверхэмптон": ["wolves", "wolverhampton", "wolverhampton wanderers"],
    "вулверхемптон": ["wolves", "wolverhampton", "wolverhampton wanderers"],
    "кристал пэлас": ["crystal palace"],
    "кристал пелас": ["crystal palace"],
    "ливерпуль": ["liverpool", "liverpool fc"],
    "манчестер сити": ["manchester city", "man city"],
    "ман сити": ["manchester city", "man city"],
    "манчестер юнайтед": ["manchester united", "man united", "man utd"],
    "ман юнайтед": ["manchester united", "man united", "man utd"],
    "ньюкасл": ["newcastle", "newcastle united"],
    "ноттингем": ["nottingham forest"],
    "ноттингем форест": ["nottingham forest"],
    "тоттенхэм": ["tottenham", "tottenham hotspur"],
    "тоттенхем": ["tottenham", "tottenham hotspur"],
    "челси": ["chelsea", "chelsea fc"],
    "фулхэм": ["fulham"],
    "фулхем": ["fulham"],
    "эвертон": ["everton", "everton fc"],
    "ипсвич": ["ipswich", "ipswich town"],
    "лидс": ["leeds", "leeds united"],
    "сандерленд": ["sunderland", "sunderland afc"],

    # Spain
    "барселона": ["barcelona", "fc barcelona", "barca"],
    "реал мадрид": ["real madrid", "real madrid cf"],
    "реал": ["real madrid"],
    "атлетико мадрид": ["atletico madrid", "atletico de madrid"],
    "атлетико": ["atletico madrid", "atletico de madrid"],
    "севилья": ["sevilla", "sevilla fc"],
    "вильярреал": ["villarreal", "villarreal cf"],
    "бетис": ["real betis", "real betis balompie", "real betis balompié"],
    "реал бетис": ["real betis", "real betis balompie", "real betis balompié"],
    "валенсия": ["valencia", "valencia cf"],
    "реал сосьедад": ["real sociedad"],
    "атлетик бильбао": ["athletic club", "athletic bilbao"],
    "бильбао": ["athletic club", "athletic bilbao"],
    "атлетик": ["athletic club", "athletic bilbao"],
    "осасуна": ["osasuna", "ca osasuna"],
    "мальорка": ["mallorca", "rcd mallorca"],
    "майорка": ["mallorca", "rcd mallorca"],
    "хетафе": ["getafe", "getafe cf"],
    "селта": ["celta", "celta vigo", "rc celta"],
    "селта виго": ["celta", "celta vigo", "rc celta"],
    "жирона": ["girona", "girona fc"],
    "райо вальекано": ["rayo vallecano"],
    "альмерия": ["almeria", "ud almeria"],
    "малага": ["malaga", "malaga cf"],
    "эспаньол": ["espanyol", "rcd espanyol"],
    "эспаньол барселона": ["espanyol", "rcd espanyol"],
    "алавес": ["alaves", "deportivo alaves", "deportivo alavés"],
    "леванте": ["levante", "levante ud"],
    "эльче": ["elche", "elche cf"],
    "расинг сантандер": ["racing santander", "real racing club de santander"],
    "депортиво": ["deportivo la coruna", "deportivo la coruña"],

    # Italy
    "ювентус": ["juventus", "juventus fc"],
    "интер": ["inter", "inter milan", "internazionale", "fc internazionale milano"],
    "интер милан": ["inter", "inter milan", "internazionale", "fc internazionale milano"],
    "милан": ["milan", "ac milan"],
    "рома": ["roma", "as roma"],
    "лацио": ["lazio", "ss lazio"],
    "наполи": ["napoli", "ssc napoli"],
    "неаполь": ["napoli", "ssc napoli"],
    "фиорентина": ["fiorentina", "acf fiorentina"],
    "болонья": ["bologna"],
    "торино": ["torino"],
    "дженоа": ["genoa"],
    "генуя": ["genoa"],
    "аталанта": ["atalanta"],
    "удинезе": ["udinese"],
    "лечче": ["lecce"],
    "монца": ["monza"],
    "кальяри": ["cagliari", "cagliari calcio"],
    "комо": ["como", "como 1907", "como fc"],
    "парма": ["parma", "parma calcio", "parma calcio 1913"],
    "сассуоло": ["sassuolo", "us sassuolo calcio"],
    "венеция": ["venezia", "venezia fc"],
    "фрозиноне": ["frosinone", "frosinone calcio"],

    # Germany
    "бавария": ["bayern", "bayern munich", "bayern munchen", "bayern münchen", "fc bayern munich"],
    "бавария мюнхен": ["bayern", "bayern munich", "bayern munchen", "bayern münchen"],
    "боруссия дортмунд": ["borussia dortmund", "bvb", "bvb 09"],
    "дортмунд": ["borussia dortmund", "bvb"],
    "байер": ["bayer leverkusen", "bayer 04 leverkusen", "bayer"],
    "байер леверкузен": ["bayer leverkusen", "bayer 04 leverkusen"],
    "лейпциг": ["rb leipzig", "rasenballsport leipzig"],
    "рб лейпциг": ["rb leipzig", "rasenballsport leipzig"],
    "шальке": ["schalke 04", "fc schalke 04"],
    "вольфсбург": ["wolfsburg", "vfl wolfsburg"],
    "штутгарт": ["stuttgart", "vfb stuttgart"],
    "фрайбург": ["freiburg", "sc freiburg"],
    "хоффенхайм": ["hoffenheim", "tsg hoffenheim"],
    "хоффенгайм": ["hoffenheim", "tsg hoffenheim"],
    "майнц": ["mainz", "mainz 05"],
    "вердер": ["werder bremen"],
    "вердер бремен": ["werder bremen"],
    "айнтрахт": ["eintracht frankfurt"],
    "айнтрахт франкфурт": ["eintracht frankfurt"],
    "унион берлин": ["union berlin"],
    "боруссия менхенгладбах": ["borussia monchengladbach", "borussia mönchengladbach", "gladbach"],
    "гладбах": ["borussia monchengladbach", "borussia mönchengladbach", "gladbach"],
    "аугсбург": ["augsburg", "fc augsburg"],
    "кельн": ["koln", "köln", "fc koln", "1. fc köln"],
    "гамбург": ["hamburger sv", "hamburg"],
    "хайденхайм": ["heidenheim", "1. fc heidenheim"],

    # France
    "псж": ["paris saint germain", "paris saint-germain", "psg"],
    "пари сен жермен": ["paris saint germain", "paris saint-germain", "psg"],
    "марсель": ["marseille", "olympique de marseille", "om"],
    "лион": ["lyon", "olympique lyonnais", "olympique lyon"],
    "ренн": ["rennes", "stade rennais"],
    "монако": ["monaco", "as monaco"],
    "лиль": ["lille", "lille osc", "losc lille"],
    "ницца": ["nice", "ogc nice"],
    "ланс": ["lens", "rc lens"],
    "тулуза": ["toulouse"],
    "монпелье": ["montpellier"],
    "нант": ["nantes"],
    "страсбур": ["strasbourg"],
    "страсбург": ["strasbourg"],
    "брест": ["brest", "stade brestois 29"],
    "реймс": ["reims", "stade de reims"],
    "осер": ["auxerre", "aj auxerre"],

    # Champions League / common European clubs
    "шахтер": ["shakhtar", "shakhtar donetsk", "fc shakhtar donetsk"],
    "шахтер донецк": ["shakhtar", "shakhtar donetsk", "fc shakhtar donetsk"],
    "порту": ["porto", "fc porto"],
    "спортинг": ["sporting cp", "sporting lisbon", "sporting clube de portugal"],
    "спортинг лиссабон": ["sporting cp", "sporting lisbon"],
    "галатасарай": ["galatasaray", "galatasaray sk"],
    "фенербахче": ["fenerbahce", "fenerbahçe", "fenerbahce sk"],
    "фейеноорд": ["feyenoord", "feyenoord rotterdam"],
    "псв": ["psv", "psv eindhoven"],
    "клуб брюгге": ["club brugge", "club brugge kv"],
    "славия прага": ["slavia praha", "slavia prague"],
    "слован братислава": ["slovan bratislava", "sk slovan bratislava"],
    "аек афины": ["aek athens", "aek fc"],
    "будё глимт": ["bodo glimt", "bodoe glimt", "bodo/glimt"],
    "бодо глимт": ["bodo glimt", "bodoe glimt", "bodo/glimt"],
}

# Merge Russian aliases into the same universal search dictionary.
# Existing Ukrainian aliases remain untouched.
for _ru_name, _ru_variants in RUSSIAN_TEAM_ALIASES.items():
    _bucket = ALIASES.setdefault(_ru_name, [])
    for _variant in _ru_variants:
        if _variant not in _bucket:
            _bucket.append(_variant)


def build_alias_index():

    index = {}

    for ukrainian, aliases in ALIASES.items():

        key = normalize_name(
            ukrainian
        )

        index[key] = [
            normalize_name(x)
            for x in aliases
            if normalize_name(x)
        ]

    return index


ALIAS_INDEX = build_alias_index()


# ============================================================
# TEAM NAMES
# ============================================================

def get_team_names(team):

    names = []

    for key in (
        "name",
        "shortName",
        "tla",
    ):

        value = team.get(
            key,
            ""
        )

        if value:

            normalized = normalize_name(
                value
            )

            if normalized:
                names.append(normalized)

    return names


# ============================================================
# SIMILARITY
# ============================================================

def similarity(a, b):

    a = normalize_name(a)
    b = normalize_name(b)

    if not a or not b:
        return 0.0

    if a == b:
        return 1.0

    if a in b or b in a:

        shorter = min(
            len(a),
            len(b)
        )

        longer = max(
            len(a),
            len(b)
        )

        if longer == 0:
            return 0.0

        return min(
            0.99,
            0.85 + (
                shorter / longer
            ) * 0.14
        )

    return SequenceMatcher(
        None,
        a,
        b
    ).ratio()


# ============================================================
# SEARCH TEAM
# ============================================================

def search_team(query, teams):

    if not query:
        return None

    original = query.strip()
    normalized = normalize_name(
        original
    )

    if not normalized:
        return None

    # Exact / universal Champions League registry.
    query_cl = cl_canonical_team(original)
    for team in teams:
        names = get_team_names(team)
        if normalized in names:
            return team
        if query_cl and any(cl_canonical_team(name) == query_cl for name in names):
            return team

    # Alias
    aliases = ALIAS_INDEX.get(
        normalized,
        []
    )

    for team in teams:

        names = get_team_names(team)

        for alias in aliases:

            if alias in names:
                return team

            for name in names:

                if similarity(
                    alias,
                    name
                ) >= 0.88:

                    return team

    # Transliteration
    transliterated = transliterate_ukrainian(
        original
    )

    for team in teams:

        for name in get_team_names(team):

            if similarity(
                transliterated,
                name
            ) >= 0.82:

                return team

    # Fuzzy alias
    best_team = None
    best_score = 0.0

    for ukrainian, aliases in ALIASES.items():

        ukrainian_score = similarity(
            normalized,
            ukrainian
        )

        if ukrainian_score < 0.70:
            continue

        for team in teams:

            names = get_team_names(team)

            for alias in aliases:

                alias_score = max(
                    (
                        similarity(alias, name)
                        for name in names
                    ),
                    default=0
                )

                score = (
                    ukrainian_score * 0.40
                    +
                    alias_score * 0.60
                )

                if score > best_score:

                    best_score = score
                    best_team = team

    if (
        best_team
        and
        best_score >= 0.70
    ):

        return best_team

    # Partial
    for team in teams:

        for name in get_team_names(team):

            if (
                normalized in name
                or
                name in normalized
            ):

                return team

    # Final fuzzy
    best_team = None
    best_score = 0.0

    for team in teams:

        for name in get_team_names(team):

            score = similarity(
                normalized,
                name
            )

            if score > best_score:

                best_score = score
                best_team = team

    if (
        best_team
        and
        best_score >= 0.72
    ):

        return best_team

    return None


# ============================================================
# FOOTBALL API
# ============================================================

async def football_api_get(
    url,
    params=None,
    retries=3
):

    session = await get_football_session()

    for attempt in range(retries):

        try:

            async with session.get(
                url,
                params=params,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:

                text = await response.text()

                if response.status == 200:
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        return await response.json(content_type=None)

                if response.status == 429:
                    # FAST mode: do not block a web request for ~50 seconds.
                    # Two short retries are enough; if the quota is still busy,
                    # the caller keeps the seasons that were already loaded.
                    if attempt == retries - 1:
                        print(
                            f"⚠️ Football API 429 → ліміт не відпустив "
                            f"({attempt + 1}/{retries}), використовуємо часткову історію"
                        )
                        break

                    retry_after = response.headers.get("Retry-After")
                    try:
                        server_delay = float(retry_after) if retry_after else None
                    except (TypeError, ValueError):
                        server_delay = None

                    fast_delay = 1.5 * (attempt + 1)
                    delay = fast_delay if server_delay is None else min(server_delay, fast_delay)
                    delay = max(0.75, min(3.0, delay))
                    print(
                        f"⚠️ Football API 429 → швидкий повтор через {delay:g} с "
                        f"({attempt + 1}/{retries})"
                    )
                    await asyncio.sleep(delay)
                    continue

                raise Exception(
                    f"Football API {response.status}: {text}"
                )

        except asyncio.TimeoutError:

            if attempt == retries - 1:
                raise

            await asyncio.sleep(2)

        except aiohttp.ClientError as e:

            if attempt == retries - 1:
                raise

            print(f"HTTP error: {e}")
            await asyncio.sleep(2)

    raise Exception("Football API request failed")


# ============================================================
# ODDS API
# ============================================================

async def odds_api_get(
    sport_key,
    markets="h2h,totals"
):
    """Get standard soccer odds from The Odds API."""
    cache_key = (sport_key, markets)

    if cache_key in ODDS_CACHE:
        return ODDS_CACHE[cache_key]

    session = await get_odds_session()
    url = f"{ODDS_BASE_URL}/sports/{sport_key}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu,uk",
        "markets": markets,
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    }

    try:
        async with session.get(
            url,
            params=params,
            timeout=aiohttp.ClientTimeout(total=30)
        ) as response:
            text = await response.text()

            if response.status != 200:
                print(f"❌ Odds API {response.status}: {text[:1000]}")
                return []

            try:
                data = await response.json(content_type=None)
            except Exception as e:
                print(f"❌ Odds API JSON error: {e}")
                return []

            if not isinstance(data, list):
                print(f"⚠️ Odds API повернув {type(data).__name__}, очікував list")
                return []

            # Не кешуємо порожню відповідь: матчі можуть з'явитися пізніше.
            if data:
                ODDS_CACHE[cache_key] = data

            print("\nODDS API")
            print(f"   sport: {sport_key}")
            print(f"   markets: {markets}")
            print(f"   events: {len(data)}")

            remaining = response.headers.get("x-requests-remaining")
            used = response.headers.get("x-requests-used")
            if remaining:
                print(f"   remaining: {remaining}")
            if used:
                print(f"   used: {used}")

            return data

    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        print(f"❌ Odds API connection error: {e}")
        return []
    except Exception as e:
        print(f"❌ Odds API error: {e}")
        return []


async def odds_api_events_get(sport_key):
    """Get the current event list without bookmaker markets.

    This is a fallback for cases where /odds does not expose a match yet,
    while the event itself is already listed by bookmakers.
    """
    if not sport_key:
        return []

    session = await get_odds_session()
    url = f"{ODDS_BASE_URL}/sports/{sport_key}/events"
    params = {
        "apiKey": ODDS_API_KEY,
        "dateFormat": "iso",
    }

    try:
        async with session.get(
            url,
            params=params,
            timeout=aiohttp.ClientTimeout(total=30)
        ) as response:
            text = await response.text()

            if response.status != 200:
                print(f"⚠️ Odds Events API {response.status}: {text[:700]}")
                return []

            try:
                data = await response.json(content_type=None)
            except Exception as e:
                print(f"⚠️ Odds Events JSON error: {e}")
                return []

            if not isinstance(data, list):
                return []

            print(f"   events endpoint: {len(data)}")
            return data

    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        print(f"⚠️ Odds Events connection error: {e}")
        return []
    except Exception as e:
        print(f"⚠️ Odds Events error: {e}")
        return []


async def find_odds_event_across_sports(home_team, away_team, preferred_key=None):
    """Find a fixture by teams across competition feeds.

    We deliberately use /events first because it is free and contains the
    competition-specific event list. This prevents a Champions League match
    from being incorrectly searched only in the home club's domestic league.
    """
    keys = []

    same_domestic_league = (
        home_team.get("league_code")
        and home_team.get("league_code") == away_team.get("league_code")
        and home_team.get("league_code") != "CL"
    )

    if same_domestic_league and preferred_key:
        priority = (
            preferred_key,
            "soccer_uefa_champs_league",
            "soccer_uefa_champs_league_qualification",
            "soccer_epl",
            "soccer_spain_la_liga",
            "soccer_italy_serie_a",
            "soccer_germany_bundesliga",
            "soccer_france_ligue_one",
        )
    else:
        priority = (
            "soccer_uefa_champs_league",
            "soccer_uefa_champs_league_qualification",
            preferred_key,
            "soccer_epl",
            "soccer_spain_la_liga",
            "soccer_italy_serie_a",
            "soccer_germany_bundesliga",
            "soccer_france_ligue_one",
        )

    for key in priority:
        if key and key not in keys:
            keys.append(key)

    print("\n🔎 CROSS-COMPETITION ODDS SEARCH")

    for key in keys:
        try:
            events = await odds_api_events_get(key)
            if not events:
                continue

            # Silent-ish matching first; find_odds_event also prints the
            # candidates, which is useful when debugging.
            candidate = find_odds_event(events, home_team, away_team)
            if candidate is not None:
                print(f"🏆 MATCH FOUND IN SPORT: {key}")
                return key, candidate
        except Exception as e:
            print(f"⚠️ Помилка перевірки {key}: {e}")

    return None, None


async def odds_api_event_get(sport_key, event_id, markets="btts"):
    """Get additional markets for one exact event."""
    if not sport_key or not event_id:
        return None

    session = await get_odds_session()
    url = f"{ODDS_BASE_URL}/sports/{sport_key}/events/{event_id}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu,uk",
        "markets": markets,
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    }

    try:
        async with session.get(
            url,
            params=params,
            timeout=aiohttp.ClientTimeout(total=30)
        ) as response:
            text = await response.text()
            if response.status != 200:
                print(f"⚠️ BTTS API {response.status}: {text[:700]}")
                return None

            try:
                data = await response.json(content_type=None)
            except Exception as e:
                print(f"⚠️ BTTS JSON error: {e}")
                return None

            return data if isinstance(data, dict) else None

    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        print(f"⚠️ BTTS connection error: {e}")
        return None
    except Exception as e:
        print(f"⚠️ BTTS error: {e}")
        return None


# ============================================================
# LOAD TEAMS
# ============================================================

async def load_league_teams(
    competition_code,
    competition_name
):

    if competition_code in COMPETITION_CACHE:

        return COMPETITION_CACHE[
            competition_code
        ]

    print(
        f"API → {competition_name}"
    )

    url = (
        f"{FOOTBALL_BASE_URL}/competitions/"
        f"{competition_code}/teams"
    )

    params = {
        "season": CURRENT_SEASON
    }

    try:

        data = await football_api_get(
            url,
            params
        )

        teams = data.get(
            "teams",
            []
        )

        result = []

        for team in teams:

            team_id = team.get(
                "id"
            )

            if team_id is None:
                continue

            result.append({

                "id":
                    team_id,

                "name":
                    team.get(
                        "name",
                        ""
                    ),

                "shortName":
                    team.get(
                        "shortName",
                        ""
                    ),

                "tla":
                    team.get(
                        "tla",
                        ""
                    ),

                "league_code":
                    competition_code,

                "league_name":
                    competition_name,

                "odds_key":
                    TOP5_LEAGUES[
                        competition_code
                    ][
                        "odds_key"
                    ],

                # Visual metadata for the web UI. football-data.org already
                # returns team crests in this endpoint, so this adds no extra
                # network request. The frontend has a graceful fallback when
                # an image is unavailable.
                "crest": team.get("crest"),
                "league_emblem": (data.get("competition") or {}).get("emblem"),
            })

        COMPETITION_CACHE[
            competition_code
        ] = result

        print(
            f"   отримано: {len(result)}"
        )

        return result

    except Exception as e:

        print(
            f"   ⚠️ Помилка: {e}"
        )

        return []


async def load_all_teams():

    print()
    print(
        "Завантаження команд ТОП-5..."
    )

    all_teams = []

    for code, config in TOP5_LEAGUES.items():

        teams = await load_league_teams(
            code,
            config["name"]
        )

        all_teams.extend(
            teams
        )

        await asyncio.sleep(
            0.5
        )

    unique = {}

    for team in all_teams:

        unique[
            team["id"]
        ] = team

    result = list(
        unique.values()
    )

    print(
        f"Збережено команд: {len(result)}"
    )

    return result


# ============================================================
# TEAM HISTORY
# ============================================================

async def get_team_history(
    team_id
):

    if team_id in HISTORY_CACHE:
        return HISTORY_CACHE[team_id]

    disk_key = f"football_history_{team_id}"
    cached_history = _disk_cache_load(
        disk_key,
        CACHE_TTL_FOOTBALL_HISTORY,
    )
    if isinstance(cached_history, list) and cached_history:
        HISTORY_CACHE[team_id] = cached_history
        print(
            f"⚡ CACHE → історія команди {team_id}: "
            f"{len(cached_history)} матчів"
        )
        return cached_history

    # A stale cache is still valuable as a fallback if the provider is
    # rate-limited during this request.
    stale_history = _disk_cache_load(
        disk_key,
        ttl=None,
        allow_stale=True,
    )

    print(
        f"API → історія команди {team_id}"
    )

    all_matches = []

    for season in HISTORY_SEASONS:

        url = (
            f"{FOOTBALL_BASE_URL}/teams/"
            f"{team_id}/matches"
        )

        params = {

            "status":
                "FINISHED",

            "season":
                season,

            "limit":
                100,
        }

        try:

            data = await football_api_get(
                url,
                params
            )

            matches = data.get(
                "matches",
                []
            )

            all_matches.extend(
                matches
            )

            print(
                f"   сезон {season}: "
                f"{len(matches)}"
            )

            # The analytical core only consumes the most recent 10 matches
            # (plus venue subsets). Once we already have a deep recent sample,
            # an extra older-season request mostly adds latency and increases
            # the chance of a 429 without changing the current-form inputs.
            if len(all_matches) >= 30:
                print(
                    f"   ⚡ SMART HISTORY: вже {len(all_matches)} матчів, "
                    f"старіші сезони не запитуємо"
                )
                break

        except Exception as e:

            print(
                f"   ⚠️ сезон {season}: {e}"
            )

        # Small courtesy gap; long waits belong in 429 handling.
        await asyncio.sleep(0.08)

    unique = {}

    for match in all_matches:

        match_id = match.get(
            "id"
        )

        if match_id:
            unique[
                match_id
            ] = match

    matches = list(
        unique.values()
    )

    filtered = []

    for match in matches:

        ft = (
            match
            .get("score", {})
            .get("fullTime", {})
        )

        if (
            ft.get("home") is None
            or
            ft.get("away") is None
        ):
            continue

        filtered.append(
            match
        )

    filtered.sort(
        key=lambda x:
        x.get(
            "utcDate",
            ""
        )
    )

    # If the provider was rate-limited before we collected a useful sample,
    # prefer the previous persistent snapshot rather than degrading the model.
    if (
        len(filtered) < MIN_HISTORY
        and isinstance(stale_history, list)
        and len(stale_history) >= MIN_HISTORY
    ):
        filtered = stale_history
        print(
            f"   ♻️ використано попередній кеш історії: "
            f"{len(filtered)} матчів"
        )

    HISTORY_CACHE[team_id] = filtered

    if filtered:
        _disk_cache_save(disk_key, filtered)

    print(
        f"   історії: {len(filtered)} матчів"
    )

    return filtered


# ============================================================
# RESULT
# ============================================================

def get_team_result(
    match,
    team_id
):

    home_id = match[
        "homeTeam"
    ].get(
        "id"
    )

    away_id = match[
        "awayTeam"
    ].get(
        "id"
    )

    ft = (
        match
        .get("score", {})
        .get("fullTime", {})
    )

    hg = safe_int(ft.get("home"), -1)
    ag = safe_int(ft.get("away"), -1)

    if hg < 0 or ag < 0:
        return None

    if home_id == team_id:

        gf = hg
        ga = ag
        home = True

    elif away_id == team_id:

        gf = ag
        ga = hg
        home = False

    else:

        return None

    if gf > ga:
        result = "W"

    elif gf == ga:
        result = "D"

    else:
        result = "L"

    return {

        "gf": gf,
        "ga": ga,
        "home": home,
        "result": result,

        "date":
            match.get(
                "utcDate",
                ""
            ),

        "opponent_id":
            away_id
            if home
            else
            home_id,

        "match":
            match,
    }



# ============================================================
# SAFE TYPE / DATE HELPERS
# ============================================================

def safe_float(value, default=0.0):
    try:
        if isinstance(value, bool):
            return default
        value = float(value)
        if not math.isfinite(value):
            return default
        return value
    except (TypeError, ValueError):
        return default


def safe_int(value, default=0):
    try:
        if isinstance(value, bool):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_datetime_utc(value):
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_before_match(match_date, before_date):
    dt = parse_datetime_utc(match_date)
    before = parse_datetime_utc(before_date)
    if dt is None or before is None:
        return False
    return dt < before


def pct(value):
    value = safe_float(value, 0.0)
    return f"{value * 100:.1f}%"


# ============================================================
# BASIC FORM
# ============================================================

def calculate_form(
    history,
    team_id,
    before_date,
    home_only=False,
    away_only=False,
    limit=FORM_MATCHES
):

    selected = []

    for match in history:

        date = match.get(
            "utcDate",
            ""
        )

        if not is_before_match(date, before_date):
            continue

        home_id = match[
            "homeTeam"
        ].get("id")

        away_id = match[
            "awayTeam"
        ].get("id")

        if (
            home_only
            and
            home_id != team_id
        ):
            continue

        if (
            away_only
            and
            away_id != team_id
        ):
            continue

        result = get_team_result(
            match,
            team_id
        )

        if result:
            selected.append(
                result
            )

    selected.sort(
        key=lambda x:
        x["date"],
        reverse=True
    )

    return selected[:limit]


# ============================================================
# FORM STATS
# ============================================================

def form_stats(
    results
):

    if not results:

        return {

            "matches": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,

            "goals_for": 0,
            "goals_against": 0,

            "attack": 0,
            "defence": 0,

            "points_per_game": 0,

            "win_rate": 0,
            "btts_rate": 0,
            "over25_rate": 0,

            "clean_sheet_rate": 0,
            "failed_to_score_rate": 0,
        }

    wins = sum(
        x["result"] == "W"
        for x in results
    )

    draws = sum(
        x["result"] == "D"
        for x in results
    )

    losses = sum(
        x["result"] == "L"
        for x in results
    )

    gf = sum(
        safe_int(x.get("gf"), 0)
        for x in results
        if isinstance(x, dict)
    )

    ga = sum(
        safe_int(x.get("ga"), 0)
        for x in results
        if isinstance(x, dict)
    )

    matches = len(results)

    btts = sum(
        safe_int(x.get("gf"), 0) > 0
        and
        safe_int(x.get("ga"), 0) > 0
        for x in results
        if isinstance(x, dict)
    )

    over25 = sum(
        safe_int(x.get("gf"), 0) + safe_int(x.get("ga"), 0) >= 3
        for x in results
        if isinstance(x, dict)
    )

    clean = sum(
        safe_int(x.get("ga"), 0) == 0
        for x in results
        if isinstance(x, dict)
    )

    failed = sum(
        safe_int(x.get("gf"), 0) == 0
        for x in results
        if isinstance(x, dict)
    )

    points = (
        wins * 3
        +
        draws
    )

    return {

        "matches":
            matches,

        "wins":
            wins,

        "draws":
            draws,

        "losses":
            losses,

        "goals_for":
            gf,

        "goals_against":
            ga,

        "attack":
            gf / matches,

        "defence":
            ga / matches,

        "points_per_game":
            points / matches,

        "win_rate":
            wins / matches,

        "btts_rate":
            btts / matches,

        "over25_rate":
            over25 / matches,

        "clean_sheet_rate":
            clean / matches,

        "failed_to_score_rate":
            failed / matches,
    }


# ============================================================
# WEIGHTED ATTACK / DEFENCE
# ============================================================

def calculate_weighted_stats(
    history,
    team_id,
    before_date,
    home_only=False,
    away_only=False
):

    results = calculate_form(
        history,
        team_id,
        before_date,
        home_only,
        away_only,
        FORM_MATCHES
    )

    if len(results) < MIN_HISTORY:

        return None

    weighted_for = 0.0
    weighted_against = 0.0
    total_weight = 0.0

    for index, item in enumerate(results):

        weight = max(
            1.0 - index * 0.10,
            0.50
        )

        weighted_for += (
            safe_float(item.get("gf"), 0.0)
            *
            weight
        )

        weighted_against += (
            safe_float(item.get("ga"), 0.0)
            *
            weight
        )

        total_weight += weight

    return {

        "matches":
            len(results),

        "attack":
            weighted_for
            /
            total_weight,

        "defence":
            weighted_against
            /
            total_weight,
    }


# ============================================================
# HALF TIME STATS
# ============================================================

def calculate_half_stats(
    history,
    team_id,
    before_date,
    home_only=False,
    away_only=False
):

    results = calculate_form(
        history,
        team_id,
        before_date,
        home_only,
        away_only,
        HISTORY_FORM_MATCHES
    )

    if not results:

        return {

            "matches": 0,

            "first_half_for": 0.0,
            "first_half_against": 0.0,

            "second_half_for": 0.0,
            "second_half_against": 0.0,

            "first_half_goals":
                0.0,

            "second_half_goals":
                0.0,
        }

    first_for = 0
    first_against = 0
    second_for = 0
    second_against = 0

    valid = 0

    for item in results:

        match = item["match"]

        score = match.get(
            "score",
            {}
        )

        half = score.get(
            "halfTime",
            {}
        )

        full = score.get(
            "fullTime",
            {}
        )

        ht_home = half.get(
            "home"
        )

        ht_away = half.get(
            "away"
        )

        ft_home = full.get(
            "home"
        )

        ft_away = full.get(
            "away"
        )

        if (
            ht_home is None
            or
            ht_away is None
            or
            ft_home is None
            or
            ft_away is None
        ):
            continue

        if item["home"]:

            fh_for = ht_home
            fh_against = ht_away

            sh_for = (
                ft_home - ht_home
            )

            sh_against = (
                ft_away - ht_away
            )

        else:

            fh_for = ht_away
            fh_against = ht_home

            sh_for = (
                ft_away - ht_away
            )

            sh_against = (
                ft_home - ht_home
            )

        first_for += fh_for
        first_against += fh_against

        second_for += sh_for
        second_against += sh_against

        valid += 1

    if valid == 0:

        return {

            "matches": 0,
            "first_half_for": 0.0,
            "first_half_against": 0.0,
            "second_half_for": 0.0,
            "second_half_against": 0.0,
            "first_half_goals": 0.0,
            "second_half_goals": 0.0,
        }

    return {

        "matches":
            valid,

        "first_half_for":
            first_for / valid,

        "first_half_against":
            first_against / valid,

        "second_half_for":
            second_for / valid,

        "second_half_against":
            second_against / valid,

        "first_half_goals":
            (
                first_for
                +
                first_against
            )
            /
            valid,

        "second_half_goals":
            (
                second_for
                +
                second_against
            )
            /
            valid,
    }


# ============================================================
# BASELINE
# ============================================================

def get_baseline_stats():

    return {

        "matches":
            5,

        "attack":
            1.35,

        "defence":
            1.35,
    }


# ============================================================
# H2H
# ============================================================

def get_h2h_matches(
    home_id,
    away_id,
    home_history,
    away_history,
    before_date
):

    cache_key = (
        home_id,
        away_id,
    )

    if cache_key in H2H_CACHE:

        matches = H2H_CACHE[
            cache_key
        ]

    else:

        combined = {}

        for match in (
            home_history
            +
            away_history
        ):

            match_id = match.get(
                "id"
            )

            if match_id:
                combined[
                    match_id
                ] = match

        matches = list(
            combined.values()
        )

        H2H_CACHE[
            cache_key
        ] = matches

    h2h = []

    for match in matches:

        if not is_before_match(
            match.get("utcDate", ""),
            before_date
        ):
            continue

        ids = {

            match
            .get("homeTeam", {})
            .get("id"),

            match
            .get("awayTeam", {})
            .get("id"),
        }

        if (
            home_id in ids
            and
            away_id in ids
        ):

            ft = (
                match
                .get("score", {})
                .get("fullTime", {})
            )

            if (
                ft.get("home") is not None
                and
                ft.get("away") is not None
            ):

                h2h.append(
                    match
                )

    h2h.sort(
        key=lambda x:
        x.get(
            "utcDate",
            ""
        ),
        reverse=True
    )

    return h2h[:H2H_MATCHES]


def calculate_h2h_stats(
    matches,
    home_id,
    away_id
):

    if not matches:

        return {

            "matches": 0,

            "home_goals":
                0.0,

            "away_goals":
                0.0,

            "over25":
                0.0,

            "btts":
                0.0,
        }

    home_goals = []
    away_goals = []

    over25 = 0
    btts = 0

    for match in matches:

        ft = (
            match
            .get("score", {})
            .get("fullTime", {})
        )

        hg = safe_int(ft.get("home"), -1)
        ag = safe_int(ft.get("away"), -1)

        if hg < 0 or ag < 0:
            continue

        match_home = (
            match
            .get("homeTeam", {})
            .get("id")
        )

        if match_home == home_id:

            home_goals.append(hg)
            away_goals.append(ag)

        else:

            home_goals.append(ag)
            away_goals.append(hg)

        if hg + ag >= 3:
            over25 += 1

        if hg > 0 and ag > 0:
            btts += 1

    count = len(home_goals)

    if count == 0:

        return {

            "matches": 0,
            "home_goals": 0,
            "away_goals": 0,
            "over25": 0,
            "btts": 0,
        }

    return {

        "matches":
            count,

        "home_goals":
            sum(home_goals) / count,

        "away_goals":
            sum(away_goals) / count,

        "over25":
            over25 / count,

        "btts":
            btts / count,
    }


# ============================================================
# REAL + MODEL xG
# ============================================================

def calculate_xg_v25(
    home_attack,
    home_defence,
    away_attack,
    away_defence,
    home_form,
    away_form,
    h2h
):

    # Базова атака/захист
    home_xg = (
        home_attack * 0.55
        +
        away_defence * 0.45
    )

    away_xg = (
        away_attack * 0.55
        +
        home_defence * 0.45
    )

    # Домашня перевага
    home_xg *= 1.08

    # Форма
    if home_form:
        home_xg *= (
            0.90
            +
            home_form["points_per_game"]
            / 30
        )

    if away_form:
        away_xg *= (
            0.92
            +
            away_form["points_per_game"]
            / 32
        )

    # H2H — невелика вага
    if isinstance(h2h, dict) and safe_int(h2h.get("matches")) >= 3:

        home_xg = (
            home_xg * 0.85
            +
            h2h["home_goals"] * 0.15
        )

        away_xg = (
            away_xg * 0.85
            +
            h2h["away_goals"] * 0.15
        )

    home_xg = max(
        0.20,
        min(
            home_xg,
            4.50
        )
    )

    away_xg = max(
        0.20,
        min(
            away_xg,
            4.50
        )
    )

    return home_xg, away_xg


# ============================================================
# POISSON
# ============================================================

def poisson_probability(
    goals,
    expected
):

    expected = safe_float(expected, 0.0)
    if expected <= 0:
        return 0.0

    return (
        math.exp(-expected)
        *
        expected ** goals
        /
        math.factorial(goals)
    )


# ============================================================
# SCORE MATRIX
# ============================================================

def build_score_matrix(
    home_xg,
    away_xg
):

    matrix = {}

    for hg in range(
        MAX_GOALS + 1
    ):

        hp = poisson_probability(
            hg,
            home_xg
        )

        for ag in range(
            MAX_GOALS + 1
        ):

            ap = poisson_probability(
                ag,
                away_xg
            )

            matrix[
                (hg, ag)
            ] = hp * ap

    return matrix


# ============================================================
# PROBABILITIES
# ============================================================

def calculate_probabilities(
    home_xg,
    away_xg
):

    matrix = build_score_matrix(
        home_xg,
        away_xg
    )

    home_win = 0.0
    draw = 0.0
    away_win = 0.0

    over25 = 0.0
    under25 = 0.0

    btts_yes = 0.0
    btts_no = 0.0

    for (
        hg,
        ag
    ), probability in matrix.items():

        if hg > ag:
            home_win += probability

        elif hg == ag:
            draw += probability

        else:
            away_win += probability

        if hg + ag >= 3:
            over25 += probability

        else:
            under25 += probability

        if hg > 0 and ag > 0:
            btts_yes += probability

        else:
            btts_no += probability

    scores = sorted(
        matrix.items(),
        key=lambda x:
        x[1],
        reverse=True
    )

    most_likely = scores[:5]

    return {

        "home_win":
            home_win,

        "draw":
            draw,

        "away_win":
            away_win,

        "double_home":
            home_win + draw,

        "double_away":
            away_win + draw,

        "over_25":
            over25,

        "under_25":
            under25,

        "btts_yes":
            btts_yes,

        "btts_no":
            btts_no,

        "most_likely_scores":
            most_likely,
    }


# ============================================================
# SEPARATE MARKET MODEL
# ============================================================

def blend_probability(
    poisson_probability_value,
    historical_probability,
    weight_history=0.25
):

    if historical_probability is None:
        return poisson_probability_value

    return (
        poisson_probability_value
        *
        (1 - weight_history)
        +
        historical_probability
        *
        weight_history
    )


def calculate_market_probabilities(
    probabilities,
    home_form,
    away_form,
    h2h
):

    result = dict(
        probabilities
    )

    # ========================================================
    # OVER / UNDER
    # ========================================================

    historical_over = None

    if (
        home_form
        and
        away_form
    ):

        historical_over = (
            home_form["over25_rate"]
            +
            away_form["over25_rate"]
        ) / 2

    if (
        h2h
        and
        safe_int(h2h.get("matches")) >= 3
    ):

        if historical_over is None:

            historical_over = h2h["over25"]

        else:

            historical_over = (
                historical_over * 0.70
                +
                h2h["over25"] * 0.30
            )

    result["over_25"] = blend_probability(
        probabilities["over_25"],
        historical_over,
        0.20
    )

    result["under_25"] = (
        1
        -
        result["over_25"]
    )

    # ========================================================
    # BTTS
    # ========================================================

    historical_btts = None

    if (
        home_form
        and
        away_form
    ):

        historical_btts = (
            home_form["btts_rate"]
            +
            away_form["btts_rate"]
        ) / 2

    if (
        h2h
        and
        safe_int(h2h.get("matches")) >= 3
    ):

        if historical_btts is None:

            historical_btts = h2h["btts"]

        else:

            historical_btts = (
                historical_btts * 0.70
                +
                h2h["btts"] * 0.30
            )

    result["btts_yes"] = blend_probability(
        probabilities["btts_yes"],
        historical_btts,
        0.20
    )

    result["btts_no"] = (
        1
        -
        result["btts_yes"]
    )

    return result


# ============================================================
# VALUE
# ============================================================

def calculate_value(
    probability,
    odds
):

    if odds is None:
        return None

    probability = safe_float(probability, -1.0)
    odds = safe_float(odds, -1.0)
    if probability < 0 or probability > 1 or odds <= 1:
        return None

    return probability * odds - 1


# ============================================================
# CONFIDENCE
# ============================================================

def calculate_confidence(
    probability,
    market_value,
    market,
    model_edge=0.0,
    real_xg_quality=0.0
):
    """V48 confidence: probability + market value + model/market agreement.

    A single bookmaker price must not create confidence. Positive market value
    and a meaningful model edge are rewarded, while weak REAL xG coverage only
    gives a small bonus instead of pretending the sample is strong.
    """
    probability = safe_float(probability, 0.0)
    market_value = safe_float(market_value, 0.0)
    model_edge = safe_float(model_edge, 0.0)
    real_xg_quality = safe_float(real_xg_quality, 0.0)

    score = probability * 50.0

    # Market-wide value: capped so a longshot cannot explode confidence.
    score += max(-10.0, min(15.0, market_value * 100.0 * 0.60))

    # Model edge is the difference between model probability and market
    # consensus probability for the same outcome.
    score += max(-8.0, min(8.0, model_edge * 100.0 * 0.40))

    # Market type reliability.
    if market in ("double_home", "double_away"):
        score += 8.0
    elif market in ("over_25", "under_25"):
        score += 5.0
    elif market in ("btts_yes", "btts_no"):
        score += 5.0

    # REAL xG quality is intentionally a modest component.
    score += max(0.0, min(4.0, real_xg_quality * 4.0))

    return min(max(score, 0.0), 100.0)


# ============================================================
# ODDS HELPERS
# ============================================================

def names_match(
    name1,
    name2
):

    a = normalize_name(name1)
    b = normalize_name(name2)

    if not a or not b:
        return False

    # First compare through the authoritative 36-team CL registry.
    ca = cl_canonical_team(name1)
    cb = cl_canonical_team(name2)
    if ca and cb:
        return ca == cb

    if a == b:
        return True

    if a in b or b in a:
        return True

    special = {

        "inter milan": [
            "inter",
            "internazionale",
            "internazionale milano",
            "fc internazionale milano",
        ],

        "inter": [
            "inter milan",
            "internazionale",
            "internazionale milano",
            "fc internazionale milano",
        ],

        "internazionale milano": [
            "inter milan",
            "inter",
            "internazionale",
            "fc internazionale milano",
        ],

        "barcelona": [
            "fc barcelona",
        ],

        "real madrid": [
            "real madrid cf",
        ],

        "bayern munich": [
            "bayern",
            "fc bayern munich",
        ],

        "bayer leverkusen": [
            "bayer",
            "bayer 04 leverkusen",
        ],

        "brighton": [
            "brighton and hove albion",
            "brighton hove albion",
        ],

        "lyon": [
            "olympique lyonnais",
            "olympique lyon",
        ],

        "rennes": [
            "stade rennais",
            "stade rennais fc",
        ],

        "fiorentina": [
            "acf fiorentina",
        ],

        "psv": [
            "psv eindhoven",
            "psv eindhoven fc",
        ],

        "sporting cp": [
            "sporting lisbon",
            "sporting clube de portugal",
        ],

        "red bull salzburg": [
            "salzburg",
            "fc salzburg",
        ],

        "shakhtar donetsk": [
            "shakhtar",
            "shakhtar donetsk fc",
        ],

        "dynamo kyiv": [
            "dinamo kiev",
            "dynamo kyiv fc",
            "dinamo kyiv",
        ],

        "pae aek": [
            "aek athens",
            "aek",
            "aeκ athens",
        ],

        "aek athens": [
            "pae aek",
            "aek",
        ],

        "lask linz": [
            "lask",
            "lask linz",
        ],

        "lask": [
            "lask linz",
        ],
    }

    if a in special:

        if any(
            b == normalize_name(x)
            for x in special[a]
        ):
            return True

    if b in special:

        if any(
            a == normalize_name(x)
            for x in special[b]
        ):
            return True

    return similarity(a, b) >= 0.88


def find_odds_event(
    events,
    home_team,
    away_team
):

    if not events:
        print("⚠️ Odds API повернув 0 подій")
        return None

    target_home = home_team["name"]
    target_away = away_team["name"]

    print()
    print("🔎 ПОШУК МАТЧУ В ODDS API")
    print(f"   Football API: {target_home} - {target_away}")
    print(f"   Подій у Odds API: {len(events)}")

    best = None
    best_score = 0.0

    for event in events:

        event_home = event.get(
            "home_team",
            ""
        )

        event_away = event.get(
            "away_team",
            ""
        )

        # --------------------------------------------
        # Порівнюємо команди
        # --------------------------------------------

        home_match = names_match(
            target_home,
            event_home
        )

        away_match = names_match(
            target_away,
            event_away
        )

        print(
            f"   {event_home} - {event_away} | "
            f"HOME={home_match} AWAY={away_match}"
        )

        if not home_match or not away_match:
            continue

        commence = event.get(
            "commence_time"
        )

        if not commence:
            continue

        try:

            event_time = datetime.fromisoformat(
                commence.replace(
                    "Z",
                    "+00:00"
                )
            )

        except Exception:

            event_time = datetime.now(
                timezone.utc
            )

        now = datetime.now(
            timezone.utc
        )

        # --------------------------------------------
        # Не відкидаємо матч автоматично,
        # якщо він вже почався.
        #
        # Odds API іноді ще повертає коефіцієнти
        # для матчу, який щойно почався.
        # --------------------------------------------

        hours_difference = abs(
            (
                event_time - now
            ).total_seconds()
        ) / 3600

        score = 1 / (
            1 +
            hours_difference / 24
        )

        if event_time >= now:

            score += 1.0

        if score > best_score:

            best_score = score
            best = event

    if best:

        print()
        print("✅ MATCH FOUND IN ODDS API")
        print(
            f"   {best.get('home_team')} - "
            f"{best.get('away_team')}"
        )
        print(
            f"   commence: "
            f"{best.get('commence_time')}"
        )

    else:

        print()
        print("❌ MATCH NOT FOUND IN ODDS API")

        print("   Приклади подій, які повернув API:")

        for event in events[:10]:

            print(
                f"   • "
                f"{event.get('home_team')} - "
                f"{event.get('away_team')}"
            )

    return best
def get_market(
    bookmaker,
    market_key
):

    for market in bookmaker.get(
        "markets",
        []
    ):

        if market.get(
            "key"
        ) == market_key:

            return market

    return None


# ============================================================
# REAL ODDS
# ============================================================

def median_odds(values):
    """Median available bookmaker price; useful as a market-consensus reference."""
    valid = []
    if not isinstance(values, (list, tuple)):
        return None
    for value in values:
        try:
            value = float(value)
            if value > 1:
                valid.append(value)
        except (TypeError, ValueError):
            continue
    if not valid:
        return None
    valid.sort()
    n = len(valid)
    mid = n // 2
    if n % 2:
        return valid[mid]
    return (valid[mid - 1] + valid[mid]) / 2.0


def devig_1x2(home_odds, draw_odds, away_odds):
    """Remove bookmaker margin from 1X2 prices and return normalized probabilities."""
    odds = [home_odds, draw_odds, away_odds]
    if any(v is None or safe_float(v, 0) <= 1 for v in odds):
        return None
    inv = [1.0 / float(v) for v in odds]
    total = sum(inv)
    if total <= 0:
        return None
    return {
        "home": inv[0] / total,
        "draw": inv[1] / total,
        "away": inv[2] / total,
    }


def best_odds(values):
    valid = []

    if not isinstance(values, (list, tuple)):
        return None

    for value in values:
        try:
            value = float(value)

            if value > 1:
                valid.append(value)

        except (TypeError, ValueError):
            continue

    if not valid:
        return None

    return max(valid)


def extract_real_odds(event):

    result = {

        "home": [],
        "draw": [],
        "away": [],
        "double_home": [],
        "double_away": [],

        "over25": [],
        "under25": [],

        "btts_yes": [],
        "btts_no": [],

        "bookmakers": [],
    }

    if not event:
        return result

    print()
    print("💰 РЕАЛЬНІ КОЕФІЦІЄНТИ")

    print(
        f"Матч: "
        f"{event.get('home_team', '')} - "
        f"{event.get('away_team', '')}"
    )

    bookmakers = event.get(
        "bookmakers",
        []
    )

    if not isinstance(bookmakers, list):
        bookmakers = []

    print(
        f"Букмекерів отримано: {len(bookmakers)}"
    )

    for bookmaker in bookmakers:

        if not isinstance(bookmaker, dict):
            continue

        bookmaker_name = bookmaker.get(
            "title",
            bookmaker.get(
                "key",
                "Unknown"
            )
        )

        bookmaker_data = {

            "name":
                bookmaker_name,

            "home":
                None,

            "draw":
                None,

            "away":
                None,

            "double_home":
                None,

            "double_away":
                None,

            "over25":
                None,

            "under25":
                None,

            "btts_yes":
                None,

            "btts_no":
                None,
        }

        markets = bookmaker.get(
            "markets",
            []
        )

        if not isinstance(markets, list):
            markets = []

        for market in markets:

            if not isinstance(market, dict):
                continue

            market_key = market.get(
                "key",
                ""
            )

            outcomes = market.get(
                "outcomes",
                []
            )

            if not isinstance(outcomes, list):
                continue

            # =================================================
            # 1X2
            # =================================================

            if market_key == "h2h":

                for outcome in outcomes:

                    if not isinstance(outcome, dict):
                        continue

                    name = outcome.get(
                        "name",
                        ""
                    )

                    price = outcome.get(
                        "price"
                    )

                    try:
                        price = float(price)

                    except (TypeError, ValueError):
                        continue

                    if price <= 1:
                        continue

                    if names_match(
                        name,
                        event.get(
                            "home_team",
                            ""
                        )
                    ):

                        result["home"].append(
                            price
                        )

                        bookmaker_data["home"] = price

                    elif names_match(
                        name,
                        event.get(
                            "away_team",
                            ""
                        )
                    ):

                        result["away"].append(
                            price
                        )

                        bookmaker_data["away"] = price

                    elif normalize_name(
                        name
                    ) in (
                        "draw",
                        "x"
                    ):

                        result["draw"].append(
                            price
                        )

                        bookmaker_data["draw"] = price

            # =================================================
            # DOUBLE CHANCE — ТІЛЬКИ РЕАЛЬНИЙ РИНОК ODDS API
            # =================================================

            elif market_key == "double_chance":

                for outcome in outcomes:

                    if not isinstance(outcome, dict):
                        continue

                    name = normalize_name(outcome.get("name", ""))
                    price = outcome.get("price")

                    try:
                        price = float(price)
                    except (TypeError, ValueError):
                        continue

                    if price <= 1:
                        continue

                    # Приклади назв Odds API:
                    # "Chelsea or Draw", "Fulham or Draw", "Chelsea or Fulham"
                    home_name = normalize_name(event.get("home_team", ""))
                    away_name = normalize_name(event.get("away_team", ""))

                    if (
                        (home_name and home_name in name and "draw" in name)
                        or name in ("1x", "home or draw")
                    ):
                        result["double_home"].append(price)
                        bookmaker_data["double_home"] = price

                    elif (
                        (away_name and away_name in name and "draw" in name)
                        or name in ("x2", "away or draw")
                    ):
                        result["double_away"].append(price)
                        bookmaker_data["double_away"] = price

            # =================================================
            # TOTALS
            # =================================================

            elif market_key == "totals":

                for outcome in outcomes:

                    if not isinstance(outcome, dict):
                        continue

                    name = normalize_name(
                        outcome.get(
                            "name",
                            ""
                        )
                    )

                    point = outcome.get(
                        "point"
                    )

                    price = outcome.get(
                        "price"
                    )

                    try:
                        point = float(point)
                        price = float(price)

                    except (TypeError, ValueError):
                        continue

                    if price <= 1:
                        continue

                    if abs(point - 2.5) > 0.01:
                        continue

                    if name == "over":

                        result["over25"].append(
                            price
                        )

                        bookmaker_data[
                            "over25"
                        ] = price

                    elif name == "under":

                        result["under25"].append(
                            price
                        )

                        bookmaker_data[
                            "under25"
                        ] = price

            # =================================================
            # BTTS
            # =================================================

            elif market_key == "btts":

                for outcome in outcomes:

                    if not isinstance(outcome, dict):
                        continue

                    name = normalize_name(
                        outcome.get(
                            "name",
                            ""
                        )
                    )

                    price = outcome.get(
                        "price"
                    )

                    try:
                        price = float(price)

                    except (TypeError, ValueError):
                        continue

                    if price <= 1:
                        continue

                    if name in (
                        "yes",
                        "btts yes",
                        "btts yes yes"
                    ):

                        result[
                            "btts_yes"
                        ].append(
                            price
                        )

                        bookmaker_data[
                            "btts_yes"
                        ] = price

                    elif name in (
                        "no",
                        "btts no",
                        "btts no no"
                    ):

                        result[
                            "btts_no"
                        ].append(
                            price
                        )

                        bookmaker_data[
                            "btts_no"
                        ] = price

        result[
            "bookmakers"
        ].append(
            bookmaker_data
        )

        print(
            f"   {bookmaker_name}: "
            f"1={bookmaker_data['home']} | "
            f"X={bookmaker_data['draw']} | "
            f"2={bookmaker_data['away']} | "
            f"1X={bookmaker_data['double_home']} | "
            f"X2={bookmaker_data['double_away']} | "
            f"ТБ2.5={bookmaker_data['over25']} | "
            f"ТМ2.5={bookmaker_data['under25']} | "
            f"ОЗ+={bookmaker_data['btts_yes']} | "
            f"ОЗ-={bookmaker_data['btts_no']}"
        )

    print()
    print("📊 ПІДСУМОК КОЕФІЦІЄНТІВ:")

    print(
        f"   П1: "
        f"{best_odds(result['home'])}"
    )

    print(
        f"   X:  "
        f"{best_odds(result['draw'])}"
    )

    print(
        f"   П2: "
        f"{best_odds(result['away'])}"
    )

    print(
        f"   1X: "
        f"{best_odds(result['double_home'])}"
    )

    print(
        f"   X2: "
        f"{best_odds(result['double_away'])}"
    )

    print(
        f"   ТБ 2.5: "
        f"{best_odds(result['over25'])}"
    )

    print(
        f"   ТМ 2.5: "
        f"{best_odds(result['under25'])}"
    )

    print(
        f"   ОЗ Так: "
        f"{best_odds(result['btts_yes'])}"
    )

    print(
        f"   ОЗ Ні: "
        f"{best_odds(result['btts_no'])}"
    )

    return result



# ============================================================
# REAL xG DATA (BIG BALLS SPORTS DATA)
# ============================================================

BBS_LEAGUES = {
    "PL": "epl",
    "PD": "laliga",
    "SA": "serie-a",
    "BL1": "bundesliga",
    "FL1": "ligue-1",
    "CL": "ucl",
}

XG_MATCHES = 10
XG_MIN_MATCHES = 5
XG_CANDIDATE_MULTIPLIER = 4
XG_MAX_CANDIDATES = 36
# If the current team feed contains too few xG-bearing matches, load older
# seasons from FotMob league feeds. This lets us continue past the usual
# recent-results window returned by /api/data/teams.
FOTMOB_HISTORICAL_SEASONS = 2
XG_CACHE = {}
XG_MATCH_LIST_CACHE = {}
XG_BBS_PAGE_CACHE = {}
BBS_XG_DEBUG = True
BBS_XG_DEBUG_DONE = False


async def get_bbs_stored_matches(league_key):
    """Load a broad finished-match archive from BBS.

    BBS uses canonical league codes on /stored/matches.  The endpoint returns
    Big Balls UUIDs which must be reused for the per-match stats endpoint.
    We keep the list cached because xG for both teams can reuse the same rows.
    """
    if league_key in XG_MATCH_LIST_CACHE:
        return XG_MATCH_LIST_CACHE[league_key]

    matches = []
    # 200 is the documented maximum.  Usually one page is enough for the
    # recent form window, but read a second page when the API exposes one so
    # we do not accidentally miss older matches during a season transition.
    for page in (1, 2, 3):
        data = await bbs_api_get(
            "/stored/matches",
            {
                "sport": "football",
                "league": league_key,
                "status": "finished",
                "limit": 200,
                "page": page,
            },
        )
        if not isinstance(data, dict):
            break
        rows = data.get("data", [])
        if not isinstance(rows, list) or not rows:
            break
        matches.extend(rows)

        pagination = data.get("pagination")
        if not isinstance(pagination, dict):
            # The stored endpoint may omit pagination; a full page is still
            # useful, but do not hammer the API unnecessarily.
            if len(rows) < 200:
                break
            continue

        total = safe_float(pagination.get("total"), None)
        if total is not None and len(matches) >= int(total):
            break
        if len(rows) < 200:
            break

    # De-duplicate by BBS UUID.
    unique = {}
    for m in matches:
        if isinstance(m, dict) and m.get("id"):
            unique[str(m["id"])] = m
    matches = list(unique.values())

    XG_MATCH_LIST_CACHE[league_key] = matches
    return matches


def bbs_match_datetime(match):
    """Read BBS kickoff time across current/legacy response shapes."""
    if not isinstance(match, dict):
        return datetime.min.replace(tzinfo=timezone.utc)
    for key in (
        "kickoff_utc", "kickoff", "kickoff_at", "kickoffAt",
        "utcDate", "date", "start_time", "startTime",
    ):
        value = match.get(key)
        if not value:
            continue
        try:
            text = str(value).replace("Z", "+00:00")
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            continue
    return datetime.min.replace(tzinfo=timezone.utc)


def _bbs_team_name(value):
    if isinstance(value, dict):
        return str(
            value.get("name")
            or value.get("team_name")
            or value.get("teamName")
            or value.get("short_name")
            or value.get("shortName")
            or ""
        )
    return str(value or "")


def bbs_match_teams(match):
    if not isinstance(match, dict):
        return "", ""

    home = (
        match.get("home")
        or match.get("home_team")
        or match.get("homeTeam")
        or match.get("home_team_name")
        or match.get("homeTeamName")
    )
    away = (
        match.get("away")
        or match.get("away_team")
        or match.get("awayTeam")
        or match.get("away_team_name")
        or match.get("awayTeamName")
    )
    return _bbs_team_name(home), _bbs_team_name(away)


def extract_number(obj, keys):
    if not isinstance(obj, dict):
        return None
    for key in keys:
        if key in obj:
            value = safe_float(obj.get(key), None)
            if value is not None and value >= 0:
                return value
    return None


def _recursive_xg_values(obj, target_name=None, depth=0):
    """Return xG-like values found in a BBS response subtree.

    BBS has evolved a few envelope shapes.  This parser intentionally accepts
    home/away objects, team-stat arrays, and nested `stats`/`statistics`
    objects while still requiring a numeric xG field.
    """
    if depth > 8 or obj is None:
        return []
    found = []
    if isinstance(obj, dict):
        name = (
            obj.get("team_name") or obj.get("teamName")
            or obj.get("name") or obj.get("team")
            or obj.get("team_name_display") or ""
        )
        if isinstance(name, dict):
            name = name.get("name", "")
        xg = extract_number(
            obj,
            ("xg", "XG", "xG", "expected_goals", "expectedGoals",
             "expected_goals_for", "expectedGoalsFor", "expected_goal", "expectedGoal"),
        )
        if xg is None:
            label = str(
                obj.get("stat") or obj.get("stat_name") or obj.get("statName")
                or obj.get("label") or obj.get("metric") or obj.get("type") or ""
            ).strip().lower()
            if label in {
                "xg", "expected goals", "expected goal", "expected_goals",
                "expected goals for", "expected_goals_for", "expectedgoals",
            }:
                xg = safe_float(
                    obj.get("value", obj.get("val", obj.get("amount"))), None
                )
        if xg is not None and xg >= 0:
            found.append((str(name), float(xg), obj))
        for value in obj.values():
            found.extend(_recursive_xg_values(value, target_name, depth + 1))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_recursive_xg_values(item, target_name, depth + 1))
    return found


def parse_bbs_xg_stats(data, home_name, away_name):
    """Extract match-level home/away xG from current or legacy BBS envelopes."""
    if not isinstance(data, dict):
        return None

    payload = data.get("data", data)
    if isinstance(payload, list) and len(payload) == 1:
        payload = payload[0]
    if not isinstance(payload, (dict, list)):
        return None

    # First, handle the canonical home/away shape directly.
    root = payload if isinstance(payload, dict) else {}
    home_obj = root.get("home") or root.get("home_team") or root.get("homeTeam") or {}
    away_obj = root.get("away") or root.get("away_team") or root.get("awayTeam") or {}
    hxg = extract_number(home_obj, ("xg", "XG", "xG", "expected_goals", "expectedGoals",
                       "expected_goals_for", "expectedGoalsFor", "expected_goal", "expectedGoal"))
    axg = extract_number(away_obj, ("xg", "XG", "xG", "expected_goals", "expectedGoals",
                       "expected_goals_for", "expectedGoalsFor", "expected_goal", "expectedGoal"))

    if hxg is not None and axg is not None:
        return {"home_xg": float(hxg), "away_xg": float(axg)}

    # Otherwise inspect all nested team-stat records and match by team name.
    candidates = _recursive_xg_values(payload)
    home_candidates = []
    away_candidates = []
    for name, value, obj in candidates:
        if names_match(name, home_name):
            home_candidates.append(value)
        elif names_match(name, away_name):
            away_candidates.append(value)

    if home_candidates and away_candidates:
        return {
            "home_xg": float(home_candidates[0]),
            "away_xg": float(away_candidates[0]),
        }

    # Last-resort positional extraction: some stored stats responses contain
    # exactly two team objects but do not repeat the team name inside them.
    raw_team_lists = []
    if isinstance(root, dict):
        for key in ("statistics", "stats", "teams", "team_stats", "match_stats", "data"):
            value = root.get(key)
            if isinstance(value, list) and len(value) >= 2:
                raw_team_lists.append(value)
    for arr in raw_team_lists:
        vals = []
        for item in arr[:2]:
            value = extract_number(item, ("xg", "XG", "xG", "expected_goals", "expectedGoals",
                       "expected_goals_for", "expectedGoalsFor", "expected_goal", "expectedGoal"))
            if value is not None:
                vals.append(float(value))
        if len(vals) >= 2:
            return {"home_xg": vals[0], "away_xg": vals[1]}

    # Generic named-team fallback for nested statistics envelopes.
    all_candidates = _recursive_xg_values(payload)
    if all_candidates:
        h = [v for n, v, _ in all_candidates if names_match(n, home_name)]
        a = [v for n, v, _ in all_candidates if names_match(n, away_name)]
        if h and a:
            return {"home_xg": float(h[0]), "away_xg": float(a[0])}

    return None



# ============================================================
# FOTMOB REAL xG
# ============================================================
# FotMob exposes match-level xG in matchDetails. We use it as the
# primary REAL xG source. No synthetic xG is generated here.
#
# Documented/observed routes:
#   /api/data/search/suggest
#   /api/data/teams
#   /api/data/matchDetails
#
# xG is read from:
#   content.stats.Periods.All.stats
#   title/key == "Expected goals (xG)" / "expected_goals"
#
FOTMOB_BASE_URL = "https://www.fotmob.com"
FOTMOB_CACHE = {}
FOTMOB_TEAM_CACHE = {}
FOTMOB_MATCH_CACHE = {}
FOTMOB_MATCH_CORNERS_CACHE = {}
FOTMOB_TEAM_DATA_CACHE = {}
FOTMOB_HISTORICAL_MATCHES_CACHE = {}


async def fotmob_get(session, path, params=None):
    url = FOTMOB_BASE_URL + path
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/140.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.fotmob.com/",
        "Origin": "https://www.fotmob.com",
        "Cache-Control": "no-cache",
    }

    async with session.get(
        url,
        params=params or {},
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=25),
        ssl=False,
    ) as resp:
        body = await resp.text()
        if resp.status != 200:
            raise RuntimeError(f"FotMob HTTP {resp.status}: {body[:500]}")
        try:
            return json.loads(body)
        except Exception:
            raise RuntimeError("FotMob returned non-JSON response")



async def fotmob_get_team_data(session, team_id):
    """Shared/persistent team payload used by both REAL xG and corners."""
    key = str(team_id)
    if key in FOTMOB_TEAM_DATA_CACHE:
        return FOTMOB_TEAM_DATA_CACHE[key]

    disk_key = f"fotmob_team_{key}"
    cached = _disk_cache_load(disk_key, CACHE_TTL_FOTMOB_TEAM)
    if isinstance(cached, dict):
        FOTMOB_TEAM_DATA_CACHE[key] = cached
        return cached

    data = await fotmob_get(
        session,
        "/api/data/teams",
        {"id": team_id},
    )
    if isinstance(data, dict):
        FOTMOB_TEAM_DATA_CACHE[key] = data
        _disk_cache_save(disk_key, data)
    return data


def _load_fotmob_match_disk(match_id):
    data = _disk_cache_load(
        f"fotmob_match_{match_id}",
        CACHE_TTL_FOTMOB_MATCH,
    )
    if not isinstance(data, dict):
        return None
    xg = data.get("xg")
    corners = data.get("corners")
    if isinstance(corners, list):
        corners = tuple(corners)
    yellow_cards = data.get("yellow_cards")
    if isinstance(yellow_cards, list):
        yellow_cards = tuple(yellow_cards)
    return {
        "xg": xg,
        "corners": corners,
        "yellow_cards": yellow_cards,
        "referee": data.get("referee"),
    }


def _save_fotmob_match_disk(match_id, xg, corners, yellow_cards=None, referee=None):
    old = _disk_cache_load(
        f"fotmob_match_{match_id}",
        CACHE_TTL_FOTMOB_MATCH,
    )
    old = old if isinstance(old, dict) else {}
    if yellow_cards is None:
        yellow_cards = old.get("yellow_cards")
    if referee is None:
        referee = old.get("referee")
    _disk_cache_save(
        f"fotmob_match_{match_id}",
        {
            "xg": xg,
            "corners": list(corners) if isinstance(corners, tuple) else corners,
            "yellow_cards": list(yellow_cards) if isinstance(yellow_cards, tuple) else yellow_cards,
            "referee": referee,
        },
    )


def _fotmob_pick_team_from_search(data, target_name):
    """Robustly extract a FotMob team from several search response shapes."""
    target_norm = normalize_name(str(target_name))
    rows = []

    def walk(obj, depth=0):
        if depth > 10 or obj is None:
            return
        if isinstance(obj, dict):
            # A team/entity object may itself be the item.
            name = (
                obj.get("name")
                or obj.get("teamName")
                or obj.get("title")
                or obj.get("shortName")
            )
            team_id = (
                obj.get("teamId")
                or obj.get("team_id")
                or (obj.get("id") if obj.get("type") in {"team", "Team"} else None)
            )
            item_type = str(obj.get("type") or obj.get("entityType") or "").lower()
            if team_id is not None and name:
                # Do not require an explicit type: some FotMob responses omit it.
                rows.append({
                    "id": team_id,
                    "name": name,
                    "type": item_type,
                })
            for value in obj.values():
                walk(value, depth + 1)
        elif isinstance(obj, list):
            for value in obj:
                walk(value, depth + 1)

    walk(data)

    best = (None, "", 0.0)
    seen = set()

    for item in rows:
        team_id = item["id"]
        name = str(item["name"])
        key = (str(team_id), name)
        if key in seen:
            continue
        seen.add(key)

        norm = normalize_name(name)
        score = SequenceMatcher(None, target_norm, norm).ratio()

        # Strong bonuses for exact/contained matches.
        if norm == target_norm:
            score = 1.0
        elif target_norm in norm or norm in target_norm:
            score = max(score, 0.90)

        if score > best[2]:
            best = (team_id, name, score)

    return best


# Known stable FotMob IDs for the teams used in our test and common aliases.
# Official FotMob league IDs for the five major European domestic leagues.
# We use the current league tables as a dynamic team -> FotMob ID registry,
# so newly promoted/relegated clubs do not need to be hard-coded manually.
FOTMOB_TOP5_LEAGUE_IDS = {
    "PL": 47,   # Premier League
    "PD": 87,   # LaLiga
    "SA": 55,   # Serie A
    "BL1": 54,  # Bundesliga
    "FL1": 53,  # Ligue 1
}

FOTMOB_TOP5_TEAM_REGISTRY = {}
FOTMOB_TOP5_REGISTRY_LOADED = False
FOTMOB_TOP5_REGISTRY_LOCK = asyncio.Lock()


async def _fotmob_load_top5_team_registry(session):
    """Load every current Top-5 domestic league team directly from FotMob.

    This is deliberately dynamic: the bot no longer depends on a manually
    maintained list of 20 teams per league. Promoted/relegated clubs are
    picked up automatically from FotMob's current league tables.
    """
    global FOTMOB_TOP5_REGISTRY_LOADED

    if FOTMOB_TOP5_REGISTRY_LOADED:
        return

    async with FOTMOB_TOP5_REGISTRY_LOCK:
        if FOTMOB_TOP5_REGISTRY_LOADED:
            return

        total = 0

        for league_code, league_id in FOTMOB_TOP5_LEAGUE_IDS.items():
            try:
                data = await fotmob_get(
                    session,
                    "/api/data/leagues",
                    {"id": league_id},
                )

                rows = []

                def walk(obj, depth=0):
                    if depth > 10 or obj is None:
                        return

                    if isinstance(obj, dict):
                        name = obj.get("name") or obj.get("teamName")
                        team_id = obj.get("id") or obj.get("teamId")

                        # Standings rows have these fields. This prevents
                        # player/stat entries elsewhere in the league payload
                        # from being mistaken for teams.
                        is_team_row = (
                            name
                            and team_id is not None
                            and any(
                                key in obj
                                for key in (
                                    "played", "wins", "draws", "losses",
                                    "pts", "points", "scoresStr",
                                    "goalConDiff", "idx", "position",
                                )
                            )
                        )

                        if is_team_row:
                            try:
                                rows.append((int(team_id), str(name)))
                            except (TypeError, ValueError):
                                pass

                        for value in obj.values():
                            walk(value, depth + 1)

                    elif isinstance(obj, list):
                        for value in obj:
                            walk(value, depth + 1)

                walk(data)

                seen = set()
                for team_id, team_name in rows:
                    key = normalize_name(team_name)
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    FOTMOB_TOP5_TEAM_REGISTRY[key] = team_id
                    FOTMOB_TEAM_CACHE[key] = team_id
                    total += 1

                print(
                    f"   📚 FotMob Top-5 registry: {league_code} "
                    f"-> {len(seen)} teams loaded"
                )

            except Exception as e:
                print(
                    f"   ⚠️ FotMob Top-5 registry {league_code}: {e}"
                )

        FOTMOB_TOP5_REGISTRY_LOADED = True
        print(f"   ✅ FotMob Top-5 registry ready: {total} teams")


def _fotmob_registry_pick_team_id(team_name):
    target = normalize_name(team_name)
    if not target:
        return None

    direct = FOTMOB_TOP5_TEAM_REGISTRY.get(target)
    if direct:
        return int(direct)

    best_id = None
    best_score = 0.0

    for name, team_id in FOTMOB_TOP5_TEAM_REGISTRY.items():
        score = SequenceMatcher(None, target, name).ratio()
        if target in name or name in target:
            score = max(score, 0.90)
        if score > best_score:
            best_score = score
            best_id = team_id

    # Conservative threshold: use the dynamic registry only for a strong
    # match; otherwise fall through to FotMob's normal search endpoints.
    if best_id is not None and best_score >= 0.86:
        return int(best_id)

    return None


FOTMOB_KNOWN_TEAM_IDS = {
    # 2026/27 UEFA Champions League — all 36 league-phase teams.
    # IDs verified where possible against current FotMob team pages.
    "aek athens": 8563,
    "pae aek": 8563,
    "aek": 8563,
    "arsenal": 9825,
    "chelsea": 8455,
    "chelsea fc": 8455,
    "aston villa": 10252,
    "atletico madrid": 9906,
    "atletico de madrid": 9906,
    "club atletico de madrid": 9906,
    "atleti": 9906,
    "barcelona": 8634,
    "bayern munich": 9823,
    "bayern munchen": 9823,
    "bayern": 9823,
    "bodo glimt": 8402,
    "bodoe glimt": 8402,
    "borussia dortmund": 9789,
    "dortmund": 9789,
    "club brugge": 8262,
    "como": 10171,
    "fenerbahce": 8695,
    "fenerbahce istanbul": 8695,
    "feyenoord": 10235,
    "galatasaray": 8637,
    "galatasaray istanbul": 8637,
    "inter": 8636,
    "inter milan": 8636,
    "internazionale": 8636,
    "internazionale milano": 8636,
    "fc internazionale milano": 8636,
    "lask": 9977,
    "lask linz": 9977,
    "leipzig": 178475,
    "rb leipzig": 178475,
    "lens": 8588,
    "lille": 8639,
    "lille osc": 8639,
    "losc lille": 8639,
    "liverpool": 8650,
    "man city": 8456,
    "manchester city": 8456,
    "man united": 10260,
    "manchester united": 10260,
    "napoli": 9875,
    "ssc napoli": 9875,
    "paris": 9847,
    "paris saint germain": 9847,
    "psg": 9847,
    "porto": 9773,
    "fc porto": 9773,
    "psv": 8640,
    "psv eindhoven": 8640,
    "real betis": 8603,
    "real betis balompie": 8603,
    "real betis balompié": 8603,
    "real betis seville": 8603,
    "real madrid": 8633,
    "real madrid cf": 8633,
    "roma": 8686,
    "as roma": 8686,
    "sabah": 951893,
    "sabah fk": 951893,
    "shakhtar": 9728,
    "shakhtar donetsk": 9728,
    "slavia praha": 7787,
    "slavia prague": 7787,
    "slovan bratislava": 6019,
    "sk slovan bratislava": 6019,
    "sporting cp": 9768,
    "sporting": 9768,
    "stuttgart": 10269,
    "vfb stuttgart": 10269,
    "villarreal": 10205,
    "villarreal cf": 10205,
    "viking": 8478,
    "viking fk": 8478,
}




# Complete the FotMob alias map for all 36 current CL teams.
_CL_FOTMOB_IDS = {
    "aek athens": 8563, "arsenal": 9825, "aston villa": 10252, "atletico madrid": 9906,
    "barcelona": 8634, "bayern munich": 9823, "bodo glimt": 8402, "borussia dortmund": 9789,
    "club brugge": 8262, "como": 10171, "fenerbahce": 8695, "feyenoord": 10235, "galatasaray": 8637,
    "inter": 8636, "lask": 9977, "leipzig": 178475, "lens": 8588, "lille": 8639, "liverpool": 8650,
    "manchester city": 8456, "manchester united": 10260, "napoli": 9875, "paris saint germain": 9847,
    "porto": 9773, "psv eindhoven": 8640, "real betis": 8603, "real madrid": 8633, "roma": 8686,
    "sabah": 951893, "shakhtar donetsk": 9728, "slavia praha": 7787, "slovan bratislava": 6019,
    "sporting cp": 9768, "stuttgart": 10269, "viking": 8478, "villarreal": 10205,
}
for _canonical, _aliases in CL_TEAM_CANONICAL.items():
    _fid = _CL_FOTMOB_IDS.get(_canonical)
    if _fid:
        FOTMOB_KNOWN_TEAM_IDS[normalize_name(_canonical)] = _fid
        for _alias in _aliases:
            FOTMOB_KNOWN_TEAM_IDS[normalize_name(_alias)] = _fid


async def fotmob_find_team_id(session, team_name):
    key = str(team_name).strip().lower()
    if key in FOTMOB_TEAM_CACHE:
        return FOTMOB_TEAM_CACHE[key]

    # Direct IDs are more reliable than the public search endpoint, which
    # can change its JSON shape.
    known_id = FOTMOB_KNOWN_TEAM_IDS.get(normalize_name(team_name))
    if known_id:
        FOTMOB_TEAM_CACHE[key] = int(known_id)
        print(f"   FotMob team: {team_name} -> known id={known_id}")
        return int(known_id)

    # Dynamic Top-5 registry: covers every current club in England, Spain,
    # Italy, Germany and France, including promoted/relegated teams.
    try:
        await _fotmob_load_top5_team_registry(session)
        registry_id = _fotmob_registry_pick_team_id(team_name)
        if registry_id:
            FOTMOB_TEAM_CACHE[key] = int(registry_id)
            print(
                f"   FotMob team: {team_name} -> "
                f"Top-5 registry id={registry_id}"
            )
            return int(registry_id)
    except Exception as e:
        print(f"   ⚠️ FotMob Top-5 registry lookup {team_name}: {e}")

    try:
        data = await fotmob_get(
            session,
            "/api/data/search/suggest",
            {"hits": 50, "lang": "en", "term": team_name},
        )
        team_id, matched_name, score = _fotmob_pick_team_from_search(data, team_name)
        if team_id is not None:
            FOTMOB_TEAM_CACHE[key] = int(team_id)
            print(
                f"   FotMob team: {team_name} -> "
                f"{matched_name} (id={team_id}, match={score:.2f})"
            )
            return int(team_id)
    except Exception as e:
        print(f"   ⚠️ FotMob search {team_name}: {e}")

    try:
        data2 = await fotmob_get(
            session,
            "/api/searchData",
            {"term": team_name},
        )
        team_id, matched_name, score = _fotmob_pick_team_from_search(data2, team_name)
        if team_id is not None:
            FOTMOB_TEAM_CACHE[key] = int(team_id)
            print(
                f"   FotMob team: {team_name} -> "
                f"{matched_name} (id={team_id}, match={score:.2f})"
            )
            return int(team_id)
    except Exception as e:
        print(f"   ⚠️ FotMob legacy search {team_name}: {e}")

    print(f"   ⚠️ FotMob: team not found: {team_name}")
    return None


def _fotmob_walk_match_candidates(obj, out, depth=0):
    """Find match-like dictionaries in the very large /teams payload."""
    if depth > 12 or obj is None:
        return

    if isinstance(obj, dict):
        match_id = obj.get("id") or obj.get("matchId")

        status = obj.get("status")
        has_status = isinstance(status, dict)

        home = obj.get("home") or obj.get("homeTeam")
        away = obj.get("away") or obj.get("awayTeam")

        if (
            match_id is not None
            and has_status
            and isinstance(home, dict)
            and isinstance(away, dict)
        ):
            home_name = (
                home.get("name")
                or home.get("teamName")
                or home.get("shortName")
                or ""
            )
            away_name = (
                away.get("name")
                or away.get("teamName")
                or away.get("shortName")
                or ""
            )
            if home_name and away_name:
                out.append(obj)

        for value in obj.values():
            _fotmob_walk_match_candidates(value, out, depth + 1)

    elif isinstance(obj, list):
        for value in obj:
            _fotmob_walk_match_candidates(value, out, depth + 1)


def _fotmob_extract_match_info(match):
    status = match.get("status") or {}

    utc = (
        status.get("utcTime")
        or match.get("utcTime")
        or match.get("startTime")
        or match.get("kickoff")
    )

    dt = None
    if utc:
        try:
            if isinstance(utc, (int, float)):
                # FotMob sometimes uses milliseconds.
                value = float(utc)
                if value > 10_000_000_000:
                    value /= 1000.0
                dt = datetime.fromtimestamp(value, tz=timezone.utc)
            else:
                value = str(utc).replace("Z", "+00:00")
                dt = datetime.fromisoformat(value)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                else:
                    dt = dt.astimezone(timezone.utc)
        except Exception:
            pass

    home = match.get("home") or match.get("homeTeam") or {}
    away = match.get("away") or match.get("awayTeam") or {}

    home_name = home.get("name") or home.get("teamName") or ""
    away_name = away.get("name") or away.get("teamName") or ""

    reason = str(status.get("reason") or "").upper()
    finished = bool(
        status.get("finished")
        or reason in {"FT", "AET", "PEN", "FINISHED", "AFTER EXTRA TIME", "AFTER PENALTIES"}
    )

    def _score_value(obj, side):
        if not isinstance(obj, dict):
            return None
        for value in (obj.get(side), obj.get(side + "Score"), obj.get(side + "score")):
            if isinstance(value, dict):
                value = value.get("current") if value.get("current") is not None else value.get("display")
            try:
                if value is not None and int(float(value)) >= 0:
                    return int(float(value))
            except Exception:
                pass
        return None

    score_found = False
    for score_obj in (match.get("score"), status.get("score"), match.get("scores")):
        if isinstance(score_obj, dict):
            hg = _score_value(score_obj, "home")
            ag = _score_value(score_obj, "away")
            if hg is not None and ag is not None:
                score_found = True
                break

    finished = finished or score_found

    match_id = match.get("id") or match.get("matchId")

    # FotMob uses several shapes for the competition object. Keep the
    # tournament/league id so V43 can request older season feeds when the
    # current /teams payload only contains a short recent-results window.
    tournament = (
        match.get("tournament")
        or match.get("uniqueTournament")
        or match.get("league")
        or {}
    )
    if not isinstance(tournament, dict):
        tournament = {}

    league_id = (
        match.get("leagueId")
        or match.get("tournamentId")
        or tournament.get("id")
        or tournament.get("uniqueTournamentId")
        or tournament.get("leagueId")
    )

    page_url = (
        match.get("pageUrl")
        or match.get("pageURL")
        or match.get("url")
        or match.get("matchUrl")
        or match.get("matchURL")
        or match.get("href")
        or status.get("pageUrl")
        or status.get("url")
        or ""
    )
    if isinstance(page_url, dict):
        page_url = page_url.get("url") or page_url.get("href") or ""

    return {
        "id": match_id,
        "date": dt,
        "home": home_name,
        "away": away_name,
        "finished": finished,
        "league_id": league_id,
        "page_url": str(page_url or ""),
    }


def parse_fotmob_xg(data):
    """
    Parse match-level xG from FotMob matchDetails.

    Typical structure:
      content.stats.Periods.All.stats = [
        {"title": "Expected goals (xG)", "stats": [home_xg, away_xg]}
      ]

    We also support key-based variants.
    """
    if not isinstance(data, dict):
        return None

    candidates = []

    def inspect_stats_list(rows):
        for row in rows or []:
            if not isinstance(row, dict):
                continue

            title = str(row.get("title") or row.get("name") or "").lower()
            key = str(row.get("key") or row.get("stat") or "").lower()

            is_xg = (
                "expected goals" in title
                or title in {"xg", "expected xg"}
                or key in {"expected_goals", "expectedgoals", "xg"}
            )

            values = row.get("stats")
            if is_xg and isinstance(values, (list, tuple)) and len(values) >= 2:
                home_xg = safe_float(values[0], None)
                away_xg = safe_float(values[1], None)
                if home_xg is not None and away_xg is not None:
                    candidates.append((float(home_xg), float(away_xg)))

    content = data.get("content")
    if isinstance(content, dict):
        stats = content.get("stats")
        if isinstance(stats, dict):
            periods = stats.get("Periods") or stats.get("periods") or {}
            if isinstance(periods, dict):
                # Prefer ALL/full-match period.
                all_period = (
                    periods.get("All")
                    or periods.get("ALL")
                    or periods.get("all")
                )
                if isinstance(all_period, dict):
                    inspect_stats_list(all_period.get("stats"))

                for period_name, period in periods.items():
                    if period is all_period or not isinstance(period, dict):
                        continue
                    inspect_stats_list(period.get("stats"))

    # Some responses flatten stats differently.
    def walk(obj, depth=0):
        if depth > 10 or obj is None:
            return

        if isinstance(obj, dict):
            title = str(
                obj.get("title")
                or obj.get("name")
                or obj.get("key")
                or obj.get("stat")
                or ""
            ).lower()

            if (
                "expected goals" in title
                or title in {"xg", "expected_goals", "expectedgoals"}
            ):
                values = obj.get("stats")
                if isinstance(values, (list, tuple)) and len(values) >= 2:
                    h = safe_float(values[0], None)
                    a = safe_float(values[1], None)
                    if h is not None and a is not None:
                        candidates.append((float(h), float(a)))

            for value in obj.values():
                walk(value, depth + 1)

        elif isinstance(obj, list):
            for value in obj:
                walk(value, depth + 1)

    walk(data)

    # Remove duplicates while preserving order.
    unique = []
    seen = set()
    for item in candidates:
        key = (round(item[0], 6), round(item[1], 6))
        if key not in seen:
            seen.add(key)
            unique.append(item)

    if unique:
        return {
            "home_xg": unique[0][0],
            "away_xg": unique[0][1],
        }

    return None


def parse_fotmob_corners(data):
    """Extract full-match home/away corner counts from FotMob matchDetails."""
    if not isinstance(data, dict):
        return None

    candidates = []

    def inspect_stats_list(rows):
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or row.get("name") or "").strip().lower()
            key = str(row.get("key") or row.get("stat") or "").strip().lower()
            if title != "corners" and key not in {"corners", "corner_kicks", "cornerkicks"}:
                continue
            values = row.get("stats")
            if isinstance(values, (list, tuple)) and len(values) >= 2:
                h = safe_float(values[0], None)
                a = safe_float(values[1], None)
                if h is not None and a is not None and h >= 0 and a >= 0:
                    candidates.append((float(h), float(a)))

    content = data.get("content")
    if isinstance(content, dict):
        stats = content.get("stats")
        if isinstance(stats, dict):
            periods = stats.get("Periods") or stats.get("periods") or {}
            if isinstance(periods, dict):
                all_period = periods.get("All") or periods.get("ALL") or periods.get("all")
                if isinstance(all_period, dict):
                    inspect_stats_list(all_period.get("stats"))
                for period in periods.values():
                    if isinstance(period, dict) and period is not all_period:
                        inspect_stats_list(period.get("stats"))

    # Flattened/alternative FotMob response shapes.
    def walk(obj, depth=0):
        if depth > 10 or obj is None:
            return
        if isinstance(obj, dict):
            title = str(obj.get("title") or obj.get("name") or obj.get("key") or obj.get("stat") or "").strip().lower()
            if title in {"corners", "corner kicks", "corner_kicks", "cornerkicks"}:
                values = obj.get("stats")
                if isinstance(values, (list, tuple)) and len(values) >= 2:
                    h = safe_float(values[0], None)
                    a = safe_float(values[1], None)
                    if h is not None and a is not None and h >= 0 and a >= 0:
                        candidates.append((float(h), float(a)))
            for value in obj.values():
                walk(value, depth + 1)
        elif isinstance(obj, list):
            for value in obj:
                walk(value, depth + 1)

    walk(data)

    unique = []
    seen = set()
    for item in candidates:
        key = (round(item[0], 6), round(item[1], 6))
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique[0] if unique else None


def _fotmob_slug_part(name):
    """Build FotMob-style URL slug from a team name."""
    import unicodedata
    value = str(name or "").strip().lower()
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value


def _fotmob_match_page_urls(info):
    """Return current FotMob match-page URL candidates.

    Important: current FotMob match URLs are slug + short match id, e.g.
    /matches/club-brugge-vs-aston-villa/2uxjqh. The old /matches/{numeric_id}
    form used by V62 is no longer valid for many fixtures.
    """
    match_id = info.get("id")
    home = info.get("home") or ""
    away = info.get("away") or ""
    urls = []

    explicit = info.get("page_url") or ""
    if explicit:
        urls.append(str(explicit).strip())

    if match_id and home and away:
        hs = _fotmob_slug_part(home)
        aws = _fotmob_slug_part(away)
        if hs and aws:
            path = f"/matches/{hs}-vs-{aws}/{match_id}"
            urls.append(FOTMOB_BASE_URL + path)
            urls.append(FOTMOB_BASE_URL + "/en-GB" + path)

    # Legacy fallback kept for older feeds.
    if match_id:
        urls.append(f"{FOTMOB_BASE_URL}/matches/{match_id}")

    result = []
    seen = set()
    for url in urls:
        if url and url not in seen:
            seen.add(url)
            result.append(url)
    return result


async def _fotmob_match_page_details(session, page_url, match_id=None):
    """Fetch match details from the public FotMob match page.

    FotMob has been returning 404 for the old JSON matchDetails endpoint on
    some current matches. The public match page still hydrates the match data
    into a __NEXT_DATA__ JSON script. We use that as the primary fallback.
    """
    if not page_url:
        return None

    url = str(page_url).strip()
    if url.startswith("/"):
        url = FOTMOB_BASE_URL + url
    elif not url.startswith("http://") and not url.startswith("https://"):
        url = FOTMOB_BASE_URL + "/" + url.lstrip("/")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/140.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.fotmob.com/",
        "Cache-Control": "no-cache",
    }

    async with session.get(
        url,
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=30),
        ssl=False,
        allow_redirects=True,
    ) as resp:
        body = await resp.text()
        if resp.status != 200:
            raise RuntimeError(f"FotMob page HTTP {resp.status}: {body[:300]}")

    # __NEXT_DATA__ is the cleanest source when present.
    match = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        body,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match:
        raw = html.unescape(match.group(1))
        try:
            root = json.loads(raw)
        except Exception:
            root = None

        if root is not None:
            def find_details(obj, depth=0):
                if depth > 14 or obj is None:
                    return None
                if isinstance(obj, dict):
                    content = obj.get("content")
                    if isinstance(content, dict):
                        stats = content.get("stats")
                        if isinstance(stats, dict):
                            periods = stats.get("Periods") or stats.get("periods")
                            if isinstance(periods, dict):
                                return obj
                    # Common direct containers.
                    for key in ("matchDetails", "match", "data", "pageProps", "props"):
                        if key in obj:
                            found = find_details(obj.get(key), depth + 1)
                            if found is not None:
                                return found
                    for value in obj.values():
                        found = find_details(value, depth + 1)
                        if found is not None:
                            return found
                elif isinstance(obj, list):
                    for value in obj:
                        found = find_details(value, depth + 1)
                        if found is not None:
                            return found
                return None

            found = find_details(root)
            if found is not None:
                return found

            # Sometimes the useful object is nested under pageProps but does
            # not expose the exact stats shape until another level is walked.
            if isinstance(root, dict):
                pp = root.get("props", {}).get("pageProps") if isinstance(root.get("props"), dict) else None
                if pp is not None:
                    return pp

    # Last-resort JSON-ish extraction: search the HTML for a serialized
    # content.stats block. This is deliberately conservative; if it cannot
    # recover valid JSON we return None rather than fabricating corners.
    return None


async def _fotmob_get_match_details_resilient(session, info):
    """Get match details with the fastest JSON routes first.

    V63 tried several public HTML/slug URLs before the JSON endpoint. On the
    current FotMob site those page URLs frequently return 404, causing three
    wasted network round-trips per match. The web version reverses the order:
    JSON first, HTML only as a last-resort compatibility fallback.
    """
    match_id = info.get("id")

    # Fast/current JSON route first, legacy JSON second.
    for path in ("/api/data/matchDetails", "/api/matchDetails"):
        try:
            data = await fotmob_get(session, path, {"matchId": match_id})
            if data:
                return data
        except Exception:
            continue

    # Last resort only. Keep this for compatibility if FotMob changes JSON.
    for page_url in _fotmob_match_page_urls(info):
        try:
            data = await _fotmob_match_page_details(session, page_url, match_id)
            if data:
                return data
        except Exception:
            # Do not spam the console with repeated HTML 404s in normal use.
            continue

    return None


async def fotmob_match_xg(session, match_id, home_name, away_name, page_url=""):
    key = str(match_id)
    if key in FOTMOB_MATCH_CACHE:
        return FOTMOB_MATCH_CACHE[key]

    disk_match = _load_fotmob_match_disk(key)
    if disk_match is not None:
        FOTMOB_MATCH_CACHE[key] = disk_match.get("xg")
        FOTMOB_MATCH_CORNERS_CACHE[key] = disk_match.get("corners")
        return disk_match.get("xg")

    info = {
        "id": match_id,
        "home": home_name,
        "away": away_name,
        "page_url": page_url,
    }

    try:
        data = await _fotmob_get_match_details_resilient(session, info)
        if not data:
            FOTMOB_MATCH_CACHE[key] = None
            return None

        parsed = parse_fotmob_xg(data)
        corners = parse_fotmob_corners(data)
        FOTMOB_MATCH_CORNERS_CACHE[key] = corners
        FOTMOB_MATCH_CACHE[key] = parsed
        _save_fotmob_match_disk(key, parsed, corners)

        if parsed:
            print(
                f"      xG {home_name} {parsed['home_xg']:.2f} - "
                f"{parsed['away_xg']:.2f} {away_name}"
            )

        return parsed

    except Exception as e:
        print(f"      ⚠️ FotMob match xG {home_name} - {away_name}: {e}")
        FOTMOB_MATCH_CACHE[key] = None
        return None


async def _fotmob_load_historical_team_matches(session, target_name, cutoff, league_ids):
    """
    Load older finished team matches from FotMob league-season feeds.

    The current /api/data/teams response can contain many future fixtures but
    only a limited recent-results window. When that happens, older seasons are
    used as a second source of match IDs. We only return matches involving the
    requested team and occurring before the analysis cutoff.
    """
    historical = {}

    if not league_ids:
        return []

    hist_cache_key = (
        normalize_name(target_name),
        str(cutoff)[:10],
        tuple(sorted(str(x) for x in league_ids if x not in (None, "", 0))),
    )
    cached_historical = FOTMOB_HISTORICAL_MATCHES_CACHE.get(hist_cache_key)
    if cached_historical is not None:
        return cached_historical

    try:
        cutoff_year = cutoff.year
        season_start = cutoff_year if cutoff.month >= 7 else cutoff_year - 1
    except Exception:
        season_start = datetime.now(timezone.utc).year

    normalized_league_ids = sorted({str(x) for x in league_ids if x not in (None, "", 0)})

    # FAST mode: team payloads often contain cup/friendly competition IDs in
    # addition to the domestic league. For Top-5 clubs the domestic feed is
    # the best historical source and avoids 4-6 unnecessary league requests.
    top5_ids = {str(x) for x in FOTMOB_TOP5_LEAGUE_IDS.values()}
    domestic_ids = [x for x in normalized_league_ids if x in top5_ids]
    if domestic_ids:
        normalized_league_ids = domestic_ids[:1]

    for league_id in normalized_league_ids:
        for offset in range(1, FOTMOB_HISTORICAL_SEASONS + 1):
            start_year = season_start - offset
            season = f"{start_year}/{start_year + 1}"

            try:
                data = await fotmob_get(
                    session,
                    "/api/data/leagues",
                    {
                        "id": league_id,
                        "season": season,
                    },
                )
            except Exception as e:
                print(
                    f"      ⚠️ FotMob historical league {league_id} "
                    f"{season}: {e}"
                )
                continue

            rows = []
            _fotmob_walk_match_candidates(data, rows)

            for row in rows:
                info = _fotmob_extract_match_info(row)
                if not info["id"] or info["date"] is None:
                    continue
                if info["date"] >= cutoff or not info["finished"]:
                    continue
                if not (
                    names_match(target_name, info["home"])
                    or names_match(target_name, info["away"])
                ):
                    continue

                info["league_id"] = info.get("league_id") or league_id
                historical[str(info["id"])] = info

    result = list(historical.values())
    result.sort(key=lambda x: x["date"], reverse=True)

    if result:
        print(
            f"      📚 FotMob historical fallback: {len(result)} "
            f"older matches found from {len(set(str(x) for x in league_ids))} leagues"
        )

    FOTMOB_HISTORICAL_MATCHES_CACHE[hist_cache_key] = result
    return result


async def get_fotmob_xg_for_team(team, before_date, limit=XG_MATCHES):
    target_name = team.get("name", "")

    try:
        cutoff = datetime.fromisoformat(
            str(before_date).replace("Z", "+00:00")
        )
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=timezone.utc)
        else:
            cutoff = cutoff.astimezone(timezone.utc)
    except Exception:
        cutoff = datetime.now(timezone.utc)

    cache_key = ("fotmob", target_name.lower(), str(cutoff)[:10], limit)
    cached_result = FOTMOB_CACHE.get(cache_key)
    if isinstance(cached_result, dict):
        cached_sample = int(cached_result.get("sample") or 0)
        if cached_sample >= limit:
            print(f"   ⚡ xG CACHE: {target_name} → {cached_sample}/{limit}")
            return cached_result
        if cached_sample > 0:
            print(
                f"   ♻️ xG CACHE incomplete: {target_name} → "
                f"{cached_sample}/{limit}; добираємо історію"
            )

    empty = {
        "available": False,
        "matches": [],
        "sample": 0,
        "xg": None,
        "xga": None,
        "home_xg": None,
        "home_xga": None,
        "away_xg": None,
        "away_xga": None,
    }

    timeout = aiohttp.ClientTimeout(total=40)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        team_id = await fotmob_find_team_id(session, target_name)
        if not team_id:
            return empty

        team_data = await fotmob_get_team_data(session, team_id)
        if not isinstance(team_data, dict):
            return empty

        raw_matches = []
        _fotmob_walk_match_candidates(team_data, raw_matches)

        # Deduplicate by match id.
        unique_matches = {}
        for row in raw_matches:
            info = _fotmob_extract_match_info(row)
            if not info["id"]:
                continue
            unique_matches[str(info["id"])] = info

        candidates = []
        skipped_no_date = 0
        skipped_future = 0
        skipped_unfinished = 0
        skipped_team = 0

        for info in unique_matches.values():
            dt = info["date"]
            if dt is None:
                skipped_no_date += 1
                continue
            if dt >= cutoff:
                skipped_future += 1
                continue
            if not info["finished"]:
                skipped_unfinished += 1
                continue
            if not (
                names_match(target_name, info["home"])
                or names_match(target_name, info["away"])
            ):
                skipped_team += 1
                continue
            candidates.append(info)

        candidates.sort(key=lambda x: x["date"], reverse=True)

        # Start with recent team payload. Historical league matches are added
        # only when the *actual xG sample* is still below the requested limit.
        # This is the key difference from V3.1.2: 12 recent fixtures may contain
        # only 5 matches with xG, so counting fixture IDs alone was insufficient.
        recent_candidates = candidates[: min(
            XG_MAX_CANDIDATES,
            max(limit * XG_CANDIDATE_MULTIPLIER, 24),
        )]

        records = []
        processed_ids = set()

        async def consume(batch):
            for info in batch:
                if len(records) >= limit:
                    break
                match_id = str(info.get("id") or "")
                if not match_id or match_id in processed_ids:
                    continue
                processed_ids.add(match_id)

                parsed = await fotmob_match_xg(
                    session,
                    info["id"],
                    info["home"],
                    info["away"],
                )
                if not parsed:
                    continue

                is_home = names_match(target_name, info["home"])
                team_xg = parsed["home_xg"] if is_home else parsed["away_xg"]
                opp_xg = parsed["away_xg"] if is_home else parsed["home_xg"]

                records.append({
                    "date": info["date"],
                    "team_xg": float(team_xg),
                    "xga": float(opp_xg),
                    "venue": "home" if is_home else "away",
                    "league": "fotmob",
                    "match_id": info["id"],
                    "opponent": info["away"] if is_home else info["home"],
                })

        await consume(recent_candidates)

        if len(records) < limit:
            league_ids = [info.get("league_id") for info in unique_matches.values()]
            league_ids = [x for x in league_ids if x not in (None, "", 0)]
            if league_ids:
                print(
                    f"      ♻️ xG backfill {target_name}: "
                    f"{len(records)}/{limit}, добираємо старі матчі"
                )
                historical = await _fotmob_load_historical_team_matches(
                    session, target_name, cutoff, league_ids
                )
                # Historical rows are already sorted newest-first. Consume only
                # IDs not tried above; matchDetails themselves are persistent-cached.
                await consume(historical)

        records.sort(key=lambda r: r["date"], reverse=True)
        records = records[:limit]
        recent_records = records[:5]

        print(
            f"   FotMob REAL xG sample for {target_name}: "
            f"{len(records)}/{limit}"
        )
        print(
            f"      filter: no_date={skipped_no_date} | future={skipped_future} | "
            f"unfinished={skipped_unfinished} | wrong_team={skipped_team}"
        )

        result = {
            "available": len(records) >= XG_MIN_MATCHES,
            "matches": records,
            "sample": len(records),
            "recent_sample": len(recent_records),
            "xg": (
                round(sum(r["team_xg"] for r in records) / len(records), 3)
                if records else None
            ),
            "xga": (
                round(sum(r["xga"] for r in records) / len(records), 3)
                if records else None
            ),
            "recent_xg": (
                round(sum(r["team_xg"] for r in recent_records) / len(recent_records), 3)
                if recent_records else None
            ),
            "recent_xga": (
                round(sum(r["xga"] for r in recent_records) / len(recent_records), 3)
                if recent_records else None
            ),
            "home_xg": None,
            "home_xga": None,
            "away_xg": None,
            "away_xga": None,
        }

        home_records = [r for r in records if r["venue"] == "home"]
        away_records = [r for r in records if r["venue"] == "away"]

        if home_records:
            result["home_xg"] = round(
                sum(r["team_xg"] for r in home_records) / len(home_records), 3
            )
            result["home_xga"] = round(
                sum(r["xga"] for r in home_records) / len(home_records), 3
            )

        if away_records:
            result["away_xg"] = round(
                sum(r["team_xg"] for r in away_records) / len(away_records), 3
            )
            result["away_xga"] = round(
                sum(r["xga"] for r in away_records) / len(away_records), 3
            )

    FOTMOB_CACHE[cache_key] = result
    return result


async def get_real_xg_for_team(team, before_date, limit=XG_MATCHES):
    """
    Get REAL match-level xG.

    Priority:
      1) FotMob matchDetails xG
      2) empty/unavailable state

    No synthetic xG is returned. If the upstream source does not provide
    xG, the bot keeps xG=None instead of inventing a value.
    """
    empty = {
        "available": False,
        "matches": [],
        "sample": 0,
        "xg": None,
        "xga": None,
        "home_xg": None,
        "home_xga": None,
        "away_xg": None,
        "away_xga": None,
    }

    try:
        result = await get_fotmob_xg_for_team(
            team,
            before_date,
            limit,
        )
        if result.get("sample", 0) > 0:
            return result
    except Exception as e:
        print(f"   ⚠️ FotMob REAL xG error: {e}")

    return empty



def blend_real_xg(base_home_xg, base_away_xg, home_real, away_real):
    """Blend base stats with real FotMob xG using sample-aware weights."""
    if not isinstance(home_real, dict) or not isinstance(away_real, dict):
        return base_home_xg, base_away_xg

    home_for = home_real.get("home_xg") if home_real.get("home_xg") is not None else home_real.get("xg")
    home_against = home_real.get("home_xga") if home_real.get("home_xga") is not None else home_real.get("xga")
    away_for = away_real.get("away_xg") if away_real.get("away_xg") is not None else away_real.get("xg")
    away_against = away_real.get("away_xga") if away_real.get("away_xga") is not None else away_real.get("xga")

    if any(v is None for v in (home_for, home_against, away_for, away_against)):
        return base_home_xg, base_away_xg

    def observed(team, recent_key, full_key):
        recent = team.get(recent_key)
        full = team.get(full_key)
        if recent is not None and full is not None:
            return float(recent) * 0.60 + float(full) * 0.40
        return float(full if full is not None else recent)

    home_for_eff = observed(home_real, "recent_xg", "home_xg")
    home_against_eff = observed(home_real, "recent_xga", "home_xga")
    away_for_eff = observed(away_real, "recent_xg", "away_xg")
    away_against_eff = observed(away_real, "recent_xga", "away_xga")

    real_home = home_for_eff * 0.60 + away_against_eff * 0.40
    real_away = away_for_eff * 0.60 + home_against_eff * 0.40

    coverage = min(int(home_real.get("sample") or 0), int(away_real.get("sample") or 0))
    if coverage >= 10:
        real_weight = 0.45
    elif coverage >= 7:
        real_weight = 0.40
    elif coverage >= 5:
        real_weight = 0.35
    elif coverage >= 4:
        real_weight = 0.20
    else:
        return base_home_xg, base_away_xg

    home_xg = base_home_xg * (1.0 - real_weight) + real_home * real_weight
    away_xg = base_away_xg * (1.0 - real_weight) + real_away * real_weight
    return max(0.20, min(home_xg, 4.50)), max(0.20, min(away_xg, 4.50))

# ============================================================
# MODEL BUILDER
# ============================================================

def build_model(home_team, away_team, histories, before_date, real_xg=None):
    home_id = home_team.get("id")
    away_id = away_team.get("id")
    home_history = histories.get(home_id, []) if isinstance(histories, dict) else []
    away_history = histories.get(away_id, []) if isinstance(histories, dict) else []

    home_form_results = calculate_form(home_history, home_id, before_date, limit=HISTORY_FORM_MATCHES)
    away_form_results = calculate_form(away_history, away_id, before_date, limit=HISTORY_FORM_MATCHES)

    home_form = form_stats(home_form_results)
    away_form = form_stats(away_form_results)

    home_home_form_results = calculate_form(home_history, home_id, before_date, home_only=True, limit=HISTORY_FORM_MATCHES)
    away_away_form_results = calculate_form(away_history, away_id, before_date, away_only=True, limit=HISTORY_FORM_MATCHES)

    home_home_form = form_stats(home_home_form_results)
    away_away_form = form_stats(away_away_form_results)

    home_weighted = calculate_weighted_stats(home_history, home_id, before_date, home_only=True)
    away_weighted = calculate_weighted_stats(away_history, away_id, before_date, away_only=True)

    baseline = get_baseline_stats()
    if not home_weighted:
        home_weighted = baseline.copy()
    if not away_weighted:
        away_weighted = baseline.copy()

    h2h_matches = get_h2h_matches(
        home_id, away_id, home_history, away_history, before_date
    )
    h2h = calculate_h2h_stats(h2h_matches, home_id, away_id)

    home_halves = calculate_half_stats(home_history, home_id, before_date, home_only=True)
    away_halves = calculate_half_stats(away_history, away_id, before_date, away_only=True)

    base_home_xg, base_away_xg = calculate_xg_v25(
        safe_float(home_weighted.get("attack"), 1.35),
        safe_float(home_weighted.get("defence"), 1.35),
        safe_float(away_weighted.get("attack"), 1.35),
        safe_float(away_weighted.get("defence"), 1.35),
        home_form,
        away_form,
        h2h,
    )

    home_real_xg = real_xg.get("home") if isinstance(real_xg, dict) else None
    away_real_xg = real_xg.get("away") if isinstance(real_xg, dict) else None

    home_xg, away_xg = blend_real_xg(
        base_home_xg,
        base_away_xg,
        home_real_xg,
        away_real_xg,
    )

    probabilities = calculate_probabilities(home_xg, away_xg)
    probabilities = calculate_market_probabilities(
        probabilities, home_form, away_form, h2h
    )

    return {
        "home_xg": safe_float(home_xg),
        "away_xg": safe_float(away_xg),
        "base_home_xg": safe_float(base_home_xg),
        "base_away_xg": safe_float(base_away_xg),
        "real_xg": real_xg or {},
        "probabilities": probabilities,
        "home_home_form": home_home_form,
        "away_away_form": away_away_form,
        "home_halves": home_halves,
        "away_halves": away_halves,
        "h2h": h2h,
    }


# ============================================================
# VALUE CANDIDATES
# ============================================================

def calculate_bet_score(
    probability,
    best_odds_value,
    confidence,
    market_value,
    best_value,
    market
):
    """Rank a bet using probability, confidence and market-wide value.

    V47 deliberately separates:
      - best bookmaker odds: useful for the user when placing a bet;
      - median bookmaker odds: used as the market benchmark;
      - market_value: model probability versus the median price.

    This prevents one unusually high bookmaker price from dominating the
    ranking merely because it creates an artificial-looking Value edge.
    """
    probability = safe_float(probability, 0.0)
    best_odds_value = safe_float(best_odds_value, 0.0)
    confidence = safe_float(confidence, 0.0)
    market_value = safe_float(market_value, 0.0)
    best_value = safe_float(best_value, 0.0)

    if probability <= 0 or best_odds_value <= 1:
        return 0.0

    probability_score = probability * 100.0
    confidence_score = confidence

    # Market-wide value is the main price-quality signal.
    market_value_score = max(-20.0, min(20.0, market_value * 100.0))

    # Best-price value is retained, but has only a small influence.
    best_value_score = max(-20.0, min(20.0, best_value * 100.0))

    market_bonus = {
        "double_home": 6.0,
        "double_away": 6.0,
        "over_25": 3.0,
        "under_25": 3.0,
        "btts_yes": 2.0,
        "btts_no": 2.0,
        "home_win": 0.0,
        "draw": -2.0,
        "away_win": 0.0,
    }.get(market, 0.0)

    score = (
        probability_score * 0.48
        + confidence_score * 0.30
        + market_value_score * 0.15
        + best_value_score * 0.07
        + market_bonus
    )

    return round(max(0.0, min(100.0, score)), 2)


def classify_candidate(candidate):
    """Classify a candidate without letting a negative-value favorite win.

    STRONG BET requires both positive market-wide value and high confidence.
    VALUE BET requires positive market-wide value plus a meaningful confidence
    level. Everything else is NO BET.
    """
    if not isinstance(candidate, dict):
        return "NO BET"

    market_value = safe_float(candidate.get("market_value"), 0.0)
    confidence = safe_float(candidate.get("confidence"), 0.0)
    probability = safe_float(candidate.get("probability"), 0.0)

    if market_value >= 0.03 and confidence >= 55.0 and probability >= 0.50:
        return "STRONG BET"
    if market_value >= 0.02 and confidence >= 30.0:
        return "VALUE BET"
    return "NO BET"


def find_candidates(probabilities, real_odds, market_consensus=None, real_xg=None):
    """Build and rank betting candidates using market-wide odds and model edge."""
    if not isinstance(probabilities, dict) or not isinstance(real_odds, dict):
        return []

    markets = [
        ("home_win", "П1", "home"),
        ("draw", "X", "draw"),
        ("away_win", "П2", "away"),
        ("double_home", "1X", "double_home"),
        ("double_away", "X2", "double_away"),
        ("over_25", "ТБ 2.5", "over25"),
        ("under_25", "ТМ 2.5", "under25"),
        ("btts_yes", "ОЗ — Так", "btts_yes"),
        ("btts_no", "ОЗ — Ні", "btts_no"),
    ]

    candidates = []
    for probability_key, name, odds_key in markets:
        probability = safe_float(probabilities.get(probability_key), -1.0)
        if probability < 0 or probability > 1:
            continue

        odds_values = real_odds.get(odds_key, [])
        best = best_odds(odds_values)
        median = median_odds(odds_values)

        if best is None:
            continue

        # For ranking, require a real market benchmark whenever possible.
        benchmark_odds = median if median is not None else best

        best_value = calculate_value(probability, best)
        market_value = calculate_value(probability, benchmark_odds)

        # Model edge = model probability minus de-vig market probability.
        consensus_key = {
            "home_win": "home",
            "draw": "draw",
            "away_win": "away",
        }.get(probability_key)
        market_probability = None
        if isinstance(market_consensus, dict) and consensus_key:
            market_probability = safe_float(market_consensus.get(consensus_key), None)
        model_edge = (probability - market_probability) if market_probability is not None else 0.0

        # REAL xG quality: 10 matches = full credit, 5 = half, below 5 = none.
        real_xg_quality = 0.0
        if isinstance(real_xg, dict):
            samples = []
            for side in ("home", "away"):
                block = real_xg.get(side)
                if isinstance(block, dict):
                    samples.append(safe_float(block.get("sample"), 0.0))
            if samples:
                real_xg_quality = min(samples) / 10.0

        confidence = calculate_confidence(
            probability,
            market_value,
            probability_key,
            model_edge=model_edge,
            real_xg_quality=real_xg_quality
        )

        bet_score = calculate_bet_score(
            probability,
            best,
            confidence,
            market_value if market_value is not None else 0.0,
            best_value if best_value is not None else 0.0,
            probability_key
        )

        candidates.append({
            "market": probability_key,
            "name": name,
            "probability": probability,
            "odds": best,
            "best_odds": best,
            "median_odds": median,
            "value": best_value,
            "best_value": best_value,
            "market_value": market_value,
            "model_edge": model_edge,
            "real_xg_quality": real_xg_quality,
            "confidence": confidence,
            "bet_score": bet_score,
        })
        candidates[-1]["category"] = classify_candidate(candidates[-1])

    candidates.sort(
        key=lambda x: (
            1 if x.get("category") in ("STRONG BET", "VALUE BET") else 0,
            1 if safe_float(x.get("market_value")) > 0 else 0,
            safe_float(x.get("bet_score")),
            safe_float(x.get("confidence")),
            safe_float(x.get("market_value")),
            safe_float(x.get("probability")),
            safe_float(x.get("best_value")),
        ),
        reverse=True,
    )
    return candidates


# ============================================================
# ANALYZE MATCH
# ============================================================

async def analyze_match(
    home_team,
    away_team
):

    print()
    print("=" * 70)

    print(
        f"АНАЛІЗ: "
        f"{home_team['name']} - "
        f"{away_team['name']}"
    )

    # ========================================================
    # HISTORY
    # ========================================================

    # Independent team histories can be loaded in parallel. The Football API
    # layer still handles 429s and each result is cached for subsequent runs.
    home_history, away_history = await asyncio.gather(
        get_team_history(home_team["id"]),
        get_team_history(away_team["id"]),
    )

    if not isinstance(
        home_history,
        list
    ):
        home_history = []

    if not isinstance(
        away_history,
        list
    ):
        away_history = []

    histories = {
        home_team["id"]:
            home_history,

        away_team["id"]:
            away_history,
    }

    before_date = datetime.now(
        timezone.utc
    ).isoformat()

    # ========================================================
    # REAL xG
    # ========================================================

    real_xg = {"home": None, "away": None}

    if True:
        print()
        print("📈 REAL xG: FotMob")
        try:
            real_xg["home"], real_xg["away"] = await asyncio.gather(
                get_real_xg_for_team(home_team, before_date, XG_MATCHES),
                get_real_xg_for_team(away_team, before_date, XG_MATCHES),
            )

            print(
                f"   {home_team['name']}: "
                f"xG={real_xg['home'].get('xg') if real_xg['home'] else None} | "
                f"xGA={real_xg['home'].get('xga') if real_xg['home'] else None} | "
                f"recent5={real_xg['home'].get('recent_xg') if real_xg['home'] else None} | "
                f"sample={real_xg['home'].get('sample') if real_xg['home'] else 0}"
            )
            print(
                f"   {away_team['name']}: "
                f"xG={real_xg['away'].get('xg') if real_xg['away'] else None} | "
                f"xGA={real_xg['away'].get('xga') if real_xg['away'] else None} | "
                f"recent5={real_xg['away'].get('recent_xg') if real_xg['away'] else None} | "
                f"sample={real_xg['away'].get('sample') if real_xg['away'] else 0}"
            )
        except Exception as e:
            print(f"   ⚠️ REAL xG error: {e}")
    else:
        print("⚠️ REAL xG unavailable")

    # ========================================================
    # MODEL
    # ========================================================

    try:

        model = build_model(
            home_team,
            away_team,
            histories,
            before_date,
            real_xg=real_xg,
        )

    except Exception as e:

        print(
            f"❌ Помилка build_model: "
            f"{repr(e)}"
        )

        raise

    # ========================================================
    # DEFAULT REAL ODDS
    # ========================================================

    real_odds = {

        "home": [],
        "draw": [],
        "away": [],
        "double_home": [],
        "double_away": [],

        "over25": [],
        "under25": [],

        "btts_yes": [],
        "btts_no": [],

        "bookmakers": [],
    }

    odds_event = None
    odds_events = []

    # ========================================================
    # ODDS API
    # ========================================================

    try:

        odds_key = home_team.get(
            "odds_key"
        )

        if not odds_key:

            print(
                "⚠️ У команди немає odds_key"
            )

        else:

            # Спочатку шукаємо сам матч серед усіх актуальних футбольних
            # competition feeds. Це критично для міжлігових турнірів:
            # Borussia Dortmund - Villarreal не є Bundesliga, навіть якщо
            # Dortmund є домашньою командою.
            found_sport_key, cross_event = await find_odds_event_across_sports(
                home_team,
                away_team,
                preferred_key=odds_key,
            )

            if cross_event is not None:
                odds_key = found_sport_key
                event_with_odds = await odds_api_event_get(
                    odds_key,
                    cross_event.get("id"),
                    "h2h,totals"
                )

                if isinstance(event_with_odds, dict) and event_with_odds.get("bookmakers"):
                    odds_event = event_with_odds
                    print(
                        f"✅ Реальні коефіцієнти знайдено через competition feed: {odds_key}"
                    )
                else:
                    print(
                        "⚠️ Матч знайдено, але /events/{id}/odds не повернув букмекера. "
                        "Переходимо до стандартного /odds fallback."
                    )

            # Fallback: стандартний /odds для початкової ліги команди.
            # Це також корисно, коли cross-competition /events тимчасово не
            # містить матч, але /odds вже його показує.
            if odds_event is None:
                # ВАЖЛИВО: /sports/{sport}/odds НЕ підтримує double_chance.
                # Спочатку отримуємо тільки стандартні ринки, щоб знайти точний event ID.
                # 1X/X2 запитуємо ОКРЕМО через /events/{eventId}/odds.
                odds_events = await odds_api_get(
                    odds_key,
                    "h2h,totals"
                )

            if odds_event is None:
                if not isinstance(
                    odds_events,
                    list
                ):
                    odds_events = []

                print(
                    f"Odds API подій: "
                    f"{len(odds_events)}"
                )

            if odds_event is None and odds_events:

                try:

                    odds_event = find_odds_event(
                        odds_events,
                        home_team,
                        away_team
                    )

                except Exception as e:

                    print(
                        "⚠️ Помилка пошуку "
                        f"матчу в Odds API: {e}"
                    )

            # Якщо /odds повернув події, але конкретний матч не знайшовся,
            # окремо беремо список events. Потім запитуємо odds за event_id.
            if odds_event is None:
                try:
                    print("🔁 /odds не знайшов точний матч. Перевіряю /events...")
                    event_list = await odds_api_events_get(odds_key)
                    event_candidate = find_odds_event(
                        event_list,
                        home_team,
                        away_team
                    ) if event_list else None

                    if event_candidate is not None:
                        event_with_odds = await odds_api_event_get(
                            odds_key,
                            event_candidate.get("id"),
                            "h2h,totals"
                        )
                        if isinstance(event_with_odds, dict) and event_with_odds.get("bookmakers"):
                            odds_event = event_with_odds
                            print("✅ Отримано реальні коефіцієнти через /events/{id}/odds")
                        else:
                            print("⚠️ Подію знайдено, але букмекери не повернули коефіцієнти")
                except Exception as e:
                    print(f"⚠️ Fallback /events помилка: {e}")

            # У The Odds API кваліфікація Ліги чемпіонів має окремий sport key.
            # Якщо основний CL feed не знайшов матч, перевіряємо qualification feed.
            if odds_event is None and odds_key == "soccer_uefa_champs_league":

                qualification_key = "soccer_uefa_champs_league_qualification"

                print(
                    "🔁 Основний CL feed не знайшов матч. "
                    "Перевіряю CL qualification..."
                )

                qualification_events = await odds_api_get(
                    qualification_key,
                    "h2h,totals"
                )

                if not isinstance(qualification_events, list):
                    qualification_events = []

                print(
                    f"Odds API подій ({qualification_key}): "
                    f"{len(qualification_events)}"
                )

                if qualification_events:

                    try:
                        odds_event = find_odds_event(
                            qualification_events,
                            home_team,
                            away_team
                        )

                        if odds_event is not None:
                            odds_key = qualification_key
                            print("✅ Знайдено матч у CL qualification feed")

                    except Exception as e:
                        print(
                            "⚠️ Помилка пошуку матчу в CL qualification: "
                            f"{e}"
                        )

            if odds_event is not None:

                print(
                    "✅ Знайдено матч у Odds API"
                )

                print(
                    f"{odds_event.get('home_team', '')} "
                    f"- "
                    f"{odds_event.get('away_team', '')}"
                )

                # ====================================================
                # ДОДАТКОВІ РИНКИ ДЛЯ ТОЧНОЇ ПОДІЇ
                # ====================================================
                # The Odds API віддає додаткові soccer markets через
                # /events/{eventId}/odds. 1X/X2 НЕ можна брати з h2h.
                # Тому double_chance запитуємо ОКРЕМО і додаємо тільки
                # його оригінальний market object.

                async def merge_extra_market(market_key):
                    extra = await odds_api_event_get(
                        odds_key,
                        odds_event.get("id"),
                        market_key
                    )
                    if not isinstance(extra, dict):
                        return 0

                    base = odds_event.get("bookmakers", [])
                    if not isinstance(base, list):
                        base = []

                    added = 0
                    for extra_book in extra.get("bookmakers", []):
                        if not isinstance(extra_book, dict):
                            continue

                        target = None
                        for base_book in base:
                            if not isinstance(base_book, dict):
                                continue
                            if (base_book.get("key") and base_book.get("key") == extra_book.get("key")) or (
                                base_book.get("title") and base_book.get("title") == extra_book.get("title")
                            ):
                                target = base_book
                                break

                        if target is None:
                            target = {
                                "key": extra_book.get("key"),
                                "title": extra_book.get("title", extra_book.get("key", "Unknown")),
                                "markets": [],
                            }
                            base.append(target)

                        target_markets = target.get("markets")
                        if not isinstance(target_markets, list):
                            target["markets"] = target_markets = []

                        for market in extra_book.get("markets", []):
                            if not isinstance(market, dict):
                                continue
                            if market.get("key") != market_key:
                                continue

                            # Видаляємо стару версію тільки цього market.
                            target_markets[:] = [
                                m for m in target_markets
                                if not (isinstance(m, dict) and m.get("key") == market_key)
                            ]
                            target_markets.append(market)
                            added += len(market.get("outcomes", [])) if isinstance(market.get("outcomes"), list) else 0

                    odds_event["bookmakers"] = base
                    return added

                try:
                    btts_added = await merge_extra_market("btts")
                    print(f"✅ BTTS market: отримано {btts_added} outcomes")
                except Exception as e:
                    print(f"⚠️ BTTS не отримано: {e}")

                try:
                    dc_added = await merge_extra_market("double_chance")
                    print(f"✅ DOUBLE CHANCE market: отримано {dc_added} outcomes")
                except Exception as e:
                    print(f"⚠️ DOUBLE CHANCE не отримано: {e}")

                # CORNERS: additional event markets are requested separately.
                # The standard h2h,totals feed does not contain corner markets.
                for corner_market in (
                    "alternate_totals_corners",
                    "alternate_team_totals_corners",
                ):
                    try:
                        added = await merge_extra_market(corner_market)
                        if added:
                            print(f"✅ CORNERS market {corner_market}: {added} outcomes")
                    except Exception as e:
                        print(f"⚠️ CORNERS market {corner_market} не отримано: {e}")

                try:

                    extracted_odds = extract_real_odds(
                        odds_event
                    )

                    if isinstance(
                        extracted_odds,
                        dict
                    ):

                        for key in real_odds:

                            if key in extracted_odds:

                                value = extracted_odds.get(
                                    key
                                )

                                if value is not None:

                                    real_odds[key] = value

                except Exception as e:

                    print(
                        "⚠️ Помилка отримання "
                        f"коефіцієнтів: {e}"
                    )

            else:

                print(
                    "⚠️ Майбутній матч "
                    "у Odds API не знайдено"
                )

    except Exception as e:

        print(
            f"❌ Odds API error: {e}"
        )

    # ========================================================
    # REAL ODDS SUMMARY
    # ========================================================

    print()
    print("💰 REAL ODDS SUMMARY")

    print(
        f"Букмекерів: "
        f"{len(real_odds.get('bookmakers', []))}"
    )

    print(
        f"П1: "
        f"{best_odds(real_odds.get('home', []))}"
    )

    print(
        f"X: "
        f"{best_odds(real_odds.get('draw', []))}"
    )

    print(
        f"П2: "
        f"{best_odds(real_odds.get('away', []))}"
    )

    print(
        f"1X: "
        f"{best_odds(real_odds.get('double_home', []))}"
    )

    print(
        f"X2: "
        f"{best_odds(real_odds.get('double_away', []))}"
    )

    print(
        f"ТБ 2.5: "
        f"{best_odds(real_odds.get('over25', []))}"
    )

    print(
        f"ТМ 2.5: "
        f"{best_odds(real_odds.get('under25', []))}"
    )

    print(
        f"ОЗ Так: "
        f"{best_odds(real_odds.get('btts_yes', []))}"
    )

    print(
        f"ОЗ Ні: "
        f"{best_odds(real_odds.get('btts_no', []))}"
    )

    # ========================================================
    # MARKET CONSENSUS DIAGNOSTICS
    # ========================================================

    consensus_home = median_odds(real_odds.get("home", []))
    consensus_draw = median_odds(real_odds.get("draw", []))
    consensus_away = median_odds(real_odds.get("away", []))
    market_1x2 = devig_1x2(
        consensus_home, consensus_draw, consensus_away
    )

    if market_1x2:
        print()
        print("📐 MARKET CONSENSUS vs MODEL")
        print(
            f"   Market (de-vig): P1={pct(market_1x2['home'])} | "
            f"X={pct(market_1x2['draw'])} | "
            f"P2={pct(market_1x2['away'])}"
        )
        print(
            f"   Model:           P1={pct(model['probabilities'].get('home_win', 0))} | "
            f"X={pct(model['probabilities'].get('draw', 0))} | "
            f"P2={pct(model['probabilities'].get('away_win', 0))}"
        )
        print(
            f"   Delta:            P1={pct(model['probabilities'].get('home_win', 0) - market_1x2['home'])} | "
            f"X={pct(model['probabilities'].get('draw', 0) - market_1x2['draw'])} | "
            f"P2={pct(model['probabilities'].get('away_win', 0) - market_1x2['away'])}"
        )
        print(
            f"   Median odds:      P1={consensus_home:.2f} | "
            f"X={consensus_draw:.2f} | P2={consensus_away:.2f}"
        )

    # ========================================================
    # VALUE / CANDIDATES
    # ========================================================

    try:

        candidates = find_candidates(
            model["probabilities"],
            real_odds,
            market_consensus=market_1x2 or {},
            real_xg=model.get("real_xg")
        )

    except Exception as e:

        print(
            f"⚠️ Помилка розрахунку Value: "
            f"{e}"
        )

        candidates = []

    if not isinstance(
        candidates,
        list
    ):
        candidates = []

    # Debug ranking: print every available candidate so model/value selection
    # can be audited before we change the scoring formula.
    if candidates:
        print()
        print("📋 BET CANDIDATES")
        for item in candidates:
            print(
                f"   {item.get('name')}: prob={pct(item.get('probability', 0))} | "
                f"best={safe_float(item.get('best_odds'), 0):.2f} | "
                f"median={safe_float(item.get('median_odds'), 0):.2f} | "
                f"bestV={safe_float(item.get('best_value'), 0) * 100:+.1f}% | "
                f"marketV={safe_float(item.get('market_value'), 0) * 100:+.1f}% | "
                f"edge={safe_float(item.get('model_edge'), 0) * 100:+.1f}pp | "
                f"xGq={safe_float(item.get('real_xg_quality'), 0):.2f} | "
                f"confidence={safe_float(item.get('confidence'), 0):.1f} | "
                f"score={safe_float(item.get('bet_score'), 0):.1f} | "
                f"{item.get('category', 'NO BET')}"
            )

    # --------------------------------------------------------
    # RECOMMENDATIONS
    # --------------------------------------------------------
    # 1) Найвірогідніша ставка = найбільша ймовірність проходу.
    #    Вона НЕ повинна автоматично бути Value.
    # 2) VALUE #1 / VALUE #2 = дві найкращі ставки з позитивним
    #    market-wide Value. Для VALUE використовуємо median odds,
    #    щоб одна аномально висока контора не перекручувала рейтинг.
    # 3) Для двох Value не дозволяємо дублікати одного ринку.

    probability_candidates = [
        item for item in candidates
        if safe_float(item.get("probability"), 0.0) > 0.0
    ]

    most_likely = None
    if probability_candidates:
        most_likely = max(
            probability_candidates,
            key=lambda x: (
                safe_float(x.get("probability"), 0.0),
                safe_float(x.get("confidence"), 0.0),
                safe_float(x.get("market_value"), -999.0),
            )
        )

    # IMPORTANT: candidates are already ranked by the full recommendation
    # score (category -> positive market value -> bet_score -> confidence -> value).
    # Do NOT re-sort here by raw market_value, otherwise a long-shot with a huge
    # theoretical Value (for example P2 @ 16.5) can incorrectly become `best`
    # despite low probability/confidence.  The site's "Bet of the Day" must
    # match the first recommended row in the analysis table.
    value_candidates = [
        item for item in candidates
        if item.get("category") in ("STRONG BET", "VALUE BET")
        and safe_float(item.get("market_value"), 0.0) >= MIN_VALUE
        and safe_float(item.get("probability"), 0.0) > 0.0
    ]

    # Keep the original `candidates` order. It is the canonical model ranking.
    value_bets = value_candidates[:2]

    # `best` is now exactly the strongest ranked recommendation shown first in
    # the betting-markets table. This keeps backend, AI recommendation,
    # "СТАВКА ДНЯ" and mobile TOP VALUE in sync.
    best = value_bets[0] if value_bets else most_likely

    model["best"] = best
    model["most_likely_bet"] = most_likely
    model["value_bets"] = value_bets
    model["candidates"] = candidates

    # ========================================================
    # RESULT
    # ========================================================

    return {

        "home":
            home_team,

        "away":
            away_team,

        "model":
            model,

        "real_odds":
            real_odds,

        "odds_event":
            odds_event,

        "home_history":
            len(home_history),

        "away_history":
            len(away_history),

        "bookmakers_count":
            len(
                real_odds.get(
                    "bookmakers",
                    []
                )
            ),
    }


# ============================================================
# FORMAT ANALYSIS
# ============================================================

def format_analysis(result):

    home = result["home"]

    away = result["away"]

    model = result["model"]

    probabilities = model.get(
        "probabilities",
        {}
    )

    real_odds = result.get(
        "real_odds",
        {}
    )

    best = model.get(
        "best"
    )

    odds_event = result.get(
        "odds_event"
    )

    text = []

    # ========================================================
    # HEADER
    # ========================================================

    text.append(
        "⚽ <b>FOOTBALL AI ANALYST V53</b>"
    )

    text.append("")

    text.append(
        f"<b>{home['name']}</b> — "
        f"<b>{away['name']}</b>"
    )

    text.append("")

    text.append(
        f"🏟 "
        f"{home.get('league_name', '')}"
    )

    # ========================================================
    # DATE
    # ========================================================

    if odds_event:

        commence = odds_event.get(
            "commence_time"
        )

        if commence:

            try:

                dt = datetime.fromisoformat(
                    commence.replace(
                        "Z",
                        "+00:00"
                    )
                )

                local_dt = dt.astimezone()

                text.append("")

                text.append(
                    "🕐 <b>Матч:</b> "
                    +
                    local_dt.strftime(
                        "%d.%m.%Y %H:%M"
                    )
                )

            except Exception:

                pass

    # ========================================================
    # MODEL
    # ========================================================

    text.append("")

    text.append(
        "📊 <b>МОДЕЛЬ V32</b>"
    )

    try:

        home_xg = float(
            model.get(
                "home_xg",
                0
            )
        )

    except (TypeError, ValueError):

        home_xg = 0

    try:

        away_xg = float(
            model.get(
                "away_xg",
                0
            )
        )

    except (TypeError, ValueError):

        away_xg = 0

    text.append(
        f"Очікувані голи моделі: "
        f"<b>{home_xg:.2f}</b> — "
        f"<b>{away_xg:.2f}</b>"
    )

    real_xg = model.get("real_xg", {})
    rx_home = real_xg.get("home") if isinstance(real_xg, dict) else None
    rx_away = real_xg.get("away") if isinstance(real_xg, dict) else None

    if (
        isinstance(rx_home, dict) and rx_home.get("available")
        and isinstance(rx_away, dict) and rx_away.get("available")
    ):
        text.append("")
        text.append("📈 <b>РЕАЛЬНИЙ xG ОСТАННІХ МАТЧІВ</b>")
        def _fmt_xg(value):
            value = safe_float(value, None)
            return f"{value:.2f}" if value is not None else "—"

        text.append(
            f"{home['name']}: xG <b>{_fmt_xg(rx_home.get('xg'))}</b> | "
            f"xGA <b>{_fmt_xg(rx_home.get('xga'))}</b> | "
            f"{rx_home.get('sample', 0)} матчів"
        )
        text.append(
            f"{away['name']}: xG <b>{_fmt_xg(rx_away.get('xg'))}</b> | "
            f"xGA <b>{_fmt_xg(rx_away.get('xga'))}</b> | "
            f"{rx_away.get('sample', 0)} матчів"
        )

    # ========================================================
    # 1X2
    # ========================================================

    text.append("")

    text.append(
        "🎯 <b>ЙМОВІРНОСТІ</b>"
    )

    text.append(
        f"П1: "
        f"{pct(probabilities.get('home_win', 0))}"
    )

    text.append(
        f"X: "
        f"{pct(probabilities.get('draw', 0))}"
    )

    text.append(
        f"П2: "
        f"{pct(probabilities.get('away_win', 0))}"
    )

    text.append(
        f"1X: "
        f"{pct(probabilities.get('double_home', 0))}"
    )

    text.append(
        f"X2: "
        f"{pct(probabilities.get('double_away', 0))}"
    )

    # ========================================================
    # TOTALS
    # ========================================================

    text.append("")

    text.append(
        "⚽ <b>ТОТАЛ 2.5</b>"
    )

    text.append(
        f"ТБ 2.5: "
        f"{pct(probabilities.get('over_25', 0))}"
    )

    text.append(
        f"ТМ 2.5: "
        f"{pct(probabilities.get('under_25', 0))}"
    )

    # ========================================================
    # BTTS
    # ========================================================

    text.append("")

    text.append(
        "🥅 <b>ОБОЄ ЗАБ'ЮТЬ</b>"
    )

    text.append(
        f"ОЗ — Так: "
        f"{pct(probabilities.get('btts_yes', 0))}"
    )

    text.append(
        f"ОЗ — Ні: "
        f"{pct(probabilities.get('btts_no', 0))}"
    )

    # ========================================================
    # SCORE
    # ========================================================

    scores = probabilities.get(
        "most_likely_scores",
        []
    )

    if scores:

        best_score = scores[0]

        try:

            (hg, ag), score_probability = best_score

            text.append("")

            text.append(
                "🎯 <b>НАЙІМОВІРНІШИЙ РАХУНОК</b>"
            )

            text.append(
                f"<b>{hg}:{ag}</b> — "
                f"{pct(score_probability)}"
            )

        except Exception:

            pass

    # ========================================================
    # HOME / AWAY FORM
    # ========================================================

    home_home_form = model.get(
        "home_home_form",
        {}
    )

    away_away_form = model.get(
        "away_away_form",
        {}
    )

    if not isinstance(
        home_home_form,
        dict
    ):
        home_home_form = {}

    if not isinstance(
        away_away_form,
        dict
    ):
        away_away_form = {}

    text.append("")

    text.append(
        "🏠 <b>ФОРМА ВДОМА / В ГОСТЯХ</b>"
    )

    if home_home_form.get(
        "matches",
        0
    ):

        text.append(
            f"{home['name']}: "
            f"{home_home_form.get('wins', 0)}W "
            f"{home_home_form.get('draws', 0)}D "
            f"{home_home_form.get('losses', 0)}L "
            f"("
            f"{home_home_form.get('points_per_game', 0):.2f}"
            f" оч./матч)"
        )

    if away_away_form.get(
        "matches",
        0
    ):

        text.append(
            f"{away['name']}: "
            f"{away_away_form.get('wins', 0)}W "
            f"{away_away_form.get('draws', 0)}D "
            f"{away_away_form.get('losses', 0)}L "
            f"("
            f"{away_away_form.get('points_per_game', 0):.2f}"
            f" оч./матч)"
        )

    # ========================================================
    # ATTACK / DEFENCE
    # ========================================================

    text.append("")

    text.append(
        "⚔️ <b>АТАКА / ЗАХИСТ</b>"
    )

    text.append(
        f"{home['name']}: "
        f"{home_home_form.get('attack', 0):.2f} гол/матч | "
        f"{home_home_form.get('defence', 0):.2f} пропущено"
    )

    text.append(
        f"{away['name']}: "
        f"{away_away_form.get('attack', 0):.2f} гол/матч | "
        f"{away_away_form.get('defence', 0):.2f} пропущено"
    )

    # ========================================================
    # HALVES
    # ========================================================

    home_halves = model.get(
        "home_halves",
        {}
    )

    away_halves = model.get(
        "away_halves",
        {}
    )

    if not isinstance(
        home_halves,
        dict
    ):
        home_halves = {}

    if not isinstance(
        away_halves,
        dict
    ):
        away_halves = {}

    text.append("")

    text.append(
        "⏱ <b>ГОЛИ ПО ТАЙМАХ</b>"
    )

    if home_halves.get(
        "matches",
        0
    ):

        text.append(
            f"{home['name']}: "
            f"1-й тайм "
            f"{home_halves.get('first_half_goals', 0):.2f} "
            f"| 2-й "
            f"{home_halves.get('second_half_goals', 0):.2f}"
        )

    if away_halves.get(
        "matches",
        0
    ):

        text.append(
            f"{away['name']}: "
            f"1-й тайм "
            f"{away_halves.get('first_half_goals', 0):.2f} "
            f"| 2-й "
            f"{away_halves.get('second_half_goals', 0):.2f}"
        )

    # ========================================================
    # H2H
    # ========================================================

    h2h = model.get(
        "h2h",
        {}
    )

    if not isinstance(
        h2h,
        dict
    ):
        h2h = {}

    text.append("")

    text.append(
        "🤝 <b>ОСОБИСТІ ЗУСТРІЧІ</b>"
    )

    if h2h.get(
        "matches",
        0
    ):

        text.append(
            f"Матчів: "
            f"{h2h.get('matches', 0)}"
        )

        text.append(
            f"Середні голи: "
            f"{h2h.get('home_goals', 0):.2f} — "
            f"{h2h.get('away_goals', 0):.2f}"
        )

        text.append(
            f"ТБ 2.5: "
            f"{pct(h2h.get('over25', 0))}"
        )

        text.append(
            f"ОЗ: "
            f"{pct(h2h.get('btts', 0))}"
        )

    else:

        text.append(
            "Недостатньо даних H2H."
        )

    # ========================================================
    # REAL ODDS
    # ========================================================

    text.append("")

    text.append(
        "💰 <b>РЕАЛЬНІ КОЕФІЦІЄНТИ</b>"
    )

    if odds_event:

        home_odds = best_odds(
            real_odds.get(
                "home",
                []
            )
        )

        draw_odds = best_odds(
            real_odds.get(
                "draw",
                []
            )
        )

        away_odds = best_odds(
            real_odds.get(
                "away",
                []
            )
        )

        over_odds = best_odds(
            real_odds.get(
                "over25",
                []
            )
        )

        under_odds = best_odds(
            real_odds.get(
                "under25",
                []
            )
        )

        btts_yes_odds = best_odds(
            real_odds.get(
                "btts_yes",
                []
            )
        )

        btts_no_odds = best_odds(
            real_odds.get(
                "btts_no",
                []
            )
        )

        text.append(
            f"П1: "
            f"<b>{home_odds:.2f}</b>"
            if home_odds is not None
            else "П1: —"
        )

        text.append(
            f"X: "
            f"<b>{draw_odds:.2f}</b>"
            if draw_odds is not None
            else "X: —"
        )

        text.append(
            f"П2: "
            f"<b>{away_odds:.2f}</b>"
            if away_odds is not None
            else "П2: —"
        )

        text.append(
            f"ТБ 2.5: "
            f"<b>{over_odds:.2f}</b>"
            if over_odds is not None
            else "ТБ 2.5: —"
        )

        text.append(
            f"ТМ 2.5: "
            f"<b>{under_odds:.2f}</b>"
            if under_odds is not None
            else "ТМ 2.5: —"
        )

        text.append(
            f"ОЗ — Так: "
            f"<b>{btts_yes_odds:.2f}</b>"
            if btts_yes_odds is not None
            else "ОЗ — Так: —"
        )

        text.append(
            f"ОЗ — Ні: "
            f"<b>{btts_no_odds:.2f}</b>"
            if btts_no_odds is not None
            else "ОЗ — Ні: —"
        )

        text.append("")

        text.append(
            f"🏦 Букмекерів: "
            f"{result.get('bookmakers_count', 0)}"
        )

    else:

        text.append(
            "⚠️ Коефіцієнти не знайдені."
        )

        text.append(
            "Для вибору найкращої ставки потрібні реальні коефіцієнти."
        )

    # ========================================================
    # RECOMMENDATIONS
    # ========================================================

    most_likely = model.get("most_likely_bet")
    value_bets = model.get("value_bets", [])

    text.append("")
    text.append("🎯 <b>РЕКОМЕНДАЦІЇ БОТА</b>")

    def append_bet_block(title, item, icon="💎", show_value=True):
        if not item:
            text.append("")
            text.append(f"{icon} <b>{title}</b>")
            text.append("— немає доступної ставки")
            return

        text.append("")
        text.append(f"{icon} <b>{title}</b>")
        text.append(f"🏆 <b>{item.get('name', '—')}</b>")
        text.append(
            f"📈 Ймовірність: <b>{pct(item.get('probability', 0))}</b>"
        )

        odds = item.get("odds")
        if odds is not None:
            try:
                text.append(f"💰 Коефіцієнт: <b>{float(odds):.2f}</b>")
            except (TypeError, ValueError):
                pass

        if show_value:
            market_value = item.get("market_value")
            if market_value is not None:
                try:
                    text.append(
                        f"💎 Market Value: <b>{float(market_value) * 100:+.1f}%</b>"
                    )
                except (TypeError, ValueError):
                    pass

        confidence = item.get("confidence")
        if confidence is not None:
            try:
                text.append(f"🧠 Confidence: <b>{float(confidence):.1f}/100</b>")
            except (TypeError, ValueError):
                pass

        category = item.get("category")
        if category and category != "NO BET":
            category_icon = "🔥" if category == "STRONG BET" else "💎"
            text.append(f"{category_icon} {category}")

    append_bet_block(
        "НАЙВІРОГІДНІША СТАВКА",
        most_likely,
        icon="🛡",
        show_value=False,
    )

    if value_bets:
        append_bet_block("VALUE #1", value_bets[0], icon="💎", show_value=True)

        if len(value_bets) >= 2:
            append_bet_block("VALUE #2", value_bets[1], icon="💎", show_value=True)
        else:
            text.append("")
            text.append("💎 <b>VALUE #2</b>")
            text.append("— другої ставки з достатнім Value не знайдено")
    else:
        text.append("")
        text.append("💎 <b>VALUE #1 / VALUE #2</b>")
        text.append("— модель не знайшла достатньо позитивного Value")

    # Коротке пояснення, якщо найвірогідніша ставка не є Value.
    if most_likely:
        most_likely_market_value = safe_float(
            most_likely.get("market_value"), 0.0
        )
        if most_likely_market_value < MIN_VALUE:
            text.append("")
            text.append(
                "ℹ️ Найвірогідніша ставка не обов'язково має Value: "
                "висока ймовірність ≠ вигідний коефіцієнт."
            )

    # ========================================================
    # HISTORY
    # ========================================================

    text.append("")

    text.append(
        "📚 <b>ІСТОРІЯ</b>"
    )

    text.append(
        f"{home['name']}: "
        f"{result.get('home_history', 0)} матчів"
    )

    text.append(
        f"{away['name']}: "
        f"{result.get('away_history', 0)} матчів"
    )

    text.append("")

    text.append(
        "⚠️ Модельний прогноз, "
        "а не гарантія результату."
    )

    return "\n".join(text)


# ============================================================
# PARSE MATCH
# ============================================================

def parse_match(text):

    if not text:
        return None, None

    text = text.strip()

    separators = [
        " - ",
        " – ",
        " — ",
        "-",
        "–",
        "—",
    ]

    for separator in separators:

        if separator in text:

            parts = text.split(
                separator,
                1
            )

            if len(parts) == 2:

                home = parts[0].strip()

                away = parts[1].strip()

                if home and away:
                    return home, away

    return None, None


# ============================================================
# V54 CORNERS MODULE
# ============================================================

SOFASCORE_BASE_URL = "https://api.sofascore.com/api/v1"
SOFASCORE_CACHE = {}
SOFASCORE_SEMAPHORE = asyncio.Semaphore(5)


async def sofascore_get(path, params=None):
    key = (path, tuple(sorted((params or {}).items())))
    if key in SOFASCORE_CACHE:
        return SOFASCORE_CACHE[key]
    session = await get_sofascore_session()
    url = f"{SOFASCORE_BASE_URL}{path}"
    try:
        async with SOFASCORE_SEMAPHORE:
            async with session.get(url, params=params or {}, timeout=aiohttp.ClientTimeout(total=20)) as r:
                text = await r.text()
                if r.status != 200:
                    print(f"⚠️ SofaScore HTTP {r.status}: {url} | {text[:250]}")
                    return None
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    data = await r.json(content_type=None)
                SOFASCORE_CACHE[key] = data
                return data
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        print(f"⚠️ SofaScore connection error: {e}")
        return None
    except Exception as e:
        print(f"⚠️ SofaScore error: {e}")
        return None


SOFASCORE_KNOWN_TEAM_IDS = {
    # Teams already verified from our previous bot logs / SofaScore mapping.
    "borussia dortmund": 2673,
    "dortmund": 2673,
    "borussia dortmund fc": 2673,
    "villarreal": 2819,
    "villarreal cf": 2819,
    "juventus": 2687,
    "juventus fc": 2687,
    "ac milan": 2692,
}

async def sofascore_team_id(name):
    """Return SofaScore team id. Prefer known IDs to avoid the blocked search endpoint."""
    import re

    def norm(v):
        v = str(v or "").lower().strip()
        v = re.sub(r"\b(fc|cf|afc|ac|sc|fk|sk|club|calcio)\b", " ", v)
        v = re.sub(r"[^a-z0-9а-яіїєґ ]+", " ", v)
        return re.sub(r"\s+", " ", v).strip()

    target = norm(name)
    known = SOFASCORE_KNOWN_TEAM_IDS.get(target)
    if known:
        print(f"   🔎 SofaScore known ID: {name} → ID {known}")
        return known

    # Search is only a fallback. SofaScore currently blocks /search/all on some IPs.
    variants = [str(name).strip()]
    if target and target.lower() not in [x.lower() for x in variants]:
        variants.append(target)
    parts = target.split()
    if len(parts) > 1:
        variants.append(parts[-1])

    candidates = []
    for query in variants:
        data = await sofascore_get("/search/all", {"q": query})
        if not isinstance(data, dict):
            continue
        results = data.get("results") or []
        if not isinstance(results, list):
            continue
        for item in results:
            if not isinstance(item, dict):
                continue
            entity = item.get("entity") if isinstance(item.get("entity"), dict) else item
            typ = str(item.get("type") or entity.get("type") or "").lower()
            if typ and typ != "team":
                continue
            team_id = entity.get("id") or item.get("id")
            title = entity.get("name") or entity.get("shortName") or item.get("name") or item.get("shortName") or ""
            if not team_id or not title:
                continue
            score = SequenceMatcher(None, target, norm(title)).ratio()
            nt = norm(title)
            if nt == target:
                score += 1.0
            elif target and (target in nt or nt in target):
                score += 0.25
            candidates.append((score, team_id, title))

    if not candidates:
        print(f"   ⚠️ SofaScore search: '{name}' → результатів немає")
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    score, team_id, title = candidates[0]
    print(f"   🔎 SofaScore search: {name} → {title} | ID {team_id}")
    return team_id if score >= 0.45 else None


def _corner_value(stat):
    if not isinstance(stat, dict):
        return None
    name = str(stat.get("name", "")).strip().lower()
    if "corner" not in name:
        return None
    hv = stat.get("home")
    av = stat.get("away")
    def num(v):
        if isinstance(v, dict):
            v = v.get("value")
        try:
            return float(str(v).replace("%", ""))
        except Exception:
            return None
    h, a = num(hv), num(av)
    if h is None or a is None:
        return None
    return h, a


async def sofascore_event_corners(event_id):
    data = await sofascore_get(f"/event/{event_id}/statistics")
    if not isinstance(data, dict):
        return None
    stats = data.get("statistics", [])
    if not isinstance(stats, list):
        return None
    # SofaScore groups statistics by period; prefer ALL periods.
    periods = []
    for period in stats:
        if not isinstance(period, dict):
            continue
        if str(period.get("period", "")).upper() in ("ALL", "FULL", ""): 
            periods.append(period)
    periods = periods or stats
    for period in periods:
        groups = period.get("groups", [])
        for group in groups if isinstance(groups, list) else []:
            items = group.get("statisticsItems", []) if isinstance(group, dict) else []
            for item in items if isinstance(items, list) else []:
                val = _corner_value(item)
                if val is not None:
                    return val
    return None


async def sofascore_recent_corner_history(team_id, pages=3):
    events = []
    for page in range(pages):
        data = await sofascore_get(f"/team/{team_id}/events/last/{page}")
        if not isinstance(data, dict):
            continue
        page_events = data.get("events", [])
        if not isinstance(page_events, list):
            continue
        events.extend(page_events)
        if not data.get("hasNextPage", True) and page > 0:
            break
    seen = set()
    clean = []
    for ev in events:
        eid = ev.get("id") if isinstance(ev, dict) else None
        if not eid or eid in seen:
            continue
        seen.add(eid)
        status = ((ev.get("status") or {}).get("type") or "").lower()
        if status not in ("finished", "afterpenalties"):
            continue
        clean.append(ev)
    clean = clean[:30]
    results = []
    async def one(ev):
        corners = await sofascore_event_corners(ev.get("id"))
        if corners is None:
            return None
        return {
            "event_id": ev.get("id"),
            "home_id": (ev.get("homeTeam") or {}).get("id"),
            "away_id": (ev.get("awayTeam") or {}).get("id"),
            "home": corners[0],
            "away": corners[1],
        }
    vals = await asyncio.gather(*(one(ev) for ev in clean))
    return [x for x in vals if x is not None]


def _mean(vals):
    vals = [float(x) for x in vals if x is not None]
    return sum(vals) / len(vals) if vals else None


def _recent_mean(values, limit=10):
    values = [float(x) for x in values if x is not None]
    if not values:
        return None
    return sum(values[:limit]) / min(len(values), limit)


def corner_team_stats(rows, team_id):
    home_for, home_against, away_for, away_against, all_for, all_against = [], [], [], [], [], []
    for r in rows:
        if r["home_id"] == team_id:
            home_for.append(r["home"]); home_against.append(r["away"])
            all_for.append(r["home"]); all_against.append(r["away"])
        elif r["away_id"] == team_id:
            away_for.append(r["away"]); away_against.append(r["home"])
            all_for.append(r["away"]); all_against.append(r["home"])
    return {
        "home_for": _recent_mean(home_for), "home_against": _recent_mean(home_against),
        "away_for": _recent_mean(away_for), "away_against": _recent_mean(away_against),
        "all_for": _recent_mean(all_for), "all_against": _recent_mean(all_against),
        "home_n": len(home_for), "away_n": len(away_for), "all_n": len(all_for),
    }


def poisson_over_under(mu, line):
    # Asian-style .5 lines: P(O line) = P(X >= floor(line)+1)
    k = math.floor(float(line)) + 1
    p_under = 0.0
    term = math.exp(-mu)
    for i in range(k):
        if i > 0:
            term *= mu / i
        p_under += term
    p_over = max(0.0, min(1.0, 1.0 - p_under))
    return p_over, p_under


def _corner_outcomes(event, market_keys):
    out = []
    for book in (event or {}).get("bookmakers", []):
        for market in book.get("markets", []):
            if market.get("key") not in market_keys:
                continue
            for o in market.get("outcomes", []):
                try:
                    point = float(o.get("point"))
                    price = float(o.get("price"))
                except Exception:
                    continue
                out.append({"bookmaker": book.get("title") or book.get("key"), "key": market.get("key"), "name": o.get("name", ""), "description": o.get("description", ""), "point": point, "price": price})
    return out


def _best_price_by_line(outcomes):
    best = {}
    for o in outcomes:
        # Team-total outcomes need description in the key; totals do not.
        key = (o["key"], o.get("description", "").lower(), o["point"], o["name"].lower())
        if key not in best or o["price"] > best[key]["price"]:
            best[key] = o
    return list(best.values())


def _corner_std(values):
    vals = [safe_float(x, None) for x in values]
    vals = [x for x in vals if x is not None]
    if len(vals) < 2:
        return 0.0
    mean = sum(vals) / len(vals)
    return math.sqrt(sum((x - mean) ** 2 for x in vals) / (len(vals) - 1))


def _corner_tail_probability(mu, line, variance=None, over=True):
    """Estimate O/U probability with over-dispersion when the sample variance
    is materially above the Poisson mean. Otherwise use the standard Poisson.
    """
    mu = max(0.05, safe_float(mu, 0.0))
    line = safe_float(line, 0.5)
    variance = safe_float(variance, mu)
    k = max(0, math.floor(line) + 1)

    # Poisson baseline.
    if variance <= mu + 0.05:
        p_over, p_under = poisson_over_under(mu, line)
        return p_over if over else p_under

    # Negative-binomial approximation for over-dispersed corner counts.
    # Var = mu + mu^2 / r  =>  r = mu^2 / (Var - mu)
    r = (mu * mu) / max(variance - mu, 0.05)
    r = max(0.5, min(1000.0, r))
    prob_success = r / (r + mu)
    prob_failure = mu / (r + mu)

    term = prob_success ** r
    p_under = 0.0
    for i in range(k):
        if i > 0:
            term *= ((i - 1 + r) / i) * prob_failure
        p_under += term
        if term < 1e-14 and i > mu + 20:
            break

    p_under = max(0.0, min(1.0, p_under))
    p_over = 1.0 - p_under
    return p_over if over else p_under


def _corner_market_confidence(probability, value, sample_n, std_dev, market_count=0, stability=1.0, consistency=1.0):
    """Confidence is deliberately conservative: probability is not confidence.

    Small samples and volatile corner counts pull confidence toward 50. A good
    price/value can add a small bonus, but cannot create an unrealistic 90%+
    confidence on five matches.
    """
    p = max(0.0, min(1.0, safe_float(probability, 0.5)))
    value = safe_float(value, 0.0)
    n = max(0, int(sample_n or 0))
    sd = max(0.0, safe_float(std_dev, 0.0))

    sample_factor = min(1.0, n / 8.0)
    # 1.0 at zero dispersion, gradually falling as volatility rises.
    stability_factor = 1.0 / (1.0 + sd / 4.0)
    reliability = 0.55 + 0.45 * sample_factor
    reliability *= 0.70 + 0.20 * stability_factor + 0.10 * stability
    reliability *= 0.85 + 0.15 * consistency

    edge_strength = abs(p - 0.5)
    confidence = 50.0 + edge_strength * 80.0 * reliability
    confidence += min(5.0, max(0.0, value * 20.0))
    if market_count >= 5:
        confidence += 1.0

    return max(50.0, min(85.0, confidence))


def _corner_candidate(label, mu, outcome, variance=None, sample_n=0, market_count=0, stability=1.0, consistency=1.0):
    name = str(outcome.get("name", "")).lower()
    if "over" in name:
        p = _corner_tail_probability(mu, outcome["point"], variance, over=True)
    elif "under" in name:
        p = _corner_tail_probability(mu, outcome["point"], variance, over=False)
    else:
        return None

    fair = 1.0 / p if p > 0 else 999.0
    value = calculate_value(p, outcome["price"]) if "calculate_value" in globals() else (p * outcome["price"] - 1.0)
    confidence = _corner_market_confidence(
        p, value, sample_n, math.sqrt(max(0.0, safe_float(variance, mu))), market_count, stability, consistency
    )
    return {
        "label": label,
        "selection": outcome["name"],
        "line": outcome["point"],
        "probability": p,
        "fair_odds": fair,
        "odds": outcome["price"],
        "value": value,
        "confidence": confidence,
        "bookmaker": outcome.get("bookmaker"),
        "market": outcome.get("key"),
        "description": outcome.get("description", ""),
        "stability": max(0.0, min(1.0, safe_float(stability, 1.0))),
        "consistency": max(0.0, min(1.0, safe_float(consistency, 1.0))),
    }


async def fotmob_recent_corner_history(team_name, limit=10):
    """Load corner history independently from xG.

    Important: some FotMob matches do not expose usable xG. Corner statistics
    are still available in matchDetails, so corners must NOT depend on the xG
    parser succeeding first.
    """
    before_date = datetime.now(timezone.utc)
    records = []
    timeout = aiohttp.ClientTimeout(total=40)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        team_id = await fotmob_find_team_id(session, team_name)
        if not team_id:
            print(f"   ⚠️ FotMob: team not found for corners: {team_name}")
            return []

        try:
            team_data = await fotmob_get_team_data(session, team_id)
        except Exception as e:
            print(f"   ⚠️ FotMob team data for corners {team_name}: {e}")
            return []

        raw_matches = []
        _fotmob_walk_match_candidates(team_data, raw_matches)
        unique = {}
        for row in raw_matches:
            info = _fotmob_extract_match_info(row)
            if not info.get("id") or not info.get("date"):
                continue
            if info["date"] >= before_date:
                continue
            if not info.get("finished"):
                continue
            if not (names_match(team_name, info.get("home", "")) or
                    names_match(team_name, info.get("away", ""))):
                continue
            unique[str(info["id"])] = info

        candidates = list(unique.values())
        candidates.sort(key=lambda x: x["date"], reverse=True)

        # The team endpoint can contain only a short completed window.
        if len(candidates) < max(limit, 10):
            league_ids = [x.get("league_id") for x in unique.values()]
            league_ids = [x for x in league_ids if x not in (None, "", 0)]
            if league_ids:
                try:
                    historical = await _fotmob_load_historical_team_matches(
                        session, team_name, before_date, league_ids
                    )
                    merged = {str(x["id"]): x for x in candidates if x.get("id")}
                    for x in historical:
                        if x.get("id"):
                            merged[str(x["id"])] = x
                    candidates = list(merged.values())
                    candidates.sort(key=lambda x: x["date"], reverse=True)
                except Exception as e:
                    print(f"   ⚠️ FotMob historical corners {team_name}: {e}")

        # Ask for more matches than needed because some matchDetails may not
        # contain a Corners row.
        candidates = candidates[:max(limit * 2, 20)]
        print(f"   🔎 FotMob corner candidates for {team_name}: {len(candidates)}")

        for info in candidates:
            match_id = str(info["id"])
            corners = FOTMOB_MATCH_CORNERS_CACHE.get(match_id)

            if corners is None:
                disk_match = _load_fotmob_match_disk(match_id)
                if disk_match is not None:
                    FOTMOB_MATCH_CACHE[match_id] = disk_match.get("xg")
                    corners = disk_match.get("corners")
                    FOTMOB_MATCH_CORNERS_CACHE[match_id] = corners

            if corners is None:
                try:
                    data = await _fotmob_get_match_details_resilient(session, info)
                    if data is not None:
                        corners = parse_fotmob_corners(data)
                    else:
                        corners = None
                    FOTMOB_MATCH_CORNERS_CACHE[match_id] = corners
                    _save_fotmob_match_disk(
                        match_id,
                        FOTMOB_MATCH_CACHE.get(match_id),
                        corners,
                    )
                except Exception as e:
                    print(
                        f"      ⚠️ FotMob corners {info.get('home')} - "
                        f"{info.get('away')}: {e}"
                    )
                    continue

            if corners is None:
                continue

            is_home = names_match(team_name, info.get("home", ""))
            records.append({
                "event_id": info["id"],
                "home_id": "home" if is_home else "opponent",
                "away_id": "opponent" if is_home else "away",
                "home": float(corners[0]),
                "away": float(corners[1]),
                "venue": "home" if is_home else "away",
                "date": info.get("date"),
            })

            if len(records) >= limit:
                break

    return records


def _corner_stats_from_rows(rows, venue):
    selected = [r for r in rows if r.get("venue") == venue]
    venue_for = []
    venue_against = []
    all_for = []
    all_against = []
    total_corners = []

    for r in rows:
        if r.get("venue") == "home":
            own, opp = float(r["home"]), float(r["away"])
        else:
            own, opp = float(r["away"]), float(r["home"])
        all_for.append(own)
        all_against.append(opp)
        total_corners.append(own + opp)

    for r in selected:
        if venue == "home":
            venue_for.append(float(r["home"]))
            venue_against.append(float(r["away"]))
        else:
            venue_for.append(float(r["away"]))
            venue_against.append(float(r["home"]))

    return {
        "venue_for": _recent_mean(venue_for, 10),
        "venue_against": _recent_mean(venue_against, 10),
        "all_for": _recent_mean(all_for, 10),
        "all_against": _recent_mean(all_against, 10),
        "venue_n": len(selected),
        "all_n": len(rows),
        "venue_for_sd": _corner_std(venue_for),
        "venue_against_sd": _corner_std(venue_against),
        "all_for_sd": _corner_std(all_for),
        "all_against_sd": _corner_std(all_against),
        "total_sd": _corner_std(total_corners),
    }


def _corner_quality(values):
    vals = [safe_float(x, None) for x in values]
    vals = [x for x in vals if x is not None]
    if len(vals) < 4:
        return 0.55, 0.65
    mean = sum(vals) / len(vals)
    sd = _corner_std(vals)
    stability = 1.0 / (1.0 + sd / max(mean, 1.0))
    half = max(2, len(vals) // 2)
    recent = sum(vals[:half]) / half
    older = sum(vals[half:]) / max(1, len(vals) - half)
    consistency = 1.0 / (1.0 + abs(recent - older) / max(mean, 1.0))
    return max(0.0, min(1.0, stability)), max(0.0, min(1.0, consistency))

def _corner_grade(c):
    v = safe_float(c.get("value"), 0.0)
    conf = safe_float(c.get("confidence"), 0.0)
    p = safe_float(c.get("probability"), 0.0)
    stability = safe_float(c.get("stability"), 0.0)
    if v >= 0.08 and conf >= 65 and p >= 0.55 and stability >= 0.55:
        return "🔥 СИЛЬНА СТАВКА"
    if v >= 0.03 and conf >= 55 and stability >= 0.45:
        return "🟢 VALUE"
    if v >= 0.0 and conf >= 50:
        return "🟡 ПОГРАНИЧНО"
    return "🔴 NO BET"

def _format_corner_line(c):
    return (
        f"   {'⭐ ' if c['value'] >= MIN_VALUE and c['confidence'] >= MIN_CONFIDENCE else '   ' }"
        f"{c['label']}: {c['selection']} {c['line']:.1f} @ {c['odds']:.2f} "
        f"| P {c['probability']*100:.1f}% | Fair {c['fair_odds']:.2f} "
        f"| Value {c['value']*100:+.1f}% | Conf {c['confidence']:.1f}% "
        f"| Stability {c.get('stability',0)*100:.0f}% | {_corner_grade(c)} | {c['bookmaker']}"
    )


async def calculate_corner_analysis(home_team, away_team, odds_event):
    print("\n🟩 CORNERS V59 PRO → FotMob + real Odds API + stability model")

    home_rows, away_rows = await asyncio.gather(
        fotmob_recent_corner_history(home_team["name"], limit=10),
        fotmob_recent_corner_history(away_team["name"], limit=10),
    )

    hs = _corner_stats_from_rows(home_rows, "home")
    aws = _corner_stats_from_rows(away_rows, "away")

    def _fmt_num(value, digits=2):
        value = safe_float(value, None)
        return f"{value:.{digits}f}" if value is not None else "None"

    print(
        f"   {home_team['name']}: home corners for={_fmt_num(hs['venue_for'])} "
        f"against={_fmt_num(hs['venue_against'])} | home_n={hs['venue_n']} | all_n={hs['all_n']} "
        f"| SD for={_fmt_num(hs['venue_for_sd'])}"
    )
    print(
        f"   {away_team['name']}: away corners for={_fmt_num(aws['venue_for'])} "
        f"against={_fmt_num(aws['venue_against'])} | away_n={aws['venue_n']} | all_n={aws['all_n']} "
        f"| SD for={_fmt_num(aws['venue_for_sd'])}"
    )

    if hs["venue_for"] is None or aws["venue_for"] is None:
        print("⚠️ FotMob: недостаточно данных по угловым")
        return {
            "home_expected": 0.0,
            "away_expected": 0.0,
            "total_expected": 0.0,
            "candidates": [],
            "all_lines": [],
            "rows_home": hs,
            "rows_away": aws,
        }

    home_for = hs["venue_for"]
    home_against = hs["venue_against"] if hs["venue_against"] is not None else hs["all_against"]
    away_for = aws["venue_for"]
    away_against = aws["venue_against"] if aws["venue_against"] is not None else aws["all_against"]

    # More stable than V57: pair attack with opponent allowance, then shrink
    # toward each team's 10-match baseline. This avoids double-counting four
    # highly correlated averages.
    home_pair = (home_for + away_against) / 2.0
    away_pair = (away_for + home_against) / 2.0

    eh = home_pair * 0.75 + (hs["all_for"] or home_pair) * 0.25
    ea = away_pair * 0.75 + (aws["all_for"] or away_pair) * 0.25

    # Mild venue correction only when venue samples are genuinely small.
    if hs["venue_n"] < 5 and hs["all_for"] is not None:
        eh = eh * 0.85 + hs["all_for"] * 0.15
    if aws["venue_n"] < 5 and aws["all_for"] is not None:
        ea = ea * 0.85 + aws["all_for"] * 0.15

    eh = max(1.0, min(10.0, eh))
    ea = max(1.0, min(10.0, ea))
    et = eh + ea

    print(
        f"   Expected corners: {home_team['name']} {eh:.2f} | "
        f"{away_team['name']} {ea:.2f} | TOTAL {et:.2f}"
    )

    outcomes = _best_price_by_line(_corner_outcomes(odds_event, {
        "alternate_totals_corners", "alternate_team_totals_corners"
    }))
    if not outcomes:
        print("⚠️ Реальные corner odds не найдены")
        return {
            "home_expected": eh, "away_expected": ea, "total_expected": et,
            "candidates": [], "rows_home": hs, "rows_away": aws,
        }

    hn = normalize_name(home_team["name"])
    an = normalize_name(away_team["name"])

    total_market_count = sum(1 for x in outcomes if x["key"] == "alternate_totals_corners")
    home_market_count = sum(
        1 for x in outcomes
        if x["key"] == "alternate_team_totals_corners"
        and normalize_name(x.get("description", ""))
        and (SequenceMatcher(None, normalize_name(x.get("description", "")), hn).ratio() >= .45
             or hn in normalize_name(x.get("description", ""))
             or normalize_name(x.get("description", "")) in hn)
    )
    away_market_count = sum(
        1 for x in outcomes
        if x["key"] == "alternate_team_totals_corners"
        and normalize_name(x.get("description", ""))
        and (SequenceMatcher(None, normalize_name(x.get("description", "")), an).ratio() >= .45
             or an in normalize_name(x.get("description", ""))
             or normalize_name(x.get("description", "")) in an)
    )

    # Stability/consistency are independent quality controls. High SD or a
    # strong shift between the first and second half of the sample reduces confidence.
    home_for_stab, home_cons = _corner_quality([r["home"] for r in home_rows if r.get("venue") == "home"])
    away_for_stab, away_cons = _corner_quality([r["away"] for r in away_rows if r.get("venue") == "away"])
    home_against_stab, home_against_cons = _corner_quality([r["away"] for r in home_rows if r.get("venue") == "home"])
    away_against_stab, away_against_cons = _corner_quality([r["home"] for r in away_rows if r.get("venue") == "away"])
    home_quality = (home_for_stab + away_against_stab) / 2.0
    away_quality = (away_for_stab + home_against_stab) / 2.0
    home_consistency = (home_cons + away_against_cons) / 2.0
    away_consistency = (away_cons + home_against_cons) / 2.0
    total_stability = (home_quality + away_quality) / 2.0
    total_consistency = (home_consistency + away_consistency) / 2.0

    print(f"   Quality: home={home_quality*100:.0f}% | away={away_quality*100:.0f}% | total={total_stability*100:.0f}% | consistency={total_consistency*100:.0f}%")

    total_variance = max(et, hs["total_sd"] ** 2 if hs["total_sd"] else 0.0, aws["total_sd"] ** 2 if aws["total_sd"] else 0.0)
    # Team-count variance: average the relevant attack/allowance dispersions.
    home_variance = max(
        eh,
        ((hs["venue_for_sd"] ** 2) + (aws["venue_against_sd"] ** 2)) / 2.0
        if (hs["venue_for_sd"] or aws["venue_against_sd"]) else eh,
    )
    away_variance = max(
        ea,
        ((aws["venue_for_sd"] ** 2) + (hs["venue_against_sd"] ** 2)) / 2.0
        if (aws["venue_for_sd"] or hs["venue_against_sd"]) else ea,
    )

    all_lines = []
    candidates = []
    for o in outcomes:
        if o["key"] == "alternate_totals_corners":
            c = _corner_candidate(
                "Загальні кути", et, o,
                variance=total_variance,
                sample_n=min(hs["all_n"], aws["all_n"]),
                market_count=total_market_count,
                stability=total_stability, consistency=total_consistency,
            )
        else:
            desc = normalize_name(o.get("description", ""))
            if desc and (SequenceMatcher(None, desc, hn).ratio() >= .45 or hn in desc or desc in hn):
                c = _corner_candidate(
                    f"{home_team['name']} кути", eh, o,
                    variance=home_variance,
                    sample_n=hs["venue_n"],
                    market_count=home_market_count,
                    stability=home_quality, consistency=home_consistency,
                )
            elif desc and (SequenceMatcher(None, desc, an).ratio() >= .45 or an in desc or desc in an):
                c = _corner_candidate(
                    f"{away_team['name']} кути", ea, o,
                    variance=away_variance,
                    sample_n=aws["venue_n"],
                    market_count=away_market_count,
                    stability=away_quality, consistency=away_consistency,
                )
            else:
                c = None
        if not c:
            continue
        c["grade"] = _corner_grade(c)
        all_lines.append(c)
        if c["value"] >= MIN_VALUE and c["confidence"] >= MIN_CONFIDENCE and c["stability"] >= 0.45:
            candidates.append(c)

    # Display every real line returned by the bookmaker feed. This is useful
    # for manual selection and makes it obvious when the model rejects a line.
    all_lines.sort(key=lambda x: (x["label"], x["line"], x["selection"]))
    print(f"\n   📊 CORNER LINES ({len(all_lines)} real lines, best available price):")
    for c in all_lines:
        print(_format_corner_line(c))

    candidates.sort(key=lambda x: (x["value"] * 0.45 + (x["confidence"] / 100.0) * 0.30 + x.get("stability", 0.0) * 0.15 + x.get("consistency", 0.0) * 0.10), reverse=True)
    if candidates:
        b = candidates[0]
        print(
            f"\n   🏆 BEST CORNER BET: {b['label']} {b['selection']} {b['line']:.1f} "
            f"@ {b['odds']:.2f} | Value {b['value']*100:+.1f}% | Conf {b['confidence']:.1f}%"
        )
    else:
        print("\n   ⚠️ Немає corner bet з достатнім Value/Confidence")

    return {
        "home_expected": eh,
        "away_expected": ea,
        "total_expected": et,
        "candidates": candidates,
        "all_lines": all_lines,
        "rows_home": hs,
        "rows_away": aws,
    }



# ============================================================
# YELLOW CARDS V1 — LAST 30 MATCHES + REFEREE
# ============================================================

FOTMOB_MATCH_YELLOW_CACHE = {}
CARDS_MATCH_LIMIT = 30


def parse_fotmob_yellow_cards(data):
    """Extract full-match home/away yellow-card counts from FotMob matchDetails."""
    if not isinstance(data, dict):
        return None

    pairs = []

    def add_pair(values):
        if not isinstance(values, (list, tuple)) or len(values) < 2:
            return
        h = safe_float(values[0], None)
        a = safe_float(values[1], None)
        if h is None or a is None or h < 0 or a < 0 or h > 20 or a > 20:
            return
        pairs.append((float(h), float(a)))

    def is_yellow_label(value):
        label = str(value or "").strip().lower()
        compact = re.sub(r"[^a-zа-я0-9]+", "", label)
        return (
            "yellowcard" in compact
            or "yellowcards" in compact
            or "желтыекарточ" in compact
            or "жёлтыекарточ" in compact
        )

    content = data.get("content")
    if isinstance(content, dict):
        stats = content.get("stats")
        if isinstance(stats, dict):
            periods = stats.get("Periods") or stats.get("periods") or {}
            if isinstance(periods, dict):
                all_period = periods.get("All") or periods.get("ALL") or periods.get("all")
                if isinstance(all_period, dict):
                    for row in all_period.get("stats") or []:
                        if isinstance(row, dict) and is_yellow_label(
                            row.get("title") or row.get("name") or row.get("key") or row.get("stat")
                        ):
                            add_pair(row.get("stats"))

    def walk(obj, depth=0):
        if depth > 10 or obj is None:
            return
        if isinstance(obj, dict):
            if is_yellow_label(
                obj.get("title") or obj.get("name") or obj.get("key") or obj.get("stat")
            ):
                add_pair(obj.get("stats"))
            for value in obj.values():
                walk(value, depth + 1)
        elif isinstance(obj, list):
            for value in obj:
                walk(value, depth + 1)

    walk(data)

    seen = set()
    for item in pairs:
        key = (round(item[0], 6), round(item[1], 6))
        if key not in seen:
            seen.add(key)
            return item
    return None


async def fotmob_recent_yellow_history(team_name, limit=CARDS_MATCH_LIMIT):
    """Last N completed matches where FotMob exposes yellow-card statistics."""
    before_date = datetime.now(timezone.utc)
    timeout = aiohttp.ClientTimeout(total=45)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        team_id = await fotmob_find_team_id(session, team_name)
        if not team_id:
            print(f"   ⚠️ FotMob: team not found for cards: {team_name}")
            return []

        try:
            team_data = await fotmob_get_team_data(session, team_id)
        except Exception as exc:
            print(f"   ⚠️ FotMob team data for cards {team_name}: {exc}")
            return []

        raw_matches = []
        _fotmob_walk_match_candidates(team_data, raw_matches)
        unique = {}
        league_ids = []

        for row in raw_matches:
            info = _fotmob_extract_match_info(row)
            if not info.get("id") or not info.get("date"):
                continue
            if info["date"] >= before_date or not info.get("finished"):
                continue
            if not (
                names_match(team_name, info.get("home", ""))
                or names_match(team_name, info.get("away", ""))
            ):
                continue
            unique[str(info["id"])] = info
            lid = info.get("league_id")
            if lid not in (None, "", 0):
                league_ids.append(lid)

        candidates = list(unique.values())
        candidates.sort(key=lambda x: x["date"], reverse=True)

        if len(candidates) < limit and league_ids:
            try:
                historical = await _fotmob_load_historical_team_matches(
                    session,
                    team_name,
                    before_date,
                    list(dict.fromkeys(league_ids)),
                )
                merged = {str(x["id"]): x for x in candidates if x.get("id")}
                for row in historical:
                    if row.get("id"):
                        merged[str(row["id"])] = row
                candidates = list(merged.values())
                candidates.sort(key=lambda x: x["date"], reverse=True)
            except Exception as exc:
                print(f"   ⚠️ FotMob historical cards {team_name}: {exc}")

        candidates = candidates[:max(limit + 12, 42)]
        print(f"   🟨 FotMob card candidates for {team_name}: {len(candidates)}")
        semaphore = asyncio.Semaphore(6)

        async def load_one(info):
            match_id = str(info["id"])
            disk_match = None

            if match_id in FOTMOB_MATCH_YELLOW_CACHE:
                yellows = FOTMOB_MATCH_YELLOW_CACHE[match_id]
            else:
                disk_match = _load_fotmob_match_disk(match_id)
                yellows = disk_match.get("yellow_cards") if disk_match else None

                if yellows is None:
                    async with semaphore:
                        try:
                            details = await _fotmob_get_match_details_resilient(session, info)
                        except Exception:
                            details = None
                    yellows = parse_fotmob_yellow_cards(details) if details else None

                    _save_fotmob_match_disk(
                        match_id,
                        disk_match.get("xg") if disk_match else FOTMOB_MATCH_CACHE.get(match_id),
                        disk_match.get("corners") if disk_match else FOTMOB_MATCH_CORNERS_CACHE.get(match_id),
                        yellow_cards=yellows,
                    )

                FOTMOB_MATCH_YELLOW_CACHE[match_id] = yellows

            if yellows is None:
                return None

            is_home = names_match(team_name, info.get("home", ""))
            own = float(yellows[0] if is_home else yellows[1])
            opp = float(yellows[1] if is_home else yellows[0])
            return {
                "event_id": info.get("id"),
                "date": info.get("date"),
                "own": own,
                "opponent": opp,
                "total": own + opp,
            }

        rows = []
        for pos in range(0, len(candidates), 8):
            vals = await asyncio.gather(*(load_one(info) for info in candidates[pos:pos + 8]))
            rows.extend(x for x in vals if x is not None)
            if len(rows) >= limit:
                break

        rows.sort(
            key=lambda x: x.get("date") or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return rows[:limit]


def _cards_team_summary(rows):
    own = [safe_float(row.get("own"), None) for row in rows]
    own = [value for value in own if value is not None]

    def avg(values):
        return round(sum(values) / len(values), 3) if values else None

    return {
        "average": avg(own),
        "sample": len(own),
        "last5": avg(own[:5]),
        "last10": avg(own[:10]),
    }


async def _sofascore_find_match_event(home_name, away_name, kickoff_utc=None):
    kickoff = parse_datetime_utc(kickoff_utc) if kickoff_utc else None
    base_date = (kickoff or datetime.now(timezone.utc)).date()
    dates = [base_date]
    if kickoff:
        dates += [base_date - timedelta(days=1), base_date + timedelta(days=1)]

    best = None

    for match_date in dates:
        data = await sofascore_get(f"/sport/football/scheduled-events/{match_date.isoformat()}")
        if not isinstance(data, dict):
            continue

        events = data.get("events") or []
        for event in events if isinstance(events, list) else []:
            if not isinstance(event, dict):
                continue

            event_home = str((event.get("homeTeam") or {}).get("name") or "")
            event_away = str((event.get("awayTeam") or {}).get("name") or "")
            if not event_home or not event_away:
                continue

            direct = names_match(home_name, event_home) and names_match(away_name, event_away)
            name_score = (
                SequenceMatcher(None, normalize_name(home_name), normalize_name(event_home)).ratio()
                + SequenceMatcher(None, normalize_name(away_name), normalize_name(event_away)).ratio()
            ) / 2.0

            if not direct and name_score < 0.66:
                continue

            time_bonus = 0.0
            if kickoff and event.get("startTimestamp"):
                try:
                    event_time = datetime.fromtimestamp(int(event["startTimestamp"]), tz=timezone.utc)
                    diff_hours = abs((event_time - kickoff).total_seconds()) / 3600.0
                    if diff_hours <= 2:
                        time_bonus = 0.35
                    elif diff_hours <= 8:
                        time_bonus = 0.12
                    elif diff_hours > 24:
                        continue
                except Exception:
                    pass

            score = name_score + time_bonus + (0.4 if direct else 0.0)
            if best is None or score > best[0]:
                best = (score, event)

    if not best:
        return None

    event = best[1]
    event_id = event.get("id")
    if event_id:
        detail = await sofascore_get(f"/event/{event_id}")
        if isinstance(detail, dict) and isinstance(detail.get("event"), dict):
            return detail["event"]
    return event


async def _rfef_referee_assignment(home_name, away_name, kickoff_utc=None):
    """
    Official-source lookup for Spanish Primera División.
    RFEF publishes referee appointments in news articles. We search the
    current Designaciones feed and recent pages, then inspect matching articles.
    """
    kickoff = parse_datetime_utc(kickoff_utc) if kickoff_utc else None
    target_date = (kickoff or datetime.now(timezone.utc)).date()

    urls = [
        "https://rfef.es/es/noticias/arbitros/designaciones",
        "https://rfef.es/es/noticias/competiciones-masculinas/primera-division",
    ]
    for page in range(1, 4):
        urls.append(f"https://rfef.es/es/noticias/arbitros/designaciones?page={page}")

    timeout = aiohttp.ClientTimeout(total=18)
    headers = {
        "User-Agent": "Mozilla/5.0 Footballistika/3.2.2",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.7",
    }

    def clean_html(raw):
        raw = re.sub(r"<script\b[^>]*>.*?</script>", " ", raw, flags=re.I | re.S)
        raw = re.sub(r"<style\b[^>]*>.*?</style>", " ", raw, flags=re.I | re.S)
        raw = re.sub(r"<[^>]+>", " ", raw)
        raw = raw.replace("&nbsp;", " ").replace("&amp;", "&")
        return re.sub(r"\s+", " ", raw).strip()

    def norm(s):
        return normalize_name(str(s or "")).replace(" cf", "").replace(" fc", "")

    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        article_urls = []
        for url in urls:
            try:
                async with session.get(url, ssl=False) as resp:
                    if resp.status != 200:
                        continue
                    html = await resp.text(errors="ignore")
            except Exception:
                continue

            for href in re.findall(r'href=["\']([^"\']+)["\']', html, flags=re.I):
                if "/es/noticias/designaciones-" not in href:
                    continue
                if href.startswith("/"):
                    href = "https://rfef.es" + href
                if href not in article_urls:
                    article_urls.append(href)

        home_n, away_n = norm(home_name), norm(away_name)

        # Prefer recent appointment articles; stop after a modest number.
        for url in article_urls[:35]:
            try:
                async with session.get(url, ssl=False) as resp:
                    if resp.status != 200:
                        continue
                    html = await resp.text(errors="ignore")
            except Exception:
                continue

            plain = clean_html(html)
            plain_n = norm(plain)

            if home_n not in plain_n or away_n not in plain_n:
                continue

            # Avoid accepting an old article for teams that meet again.
            date_tokens = [
                target_date.strftime("%d/%m/%Y"),
                target_date.strftime("%d-%m-%Y"),
                str(target_date.day),
            ]
            if kickoff and not any(tok in plain for tok in date_tokens):
                # Article title/date can be one day before the fixture, so this
                # is only a weak guard. Team-pair match remains primary.
                pass

            # RFEF appointment cards/images expose role labels in alt/title/text
            # inconsistently. Try common Spanish labels around the referee name.
            patterns = [
                r"(?:ÁRBITRO|ARBITRO|Árbitro|Arbitro)\s*(?:PRINCIPAL)?\s*[:\-–]?\s*([A-ZÁÉÍÓÚÜÑ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ' -]{5,70})",
                r"(?:Colegiado|COLEGIADO)\s*[:\-–]?\s*([A-ZÁÉÍÓÚÜÑ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ' -]{5,70})",
            ]
            for pattern in patterns:
                match = re.search(pattern, plain)
                if match:
                    name = re.split(
                        r"\s+(?:VAR|AVAR|ASISTENTE|CUARTO|4º|CUARTO ÁRBITRO)\b",
                        match.group(1).strip(),
                        maxsplit=1,
                        flags=re.I,
                    )[0].strip(" -–:")
                    if 5 <= len(name) <= 70:
                        return {
                            "name": name,
                            "source": "RFEF",
                            "source_url": url,
                            "official": True,
                        }

        return None


async def _sofascore_referee_profile_by_name(referee_name):
    """Resolve referee profile/statistics after the assignment name is known."""
    if not referee_name:
        return None

    # SofaScore search endpoint is useful even when the future event itself
    # has not yet been populated with referee metadata.
    queries = [referee_name]
    normalized = referee_name.replace("Jesús", "Jesus").replace("José", "Jose")
    if normalized not in queries:
        queries.append(normalized)

    for query in queries:
        try:
            data = await sofascore_get(f"/search/all?q={quote(query)}")
        except Exception:
            data = None

        results = []
        if isinstance(data, dict):
            results = data.get("results") or data.get("entities") or []

        for item in results if isinstance(results, list) else []:
            entity = item.get("entity") if isinstance(item, dict) else None
            entity = entity if isinstance(entity, dict) else (item if isinstance(item, dict) else {})
            entity_type = str(
                item.get("type") if isinstance(item, dict) else entity.get("type", "")
            ).lower()
            name = str(entity.get("name") or "")
            if "referee" not in entity_type and not entity.get("id"):
                continue
            if SequenceMatcher(None, normalize_name(referee_name), normalize_name(name)).ratio() < 0.72:
                continue

            referee_id = entity.get("id")
            if not referee_id:
                continue

            profile = await sofascore_get(f"/referee/{referee_id}")
            profile = profile if isinstance(profile, dict) else {}
            profile_ref = profile.get("referee") or entity
            stats = profile.get("statistics") or {}

            matches = int(safe_float(stats.get("matchesTotal"), 0) or 0)
            yellow_total = safe_float(stats.get("yellowCardsTotal"), 0.0) or 0.0
            red_total = safe_float(stats.get("redCardsTotal"), 0.0) or 0.0
            yellow_red_total = safe_float(stats.get("yellowRedCardsTotal"), 0.0) or 0.0

            return {
                "available": matches > 0,
                "assigned": True,
                "id": referee_id,
                "name": profile_ref.get("name") or name or referee_name,
                "matches": matches,
                "yellow_total": round(yellow_total, 1),
                "yellow_average": round(yellow_total / matches, 3) if matches else None,
                "red_average": round((red_total + yellow_red_total) / matches, 3) if matches else None,
            }

    return None


async def _sofascore_referee_stats(home_name, away_name, kickoff_utc=None):
    """
    Multi-source assignment:
      1) RFEF official appointment for Spanish Primera
      2) SofaScore event metadata fallback
    Statistics are resolved separately so a missing referee field on the
    future SofaScore event no longer means 'not appointed'.
    """
    official = None
    try:
        official = await _rfef_referee_assignment(home_name, away_name, kickoff_utc)
    except Exception as exc:
        print(f"   ⚠️ RFEF referee lookup: {exc}")

    if official and official.get("name"):
        profile = await _sofascore_referee_profile_by_name(official["name"])
        if profile:
            profile["source"] = official.get("source")
            profile["source_url"] = official.get("source_url")
            profile["official"] = True
            return profile
        return {
            "available": False,
            "assigned": True,
            "name": official["name"],
            "source": "RFEF",
            "source_url": official.get("source_url"),
            "official": True,
            "message": "Назначение подтверждено RFEF, статистика арбитра пока не найдена.",
        }

    event = await _sofascore_find_match_event(home_name, away_name, kickoff_utc)
    if not isinstance(event, dict):
        return {
            "available": False,
            "assigned": False,
            "source": None,
            "official": False,
            "message": "Официальное назначение арбитра пока не найдено.",
        }

    referee = event.get("referee") or {}
    if not isinstance(referee, dict) or not referee.get("id"):
        return {
            "available": False,
            "assigned": False,
            "source": None,
            "official": False,
            "message": "Официальное назначение арбитра пока не найдено.",
        }

    referee_id = referee.get("id")
    profile = await sofascore_get(f"/referee/{referee_id}")
    profile = profile if isinstance(profile, dict) else {}
    profile_ref = profile.get("referee") or {}
    stats = profile.get("statistics") or {}

    matches = int(safe_float(stats.get("matchesTotal"), 0) or 0)
    yellow_total = safe_float(stats.get("yellowCardsTotal"), 0.0) or 0.0
    red_total = safe_float(stats.get("redCardsTotal"), 0.0) or 0.0
    yellow_red_total = safe_float(stats.get("yellowRedCardsTotal"), 0.0) or 0.0

    return {
        "available": matches > 0,
        "assigned": True,
        "id": referee_id,
        "name": profile_ref.get("name") or referee.get("name") or referee.get("shortName") or "—",
        "matches": matches,
        "yellow_total": round(yellow_total, 1),
        "yellow_average": round(yellow_total / matches, 3) if matches else None,
        "red_average": round((red_total + yellow_red_total) / matches, 3) if matches else None,
        "source": "SofaScore",
        "official": False,
        "message": None if matches else "Арбитр найден, но статистика карточек недоступна.",
    }


async def calculate_cards_analysis(home_team, away_team, odds_event=None):
    print("\n🟨 YELLOW CARDS V1 → last 30 matches + referee")

    kickoff_utc = odds_event.get("commence_time") if isinstance(odds_event, dict) else None

    home_rows, away_rows, referee = await asyncio.gather(
        fotmob_recent_yellow_history(home_team["name"], CARDS_MATCH_LIMIT),
        fotmob_recent_yellow_history(away_team["name"], CARDS_MATCH_LIMIT),
        _sofascore_referee_stats(home_team["name"], away_team["name"], kickoff_utc),
    )

    home_stats = _cards_team_summary(home_rows)
    away_stats = _cards_team_summary(away_rows)

    home_avg = safe_float(home_stats.get("average"), None)
    away_avg = safe_float(away_stats.get("average"), None)
    team_total = (
        home_avg + away_avg
        if home_avg is not None and away_avg is not None
        else None
    )
    ref_avg = safe_float((referee or {}).get("yellow_average"), None)

    if team_total is not None and ref_avg is not None:
        expected_total = team_total * 0.70 + ref_avg * 0.30
    else:
        expected_total = team_total if team_total is not None else ref_avg

    home_sample = int(home_stats.get("sample") or 0)
    away_sample = int(away_stats.get("sample") or 0)
    referee_matches = int((referee or {}).get("matches") or 0)

    team_quality = min(1.0, min(home_sample, away_sample) / CARDS_MATCH_LIMIT)
    referee_quality = min(1.0, referee_matches / 50.0) if ref_avg is not None else 0.0
    quality = team_quality * 0.75 + referee_quality * 0.25 if ref_avg is not None else team_quality * 0.85

    print(f"   {home_team['name']}: {home_avg if home_avg is not None else 'N/A'} YC | {home_sample}/30")
    print(f"   {away_team['name']}: {away_avg if away_avg is not None else 'N/A'} YC | {away_sample}/30")
    if (referee or {}).get("assigned"):
        print(
            f"   Referee: {(referee or {}).get('name')} | "
            f"{ref_avg if ref_avg is not None else 'N/A'} YC/match | {referee_matches} matches"
        )
    else:
        print(f"   Referee: {(referee or {}).get('message', 'not available')}")
    if expected_total is not None:
        print(f"   Expected yellow cards: {expected_total:.2f}")

    available = home_avg is not None or away_avg is not None
    return {
        "available": available,
        "home": {
            "average": home_avg,
            "sample": home_sample,
            "last5": home_stats.get("last5"),
            "last10": home_stats.get("last10"),
        },
        "away": {
            "average": away_avg,
            "sample": away_sample,
            "last5": away_stats.get("last5"),
            "last10": away_stats.get("last10"),
        },
        "team_total_average": round(team_total, 3) if team_total is not None else None,
        "expected_total": round(expected_total, 3) if expected_total is not None else None,
        "referee": referee,
        "quality": round(max(0.0, min(1.0, quality)) * 100.0, 1),
        "message": None if available else "Недостаточно данных по жёлтым карточкам.",
    }


# ============================================================
# INTEGRATION WITH MAIN ANALYSIS
# ============================================================

_BASE_ANALYZE_MATCH_V58 = analyze_match

async def analyze_match(home_team, away_team):
    result = await _BASE_ANALYZE_MATCH_V58(home_team, away_team)
    odds_event = result.get("odds_event")

    corner_task = calculate_corner_analysis(home_team, away_team, odds_event)
    cards_task = calculate_cards_analysis(home_team, away_team, odds_event)

    corners, cards = await asyncio.gather(
        corner_task,
        cards_task,
        return_exceptions=True,
    )

    if isinstance(corners, Exception):
        print(f"⚠️ Corner analysis error: {corners}")
        result["corners"] = None
    else:
        result["corners"] = corners

    if isinstance(cards, Exception):
        print(f"⚠️ Yellow-card analysis error: {cards}")
        result["cards"] = {
            "available": False,
            "message": "Анализ жёлтых карточек временно недоступен.",
        }
    else:
        result["cards"] = cards

    corners_data = result.get("corners") or {}
    corner_candidates = corners_data.get("candidates") or []
    base_best = result.get("model", {}).get("best")

    if corner_candidates:
        best_corner = corner_candidates[0]
        base_value = (
            float(base_best.get("value", -999))
            if isinstance(base_best, dict)
            else -999.0
        )
        if best_corner.get("value", -999.0) > base_value:
            result["best_overall"] = {"type": "corner", **best_corner}
        else:
            result["best_overall"] = {"type": "football", **(base_best or {})}
    else:
        result["best_overall"] = (
            {"type": "football", **base_best}
            if isinstance(base_best, dict)
            else None
        )

    return result


_BASE_FORMAT_ANALYSIS_V58 = format_analysis

def format_analysis(result):
    text = _BASE_FORMAT_ANALYSIS_V58(result)
    corners = result.get("corners") or {}

    lines = [text, "", "🟩 <b>КУТОВІ — V59 PRO</b>"]

    if corners:
        lines.append(
            f"Очікувано: {result['home']['name']} "
            f"{corners.get('home_expected', 0):.2f} | "
            f"{result['away']['name']} "
            f"{corners.get('away_expected', 0):.2f} | "
            f"разом {safe_float(corners.get('total_expected'), 0.0):.2f}"
        )

        cc = corners.get("candidates") or []
        all_lines = corners.get("all_lines") or []

        if cc:
            b = cc[0]
            lines.append(
                f"🏆 <b>Краща ставка на кути:</b> {b['label']} — "
                f"{b['selection']} {b['line']} @ {b['odds']}"
            )
            lines.append(
                f"📈 P: {b['probability']*100:.1f}% | "
                f"Fair: {b['fair_odds']:.2f} | "
                f"Value: {b['value']*100:+.1f}% | "
                f"Confidence: {b['confidence']:.1f}%"
            )
            lines.append(
                f"📊 Stability: {b.get('stability', 0)*100:.0f}% | "
                f"Consistency: {b.get('consistency', 0)*100:.0f}% | "
                f"Grade: {b.get('grade', 'NO BET')}"
            )
            if b.get("bookmaker"):
                lines.append(f"💰 Букмекер: {b['bookmaker']}")
        else:
            lines.append("⚠️ Немає corner ставки, яка проходить фільтри моделі.")

        if all_lines:
            lines.append("")
            lines.append("<b>📊 Усі доступні лінії:</b>")
            for c in all_lines[:20]:
                marker = "⭐" if c.get("grade") in ("VALUE", "STRONG BET") else "•"
                lines.append(
                    f"{marker} {c['label']} — {c['selection']} {c['line']:.1f} "
                    f"@ {c['odds']:.2f} | "
                    f"P {c['probability']*100:.1f}% | "
                    f"V {c['value']*100:+.1f}% | "
                    f"C {c['confidence']:.1f}% | "
                    f"{c.get('grade', 'NO BET')}"
                )
    else:
        lines.append("⚠️ Статистика кутових недоступна.")

    best = result.get("best_overall")
    if best:
        lines.append("")
        if best.get("type") == "corner":
            lines.append(
                f"🔥 <b>НАЙКРАЩА СТАВКА МАТЧУ:</b> "
                f"{best.get('label')} — {best.get('selection')} "
                f"{best.get('line')} @ {best.get('odds')}"
            )
        else:
            lines.append("🔥 <b>НАЙКРАЩА СТАВКА МАТЧУ:</b> основний футбольний ринок")

    return "\n".join(lines)


# ============================================================
# FASTAPI WEB API — V25 CORE + REAL xG + CORNERS
# ============================================================

WEB_TEAMS = []


class MatchRequest(BaseModel):
    home_team: str
    away_team: str


async def ensure_teams_loaded():
    global WEB_TEAMS
    if not WEB_TEAMS:
        WEB_TEAMS = await load_all_teams()
    return WEB_TEAMS


def probability_percent(value):
    return round(safe_float(value, 0.0) * 100.0, 1)


def poisson_total_probability(home_xg, away_xg, line, over=True):
    matrix = build_score_matrix(home_xg, away_xg)
    probability = 0.0
    threshold = math.floor(line) + 1
    for (home_goals, away_goals), p in matrix.items():
        total = home_goals + away_goals
        if over and total >= threshold:
            probability += p
        elif not over and total < threshold:
            probability += p
    return probability


def form_sequence(history, team_id, before_date, limit=5):
    rows = calculate_form(history, team_id, before_date, limit=limit)
    out = []
    for row in rows:
        try:
            if row.get("result") in ("W", "D", "L"):
                out.append(row["result"])
                continue
            home = row.get("homeTeam", {})
            away = row.get("awayTeam", {})
            score = row.get("score", {}).get("fullTime", {})
            hg, ag = score.get("home"), score.get("away")
            if hg is None or ag is None:
                continue
            if home.get("id") == team_id:
                out.append("W" if hg > ag else "D" if hg == ag else "L")
            elif away.get("id") == team_id:
                out.append("W" if ag > hg else "D" if ag == hg else "L")
        except Exception:
            pass
    return out[:limit]


def serialize_scores(items):
    out = []
    for item in items or []:
        try:
            (hg, ag), p = item
            out.append({"home": int(hg), "away": int(ag), "probability": probability_percent(p)})
        except Exception:
            pass
    return out


def map_candidate(candidate):
    if not isinstance(candidate, dict):
        return None
    return {
        "market": candidate.get("market"),
        "selection": candidate.get("name") or candidate.get("selection"),
        "name": candidate.get("name") or candidate.get("selection"),
        "odds": candidate.get("odds"),
        "probability": probability_percent(candidate.get("probability")),
        "value": None if candidate.get("value") is None else round(safe_float(candidate.get("value")), 4),
        "confidence": round(safe_float(candidate.get("confidence")), 1),
    }


def map_corner_candidate(candidate):
    if not isinstance(candidate, dict):
        return None
    return {
        "label": candidate.get("label"),
        "selection": candidate.get("selection"),
        "line": candidate.get("line"),
        "odds": candidate.get("odds"),
        "probability": probability_percent(candidate.get("probability")),
        "fair_odds": None if candidate.get("fair_odds") is None else round(safe_float(candidate.get("fair_odds")), 2),
        "value": None if candidate.get("value") is None else round(safe_float(candidate.get("value")), 4),
        "confidence": round(safe_float(candidate.get("confidence")), 1),
        "bookmaker": candidate.get("bookmaker"),
        "grade": candidate.get("grade"),
        "stability": candidate.get("stability"),
        "consistency": candidate.get("consistency"),
    }


def build_web_response(result):
    home = result["home"]
    away = result["away"]
    model = result.get("model", {})
    probabilities = model.get("probabilities", {})
    real_odds = result.get("real_odds", {})

    home_xg = safe_float(model.get("home_xg"), 0.0)
    away_xg = safe_float(model.get("away_xg"), 0.0)

    before_date = datetime.now(timezone.utc).isoformat()
    home_history = HISTORY_CACHE.get(home["id"], [])
    away_history = HISTORY_CACHE.get(away["id"], [])

    home_form_stats = model.get("home_home_form", {}) or {}
    away_form_stats = model.get("away_away_form", {}) or {}

    over_05 = poisson_total_probability(home_xg, away_xg, 0.5, True)
    over_15 = poisson_total_probability(home_xg, away_xg, 1.5, True)
    over_35 = poisson_total_probability(home_xg, away_xg, 3.5, True)

    odds = {
        "1": best_odds(real_odds.get("home", [])),
        "X": best_odds(real_odds.get("draw", [])),
        "2": best_odds(real_odds.get("away", [])),
        "1X": best_odds(real_odds.get("double_home", [])),
        "X2": best_odds(real_odds.get("double_away", [])),
        "over_2_5": best_odds(real_odds.get("over25", [])),
        "under_2_5": best_odds(real_odds.get("under25", [])),
        "btts_yes": best_odds(real_odds.get("btts_yes", [])),
        "btts_no": best_odds(real_odds.get("btts_no", [])),
    }

    candidates = [x for x in (map_candidate(v) for v in model.get("candidates", [])) if x]
    best_bet = map_candidate(model.get("best"))

    kickoff_utc = None
    kickoff_kyiv = None
    odds_event = result.get("odds_event")
    if isinstance(odds_event, dict):
        kickoff_utc = odds_event.get("commence_time")
        dt = parse_datetime_utc(kickoff_utc)
        if dt is not None:
            try:
                kickoff_kyiv = dt.astimezone(ZoneInfo("Europe/Kyiv")).isoformat()
            except Exception:
                kickoff_kyiv = kickoff_utc

    real_xg = model.get("real_xg", {}) or {}
    home_real = real_xg.get("home") or {}
    away_real = real_xg.get("away") or {}

    corners = result.get("corners") or {}
    corner_candidates = [
        x for x in (map_corner_candidate(v) for v in corners.get("candidates", [])) if x
    ]
    corner_all_lines = [
        x for x in (map_corner_candidate(v) for v in corners.get("all_lines", [])) if x
    ]

    # Keep the original V25 web response contract. The frontend renders
    # ai_assessment.rating/risk/summary directly, so this object must always
    # be present even when no value bet is found.
    if best_bet:
        confidence = safe_float(best_bet.get("confidence"), 0.0)
        if confidence >= 80:
            rating, risk = "EXCELLENT", "LOW"
        elif confidence >= 70:
            rating, risk = "GOOD", "LOW"
        elif confidence >= 60:
            rating, risk = "MEDIUM", "MODERATE"
        else:
            rating, risk = "WEAK", "HIGH"
        summary = (
            f"V25 model selects {best_bet['selection']} as the strongest value option "
            f"at {best_bet['probability']:.1f}% model probability."
        )
    else:
        rating, risk = "NO_VALUE", "—"
        summary = "V25 did not find a market that passes both Value and Confidence filters."

    return {
        "status": "success",
        "version": "3.2.2-cards-pro-rfef-referee-ru-search-statistics-v25-xg-corners",
        "match": {
            "home_team": home.get("name"),
            "away_team": away.get("name"),
            "league": home.get("league_name"),
            "league_code": home.get("league_code"),
            "league_emblem": home.get("league_emblem"),
            "home_crest": home.get("crest"),
            "away_crest": away.get("crest"),
            "home_tla": home.get("tla"),
            "away_tla": away.get("tla"),
            "kickoff_utc": kickoff_utc,
            "kickoff_kyiv": kickoff_kyiv,
        },
        "prediction": {
            "home": probability_percent(probabilities.get("home_win")),
            "draw": probability_percent(probabilities.get("draw")),
            "away": probability_percent(probabilities.get("away_win")),
            "double_home": probability_percent(probabilities.get("double_home")),
            "double_away": probability_percent(probabilities.get("double_away")),
        },
        "xg": {
            "home": round(home_xg, 2),
            "away": round(away_xg, 2),
            "total": round(home_xg + away_xg, 2),
            "base_home": round(safe_float(model.get("base_home_xg"), home_xg), 2),
            "base_away": round(safe_float(model.get("base_away_xg"), away_xg), 2),
            "real": {
                "home_available": bool(home_real.get("available")),
                "away_available": bool(away_real.get("available")),
                "home_xg": home_real.get("xg"),
                "home_xga": home_real.get("xga"),
                "home_sample": home_real.get("sample", 0),
                "away_xg": away_real.get("xg"),
                "away_xga": away_real.get("xga"),
                "away_sample": away_real.get("sample", 0),
            },
        },
        "goals": {
            "over_0_5": probability_percent(over_05),
            "over_1_5": probability_percent(over_15),
            "over_2_5": probability_percent(probabilities.get("over_25")),
            "over_3_5": probability_percent(over_35),
            "under_0_5": probability_percent(1 - over_05),
            "under_1_5": probability_percent(1 - over_15),
            "under_2_5": probability_percent(probabilities.get("under_25")),
            "under_3_5": probability_percent(1 - over_35),
        },
        "btts": {
            "yes": probability_percent(probabilities.get("btts_yes")),
            "no": probability_percent(probabilities.get("btts_no")),
        },
        "most_likely_scores": serialize_scores(probabilities.get("most_likely_scores")),
        "form": {
            "home": form_sequence(home_history, home["id"], before_date, 5),
            "away": form_sequence(away_history, away["id"], before_date, 5),
            "home_home": home_form_stats,
            "away_away": away_form_stats,
        },
        "attack": {
            "home": round(safe_float(home_form_stats.get("attack")), 2),
            "away": round(safe_float(away_form_stats.get("attack")), 2),
        },
        "defense": {
            "home": round(safe_float(home_form_stats.get("defence")), 2),
            "away": round(safe_float(away_form_stats.get("defence")), 2),
        },
        "halves": {
            "home": model.get("home_halves", {}) or {},
            "away": model.get("away_halves", {}) or {},
        },
        "h2h": model.get("h2h", {}) or {},
        "corners": {
            "available": bool(corners),
            "home": corners.get("home_expected"),
            "away": corners.get("away_expected"),
            "total": corners.get("total_expected"),
            "candidates": corner_candidates,
            "all_lines": corner_all_lines,
            "message": None if corners else "Corner data unavailable for this match.",
        },
        "cards": result.get("cards") or {
            "available": False,
            "message": "Анализ жёлтых карточек недоступен.",
        },
        "odds": odds,
        "bookmakers_count": result.get("bookmakers_count", 0),
        "betting_markets": candidates,
        "best_bet": best_bet,
        "best_overall": result.get("best_overall"),
        "ai_assessment": {
            "rating": rating,
            "risk": risk,
            "summary": summary,
        },
        "history": {
            "home_matches": result.get("home_history", 0),
            "away_matches": result.get("away_history", 0),
        },
    }


# ============================================================
# FOOTBALLISTIKA — BET OF THE DAY JOURNAL / MONTHLY STATISTICS
# ============================================================

STATS_DB_PATH = Path(__file__).resolve().with_name("footballistika_stats.sqlite3")


def _stats_connect():
    conn = sqlite3.connect(STATS_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_stats_db():
    with _stats_connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_key TEXT NOT NULL UNIQUE,
                home_id INTEGER,
                away_id INTEGER,
                home_team TEXT NOT NULL,
                away_team TEXT NOT NULL,
                league TEXT,
                kickoff_utc TEXT,
                market TEXT,
                selection TEXT,
                odds REAL,
                probability REAL,
                value REAL,
                confidence REAL,
                status TEXT NOT NULL DEFAULT 'pending',
                home_score INTEGER,
                away_score INTEGER,
                profit REAL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                settled_at TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_daily_bets_kickoff ON daily_bets(kickoff_utc)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_daily_bets_status ON daily_bets(status)")
        conn.commit()


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _match_key(home_id, away_id, kickoff_utc, home_team, away_team):
    # Event IDs are not guaranteed to exist in every provider response.
    # Team IDs + kickoff is stable enough for one row per match.
    kick = kickoff_utc or "unknown"
    return f"{home_id}:{away_id}:{kick}:{home_team}:{away_team}"


def save_bet_of_day(web_response, home_team, away_team):
    """Persist the recommendation shown as BET OF THE DAY.

    Re-analysis before kickoff refreshes the recommendation. Once the match has
    started/finished, the journal entry is frozen so historical statistics cannot
    be rewritten afterwards.
    """
    init_stats_db()
    match = web_response.get("match") or {}
    bet = web_response.get("best_bet")
    if not isinstance(bet, dict):
        markets = web_response.get("betting_markets") or []
        bet = markets[0] if markets and isinstance(markets[0], dict) else None
    kickoff_utc = match.get("kickoff_utc")
    key = _match_key(home_team.get("id"), away_team.get("id"), kickoff_utc, match.get("home_team"), match.get("away_team"))
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    market = bet.get("market") if isinstance(bet, dict) else None
    selection = (bet.get("selection") or bet.get("name")) if isinstance(bet, dict) else None
    odds = safe_float(bet.get("odds"), None) if isinstance(bet, dict) and bet.get("odds") is not None else None
    probability = safe_float(bet.get("probability"), None) if isinstance(bet, dict) and bet.get("probability") is not None else None
    value = safe_float(bet.get("value"), None) if isinstance(bet, dict) and bet.get("value") is not None else None
    confidence = safe_float(bet.get("confidence"), None) if isinstance(bet, dict) and bet.get("confidence") is not None else None
    new_status = "pending" if bet else "no_bet"

    with _stats_connect() as conn:
        existing = conn.execute("SELECT * FROM daily_bets WHERE match_key = ?", (key,)).fetchone()
        if existing:
            # Freeze after settlement or after kickoff.
            if existing["status"] in ("win", "loss", "void"):
                row = dict(existing)
                print(f"📒 STATS → already settled: {row['home_team']} - {row['away_team']} | {row['status']}")
                return row
            kickoff_dt = parse_datetime_utc(existing["kickoff_utc"] or kickoff_utc)
            if kickoff_dt is not None and kickoff_dt <= now:
                row = dict(existing)
                print(f"📒 STATS → frozen after kickoff: {row['home_team']} - {row['away_team']}")
                return row
            conn.execute(
                """
                UPDATE daily_bets
                SET market=?, selection=?, odds=?, probability=?, value=?, confidence=?,
                    status=?, updated_at=?
                WHERE match_key=?
                """,
                (market, selection, odds, probability, value, confidence, new_status, now_iso, key),
            )
        else:
            conn.execute(
                """
                INSERT INTO daily_bets (
                    match_key, home_id, away_id, home_team, away_team, league,
                    kickoff_utc, market, selection, odds, probability, value,
                    confidence, status, profit, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    key,
                    home_team.get("id"), away_team.get("id"),
                    match.get("home_team") or home_team.get("name"),
                    match.get("away_team") or away_team.get("name"),
                    match.get("league"), kickoff_utc,
                    market, selection, odds, probability, value, confidence,
                    new_status, 0.0 if new_status == "no_bet" else None,
                    now_iso, now_iso,
                ),
            )
        conn.commit()
        saved = conn.execute("SELECT * FROM daily_bets WHERE match_key = ?", (key,)).fetchone()
        row = dict(saved) if saved else None
        if row:
            print(f"📒 STATS SAVED → {row['home_team']} - {row['away_team']} | {row.get('selection') or 'NO BET'} | status={row['status']}")
        return row


def _settle_market(market, selection, home_goals, away_goals):
    key = str(market or selection or "").strip().lower().replace(" ", "_")
    total = home_goals + away_goals

    if key in {"home_win", "п1", "home"}:
        return home_goals > away_goals
    if key in {"away_win", "п2", "away"}:
        return away_goals > home_goals
    if key in {"draw", "x", "нічия", "ничья"}:
        return home_goals == away_goals
    if key in {"double_home", "1x", "1х"}:
        return home_goals >= away_goals
    if key in {"double_away", "x2", "х2"}:
        return away_goals >= home_goals
    if key in {"over_25", "over25", "o2.5", "тб2.5", "тб_2.5"}:
        return total >= 3
    if key in {"under_25", "under25", "u2.5", "тм2.5", "тм_2.5"}:
        return total <= 2
    if key in {"btts_yes", "оз_—_да", "оз_—_так", "btts"}:
        return home_goals > 0 and away_goals > 0
    if key in {"btts_no", "оз_—_нет", "оз_—_ні"}:
        return home_goals == 0 or away_goals == 0
    return None


async def settle_pending_bets():
    """Resolve finished matches against football-data.org.

    Called when the statistics page is opened. Pending matches remain pending if
    the provider is rate-limited or the final score is not available yet.
    """
    init_stats_db()
    now = datetime.now(timezone.utc)
    with _stats_connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM daily_bets
            WHERE status='pending' AND kickoff_utc IS NOT NULL
            ORDER BY kickoff_utc ASC
            """
        ).fetchall()

    due = []
    for row in rows:
        dt = parse_datetime_utc(row["kickoff_utc"])
        if dt is not None and dt <= now - timedelta(hours=1, minutes=30):
            due.append(row)
    if not due:
        return

    # One provider request per home team, even if several journal rows exist.
    by_home = {}
    for row in due:
        by_home.setdefault(row["home_id"], []).append(row)

    for home_id, team_rows in by_home.items():
        if not home_id:
            continue
        kickoff_dates = [parse_datetime_utc(r["kickoff_utc"]) for r in team_rows]
        kickoff_dates = [d for d in kickoff_dates if d is not None]
        if not kickoff_dates:
            continue
        date_from = (min(kickoff_dates) - timedelta(days=1)).date().isoformat()
        date_to = now.date().isoformat()
        try:
            data = await football_api_get(
                f"{FOOTBALL_BASE_URL}/teams/{home_id}/matches",
                params={"status": "FINISHED", "dateFrom": date_from, "dateTo": date_to, "limit": 100},
                retries=2,
            )
            matches = (data or {}).get("matches", [])
        except Exception as exc:
            print(f"⚠️ STATS settlement failed for team {home_id}: {exc}")
            continue

        for row in team_rows:
            kickoff = parse_datetime_utc(row["kickoff_utc"])
            matched = None
            for match in matches:
                h = (match.get("homeTeam") or {}).get("id")
                a = (match.get("awayTeam") or {}).get("id")
                mdt = parse_datetime_utc(match.get("utcDate"))
                if h != row["home_id"] or a != row["away_id"] or mdt is None or kickoff is None:
                    continue
                if abs((mdt - kickoff).total_seconds()) <= 12 * 3600:
                    matched = match
                    break
            if not matched:
                continue

            full = ((matched.get("score") or {}).get("fullTime") or {})
            hg = full.get("home")
            ag = full.get("away")
            if hg is None or ag is None:
                continue
            verdict = _settle_market(row["market"], row["selection"], int(hg), int(ag))
            if verdict is None:
                status = "void"
                profit = 0.0
            else:
                status = "win" if verdict else "loss"
                odds = safe_float(row["odds"], 0.0)
                profit = round((odds - 1.0) if verdict and odds > 0 else (-1.0 if not verdict else 0.0), 4)

            with _stats_connect() as conn:
                conn.execute(
                    """
                    UPDATE daily_bets
                    SET status=?, home_score=?, away_score=?, profit=?, settled_at=?, updated_at=?
                    WHERE id=?
                    """,
                    (status, int(hg), int(ag), profit, _utc_now_iso(), _utc_now_iso(), row["id"]),
                )
                conn.commit()


def _month_bounds(month_text):
    if month_text:
        try:
            year, month = [int(x) for x in month_text.split("-", 1)]
            start = datetime(year, month, 1, tzinfo=timezone.utc)
        except Exception:
            raise HTTPException(status_code=400, detail="month must have YYYY-MM format")
    else:
        now = datetime.now(timezone.utc)
        start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    if start.month == 12:
        end = datetime(start.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(start.year, start.month + 1, 1, tzinfo=timezone.utc)
    return start, end


def read_month_statistics(month_text=None):
    init_stats_db()
    start, end = _month_bounds(month_text)
    with _stats_connect() as conn:
        month_key = start.strftime("%Y-%m")
        rows = conn.execute(
            """
            SELECT * FROM daily_bets
            WHERE substr(COALESCE(kickoff_utc, created_at), 1, 7) = ?
            ORDER BY COALESCE(kickoff_utc, created_at) DESC, id DESC
            """,
            (month_key,),
        ).fetchall()

    items = [dict(r) for r in rows]
    settled = [r for r in items if r["status"] in ("win", "loss", "void")]
    graded = [r for r in items if r["status"] in ("win", "loss")]
    wins = sum(1 for r in graded if r["status"] == "win")
    losses = sum(1 for r in graded if r["status"] == "loss")
    pending = sum(1 for r in items if r["status"] == "pending")
    no_bet = sum(1 for r in items if r["status"] == "no_bet")
    profit = round(sum(safe_float(r.get("profit"), 0.0) for r in settled), 2)
    staked = len(graded)  # flat stake: 1 unit per Bet of the Day
    roi = round((profit / staked * 100.0), 1) if staked else 0.0
    win_rate = round((wins / len(graded) * 100.0), 1) if graded else 0.0

    return {
        "status": "success",
        "month": start.strftime("%Y-%m"),
        "summary": {
            "profit_units": profit,
            "roi_percent": roi,
            "bets_settled": len(graded),
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "pending": pending,
            "no_bet": no_bet,
            "matches_analyzed": len(items),
            "stake_per_bet": 1.0,
        },
        "bets": items,
    }


init_stats_db()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await close_sessions()


app = FastAPI(
    title="Football AI Analyst",
    description="V25 web engine with real xG and corners",
    version="3.2.2",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {
        "status": "ok",
        "app": "Football AI Analyst",
        "version": "3.2.2-cards-pro-rfef-referee-ru-search-statistics-v25-xg-corners",
        "model": "V25 core + FotMob real xG + V63 corners",
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "version": "3.2.2-cards-pro-rfef-referee-ru-search-statistics-v25-xg-corners",
        "teams_loaded": len(WEB_TEAMS),
    }




@app.get("/statistics")
async def statistics(month: str | None = None):
    settlement_warning = None
    try:
        await settle_pending_bets()
    except Exception as exc:
        settlement_warning = str(exc)
        print(f"⚠️ STATS settlement skipped: {repr(exc)}")

    payload = read_month_statistics(month)
    if settlement_warning:
        payload["settlement_warning"] = settlement_warning
    return payload


@app.get("/statistics/raw")
async def statistics_raw(month: str | None = None):
    """Return saved journal rows immediately, without checking match results."""
    return read_month_statistics(month)


@app.get("/statistics/debug")
async def statistics_debug():
    init_stats_db()
    with _stats_connect() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM daily_bets").fetchone()["n"]
        rows = conn.execute("SELECT * FROM daily_bets ORDER BY id DESC LIMIT 10").fetchall()
    return {
        "status": "success",
        "db_path": str(STATS_DB_PATH),
        "total_rows": total,
        "last_rows": [dict(r) for r in rows],
    }


@app.post("/analyze")
async def analyze_web_match(match: MatchRequest):
    home_query = match.home_team.strip()
    away_query = match.away_team.strip()

    if not home_query or not away_query:
        raise HTTPException(status_code=400, detail="Both home_team and away_team are required")

    teams = await ensure_teams_loaded()
    home_team = search_team(home_query, teams)
    away_team = search_team(away_query, teams)

    if home_team is None:
        raise HTTPException(status_code=404, detail=f"Home team not found: {home_query}")
    if away_team is None:
        raise HTTPException(status_code=404, detail=f"Away team not found: {away_query}")
    if home_team["id"] == away_team["id"]:
        raise HTTPException(status_code=400, detail="Home and away teams must be different")

    try:
        result = await analyze_match(home_team, away_team)
        response = build_web_response(result)
        journal_entry = save_bet_of_day(response, home_team, away_team)
        response["journal_entry"] = journal_entry
        return response
    except Exception as exc:
        print(f"❌ WEB ANALYZE ERROR: {repr(exc)}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}") from exc
