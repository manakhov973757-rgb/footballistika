import os
import re
import math
import asyncio
import aiohttp

from difflib import SequenceMatcher
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from dotenv import load_dotenv


# ============================================================
# FOOTBALL AI ANALYST V25
# ============================================================
# V25
#
# + Ukrainian / English / fuzzy search
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


if not FOOTBALL_DATA_TOKEN:
    raise RuntimeError("Не знайдено FOOTBALL_DATA_TOKEN у .env")

if not ODDS_API_KEY:
    raise RuntimeError("Не знайдено ODDS_API_KEY у .env")


FOOTBALL_BASE_URL = "https://api.football-data.org/v4"
ODDS_BASE_URL = "https://api.the-odds-api.com/v4"


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


# ============================================================
# SESSIONS
# ============================================================

FOOTBALL_SESSION = None
ODDS_SESSION = None


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


async def close_sessions():

    global FOOTBALL_SESSION
    global ODDS_SESSION

    if FOOTBALL_SESSION:

        await FOOTBALL_SESSION.close()
        FOOTBALL_SESSION = None

    if ODDS_SESSION:

        await ODDS_SESSION.close()
        ODDS_SESSION = None


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

    # Exact
    for team in teams:

        if normalized in get_team_names(team):
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
                timeout=aiohttp.ClientTimeout(
                    total=30
                )
            ) as response:

                text = await response.text()

                if response.status == 200:

                    return await response.json()

                if response.status == 429:

                    print(
                        "⚠️ Football API 429"
                    )

                    await asyncio.sleep(
                        10
                    )

                    continue

                raise Exception(
                    f"Football API "
                    f"{response.status}: "
                    f"{text}"
                )

        except asyncio.TimeoutError:

            if attempt == retries - 1:
                raise

            await asyncio.sleep(2)

        except aiohttp.ClientError as e:

            if attempt == retries - 1:
                raise

            print(
                f"HTTP error: {e}"
            )

            await asyncio.sleep(2)

    raise Exception(
        "Football API request failed"
    )


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


async def odds_api_event_get(sport_key, event_id, markets="btts"):
    """Get odds for one exact event. Never affects the standard odds if an additional market is unavailable."""
    if not sport_key or not event_id:
        return None

    session = await get_odds_session()
    url = f"{ODDS_BASE_URL}/sports/{sport_key}/events/{event_id}/odds"

    # Try EU first, then UK. Some additional soccer markets have limited bookmaker/region coverage.
    for region in ("eu", "uk"):
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": region,
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
                    print(f"⚠️ Event odds {markets} [{region}] HTTP {response.status}: {text[:500]}")
                    continue

                try:
                    data = await response.json(content_type=None)
                except Exception as e:
                    print(f"⚠️ Event odds JSON [{region}]: {e}")
                    continue

                if isinstance(data, dict) and isinstance(data.get("bookmakers"), list):
                    print(
                        f"   ✅ Event odds {markets} [{region}]: "
                        f"{len(data.get('bookmakers', []))} bookmakers"
                    )
                    return data

                print(f"⚠️ Event odds {markets} [{region}]: некоректна відповідь API")

        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            print(f"⚠️ Event odds connection [{region}]: {e}")
        except Exception as e:
            print(f"⚠️ Event odds error [{region}]: {e}")

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

        return HISTORY_CACHE[
            team_id
        ]

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

        except Exception as e:

            print(
                f"   ⚠️ сезон {season}: {e}"
            )

        await asyncio.sleep(
            0.4
        )

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

    HISTORY_CACHE[
        team_id
    ] = filtered

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
# XG MODEL V25
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
    value,
    market
):
    probability = safe_float(probability, 0.0)
    value = None if value is None else safe_float(value, 0.0)

    score = probability * 55.0

    if value is not None:
        score += min(max(value * 100.0, 0.0), 20.0)

    if market in ("double_home", "double_away"):
        score += 8.0
    elif market in ("over_25", "under_25"):
        score += 5.0
    elif market in ("btts_yes", "btts_no"):
        score += 5.0

    return min(max(score, 0.0), 100.0)


# ============================================================
# ODDS HELPERS
# ============================================================

def names_match(name1, name2):
    """Надійне порівняння назв команд Football Data API / Odds API."""
    a = normalize_name(name1)
    b = normalize_name(name2)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True

    special = {
        "inter milan": {"inter", "internazionale", "fc internazionale milano"},
        "inter": {"inter milan", "internazionale", "fc internazionale milano"},
        "barcelona": {"fc barcelona", "barca"},
        "real madrid": {"real madrid cf"},
        "bayern munich": {"bayern", "fc bayern munich"},
        "bayer leverkusen": {"bayer", "bayer 04 leverkusen"},
        "brighton": {"brighton and hove albion", "brighton hove albion"},
        "lyon": {"olympique lyonnais", "olympique lyon"},
        "rennes": {"stade rennais", "stade rennais fc"},
        "fiorentina": {"acf fiorentina"},
        "celta vigo": {"rc celta de vigo", "celta de vigo", "celta"},
        "rc celta de vigo": {"celta vigo", "celta de vigo", "celta"},
        "osasuna": {"ca osasuna"},
        "ca osasuna": {"osasuna"},
    }
    if b in special.get(a, set()) or a in special.get(b, set()):
        return True

    def team_tokens(value):
        stop = {
            "fc", "cf", "rc", "ca", "ud", "sd", "afc", "sc", "ac",
            "ss", "as", "us", "de", "del", "la", "el", "the",
            "club", "futbol", "football"
        }
        return {t for t in normalize_name(value).split() if t and t not in stop and len(t) > 1}

    ta = team_tokens(a)
    tb = team_tokens(b)
    if ta and tb:
        if ta == tb or ta.issubset(tb) or tb.issubset(ta):
            return True
        common = ta & tb
        if len(common) >= 2:
            ratio = len(common) / min(len(ta), len(tb))
            if ratio >= 0.66:
                return True

    return similarity(a, b) >= 0.84

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

                    # The Odds API may return labels such as:
                    #   "Real Madrid or Draw"
                    #   "Real Madrid or Real Sociedad"
                    # or compact labels "1X" / "X2".
                    # We only accept the home+draw combination for 1X.
                    # Odds API може повертати: "1X", "X2",
                    # "Team or Draw", "Draw or Team".
                    compact = re.sub(r"\s+", "", name)
                    parts = [x.strip() for x in re.split(r"\bor\b", name) if x.strip()]
                    has_draw = "draw" in name or "x" in parts

                    home_1x = compact == "1x"
                    away_x2 = compact == "x2"

                    if len(parts) == 2 and "draw" in parts:
                        other = parts[0] if parts[1] == "draw" else parts[1]
                        if names_match(other, home_name):
                            home_1x = True
                        if names_match(other, away_name):
                            away_x2 = True

                    # Деякі провайдери пишуть "home or draw" / "away or draw".
                    if "home" in parts and "draw" in parts:
                        home_1x = True
                    if "away" in parts and "draw" in parts:
                        away_x2 = True

                    if home_1x:
                        result["double_home"].append(price)
                        bookmaker_data["double_home"] = price
                    elif away_x2:
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

    print(
        f"   1X: "
        f"{best_odds(result['double_home'])}"
    )

    print(
        f"   X2: "
        f"{best_odds(result['double_away'])}"
    )

    return result



# ============================================================
# MODEL BUILDER
# ============================================================

def build_model(home_team, away_team, histories, before_date):
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

    home_xg, away_xg = calculate_xg_v25(
        safe_float(home_weighted.get("attack"), 1.35),
        safe_float(home_weighted.get("defence"), 1.35),
        safe_float(away_weighted.get("attack"), 1.35),
        safe_float(away_weighted.get("defence"), 1.35),
        home_form,
        away_form,
        h2h,
    )

    probabilities = calculate_probabilities(home_xg, away_xg)
    probabilities = calculate_market_probabilities(
        probabilities, home_form, away_form, h2h
    )

    return {
        "home_xg": safe_float(home_xg),
        "away_xg": safe_float(away_xg),
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

def find_candidates(probabilities, real_odds):
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

        odds = best_odds(real_odds.get(odds_key, []))
        if odds is None:
            continue

        value = calculate_value(probability, odds)
        if value is None or value < MIN_VALUE:
            continue

        confidence = calculate_confidence(probability, value, probability_key)
        confidence = safe_float(confidence)

        if confidence < safe_float(MIN_CONFIDENCE, 55.0):
            continue

        candidates.append({
            "market": probability_key,
            "name": name,
            "probability": probability,
            "odds": odds,
            "value": value,
            "confidence": confidence,
        })

    candidates.sort(
        key=lambda x: (safe_float(x.get("value")), safe_float(x.get("confidence"))),
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

    home_history = await get_team_history(
        home_team["id"]
    )

    away_history = await get_team_history(
        away_team["id"]
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
    # MODEL
    # ========================================================

    try:

        model = build_model(
            home_team,
            away_team,
            histories,
            before_date
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

            # ВАЖЛИВО: /sports/{sport}/odds НЕ підтримує double_chance.
            # Спочатку отримуємо тільки стандартні ринки, щоб знайти точний event ID.
            # 1X/X2 запитуємо ОКРЕМО через /events/{eventId}/odds.
            odds_events = await odds_api_get(
                odds_key,
                "h2h,totals"
            )

            if not isinstance(odds_events, list):
                odds_events = []

            # Якщо головний /odds endpoint тимчасово не повернув події,
            # не втрачаємо реальні коефіцієнти: беремо список подій без odds,
            # знаходимо event_id і запитуємо стандартні h2h,totals окремо.
            if not odds_events:
                try:
                    session = await get_odds_session()
                    events_url = f"{ODDS_BASE_URL}/sports/{odds_key}/events"
                    events_params = {
                        "apiKey": ODDS_API_KEY,
                        "regions": "eu",
                        "dateFormat": "iso",
                    }
                    async with session.get(
                        events_url,
                        params=events_params,
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as response:
                        if response.status == 200:
                            events_data = await response.json(content_type=None)
                            if isinstance(events_data, list):
                                fallback_event = find_odds_event(
                                    events_data, home_team, away_team
                                )
                                if fallback_event and fallback_event.get("id"):
                                    print("🔄 Fallback: запит стандартних odds через event endpoint")
                                    fallback_odds = await odds_api_event_get(
                                        odds_key,
                                        fallback_event.get("id"),
                                        "h2h,totals"
                                    )
                                    if isinstance(fallback_odds, dict):
                                        odds_events = [fallback_odds]
                except Exception as fallback_error:
                    print(f"⚠️ Odds fallback error: {fallback_error}")

            print(
                f"Odds API подій: "
                f"{len(odds_events)}"
            )

            if odds_events:

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

            # ========================================================
            # НАДІЙНИЙ FALLBACK: EVENTS -> EVENT ODDS
            # ========================================================
            # Якщо /odds не повернув потрібний матч (або повернув
            # події без точного збігу назв), не вважаємо, що odds немає.
            # /events безкоштовний і повертає точний event_id, після чого
            # /events/{eventId}/odds дозволяє отримати реальні коефіцієнти.
            if odds_event is None:
                try:
                    session = await get_odds_session()
                    events_url = f"{ODDS_BASE_URL}/sports/{odds_key}/events"
                    events_params = {
                        "apiKey": ODDS_API_KEY,
                        "dateFormat": "iso",
                    }

                    print("🔄 Fallback: шукаю event_id через /events ...")

                    async with session.get(
                        events_url,
                        params=events_params,
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as response:
                        text = await response.text()

                        if response.status == 200:
                            events_data = await response.json(content_type=None)
                            if isinstance(events_data, list):
                                fallback_event = find_odds_event(
                                    events_data,
                                    home_team,
                                    away_team
                                )

                                if fallback_event and fallback_event.get("id"):
                                    event_id = fallback_event["id"]
                                    print(f"✅ Event ID знайдено: {event_id}")

                                    # Отримуємо основні РЕАЛЬНІ коефіцієнти
                                    # окремим event-odds запитом.
                                    fallback_odds = await odds_api_event_get(
                                        odds_key,
                                        event_id,
                                        "h2h,totals"
                                    )

                                    if isinstance(fallback_odds, dict):
                                        odds_event = fallback_odds
                                        print("✅ Реальні h2h/totals коефіцієнти отримано через event endpoint")
                                else:
                                    print("⚠️ Точний event_id через /events не знайдено")
                        else:
                            print(f"⚠️ /events fallback HTTP {response.status}: {text[:500]}")

                except Exception as fallback_error:
                    print(f"⚠️ Events fallback error: {fallback_error}")

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

    if not real_odds.get("home") and not real_odds.get("draw") and not real_odds.get("away"):
        print("❌ КРИТИЧНО: реальні h2h коефіцієнти не отримані")
        print("   Бот НЕ буде вигадувати коефіцієнти для Value.")

    if real_odds.get("double_home"):
        print(f"✅ РЕАЛЬНИЙ 1X: {best_odds(real_odds.get('double_home'))}")
    else:
        print("⚠️ Реальний 1X не знайдений у відповіді букмекерів")

    if real_odds.get("double_away"):
        print(f"✅ РЕАЛЬНИЙ X2: {best_odds(real_odds.get('double_away'))}")
    else:
        print("⚠️ Реальний X2 не знайдений у відповіді букмекерів")

    # ========================================================
    # VALUE / CANDIDATES
    # ========================================================

    try:

        candidates = find_candidates(
            model["probabilities"],
            real_odds
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

    # Якщо find_candidates повернув
    # не відсортований список,
    # сортуємо за Value

    try:

        candidates.sort(
            key=lambda x: (
                float(
                    x.get(
                        "value",
                        -999
                    )
                )
                if isinstance(x, dict)
                else -999
            ),
            reverse=True
        )

    except Exception:

        pass

    best = (
        candidates[0]
        if candidates
        else None
    )

    model["best"] = best

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

# ============================================================
# FASTAPI WEB API
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
    return max(0.0, min(probability, 1.0))


def form_sequence(history, team_id, before_date, home_only=False, away_only=False, limit=5):
    results = calculate_form(
        history,
        team_id,
        before_date,
        home_only=home_only,
        away_only=away_only,
        limit=limit,
    )
    return [item.get("result", "") for item in results]


def serialize_scores(scores):
    output = []
    for item in scores or []:
        try:
            (home_goals, away_goals), probability = item
            output.append({
                "home": safe_int(home_goals),
                "away": safe_int(away_goals),
                "probability": probability_percent(probability),
            })
        except Exception:
            continue
    return output


def map_candidate(candidate):
    if not isinstance(candidate, dict):
        return None
    return {
        "market": candidate.get("market"),
        "selection": candidate.get("name"),
        "name": candidate.get("name"),
        "odds": candidate.get("odds"),
        "probability": probability_percent(candidate.get("probability")),
        "value": None if candidate.get("value") is None else round(safe_float(candidate.get("value")), 4),
        "confidence": round(safe_float(candidate.get("confidence")), 1),
    }


def build_web_response(result):
    home = result["home"]
    away = result["away"]
    model = result.get("model", {})
    probabilities = model.get("probabilities", {})
    real_odds = result.get("real_odds", {})

    home_xg = safe_float(model.get("home_xg"), 0.0)
    away_xg = safe_float(model.get("away_xg"), 0.0)
    total_xg = home_xg + away_xg

    before_date = datetime.now(timezone.utc).isoformat()
    home_history = HISTORY_CACHE.get(home["id"], [])
    away_history = HISTORY_CACHE.get(away["id"], [])

    home_form_stats = model.get("home_home_form", {}) or {}
    away_form_stats = model.get("away_away_form", {}) or {}
    home_halves = model.get("home_halves", {}) or {}
    away_halves = model.get("away_halves", {}) or {}
    h2h = model.get("h2h", {}) or {}

    # The V25 core exposes only O/U 2.5 directly. Extra total lines below are
    # calculated from the very same Poisson score matrix for web presentation.
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

    candidates = [
        mapped
        for mapped in (map_candidate(x) for x in model.get("candidates", []))
        if mapped is not None
    ]
    best_bet = map_candidate(model.get("best"))

    kickoff_utc = None
    kickoff_kyiv = None
    odds_event = result.get("odds_event")
    if isinstance(odds_event, dict):
        kickoff_utc = odds_event.get("commence_time")
        dt = parse_datetime_utc(kickoff_utc)
        if dt is not None:
            kickoff_kyiv = dt.astimezone(ZoneInfo("Europe/Kyiv")).isoformat()

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
        "version": "3.0.0-v25",
        "match": {
            "home_team": home.get("name"),
            "away_team": away.get("name"),
            "league": home.get("league_name"),
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
            "total": round(total_xg, 2),
        },
        "goals": {
            "over_0_5": probability_percent(over_05),
            "over_1_5": probability_percent(over_15),
            "over_2_5": probability_percent(probabilities.get("over_25")),
            "over_3_5": probability_percent(over_35),
            "under_0_5": probability_percent(1.0 - over_05),
            "under_1_5": probability_percent(1.0 - over_15),
            "under_2_5": probability_percent(probabilities.get("under_25")),
            "under_3_5": probability_percent(1.0 - over_35),
        },
        "btts": {
            "yes": probability_percent(probabilities.get("btts_yes")),
            "no": probability_percent(probabilities.get("btts_no")),
        },
        "most_likely_scores": serialize_scores(probabilities.get("most_likely_scores")),
        "form": {
            "home": form_sequence(home_history, home["id"], before_date, limit=5),
            "away": form_sequence(away_history, away["id"], before_date, limit=5),
            "home_home": {
                "matches": safe_int(home_form_stats.get("matches")),
                "wins": safe_int(home_form_stats.get("wins")),
                "draws": safe_int(home_form_stats.get("draws")),
                "losses": safe_int(home_form_stats.get("losses")),
                "goals_for_per_match": round(safe_float(home_form_stats.get("attack")), 2),
                "goals_against_per_match": round(safe_float(home_form_stats.get("defence")), 2),
                "points_per_game": round(safe_float(home_form_stats.get("points_per_game")), 2),
            },
            "away_away": {
                "matches": safe_int(away_form_stats.get("matches")),
                "wins": safe_int(away_form_stats.get("wins")),
                "draws": safe_int(away_form_stats.get("draws")),
                "losses": safe_int(away_form_stats.get("losses")),
                "goals_for_per_match": round(safe_float(away_form_stats.get("attack")), 2),
                "goals_against_per_match": round(safe_float(away_form_stats.get("defence")), 2),
                "points_per_game": round(safe_float(away_form_stats.get("points_per_game")), 2),
            },
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
            "home": home_halves,
            "away": away_halves,
        },
        "h2h": h2h,
        "corners": {
            "available": False,
            "home": None,
            "away": None,
            "total": None,
            "message": "Corners are not part of the supplied V25 model.",
        },
        "odds": odds,
        "bookmakers_count": result.get("bookmakers_count", 0),
        "betting_markets": candidates,
        "best_bet": best_bet,
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Lazy loading keeps startup fast; first /analyze call loads TOP-5 teams.
    yield
    await close_sessions()


app = FastAPI(
    title="Football AI Analyst",
    description="Football match analysis API powered by V25 model",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {
        "status": "ok",
        "app": "Football AI Analyst",
        "version": "3.0.0-v25",
        "model": "Football AI Analyst V25",
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "version": "3.0.0-v25",
        "teams_loaded": len(WEB_TEAMS),
    }


@app.post("/analyze")
async def analyze_web_match(match: MatchRequest):
    home_query = match.home_team.strip()
    away_query = match.away_team.strip()

    if not home_query or not away_query:
        raise HTTPException(status_code=400, detail="Both home_team and away_team are required")

    try:
        teams = await ensure_teams_loaded()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to load teams: {exc}") from exc

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
        return build_web_response(result)
    except HTTPException:
        raise
    except Exception as exc:
        print(f"❌ WEB ANALYZE ERROR: {repr(exc)}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}") from exc

