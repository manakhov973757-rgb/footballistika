import os
import asyncio
import aiohttp


ODDS_API_URL = "https://api.the-odds-api.com/v4"


SPORT_KEYS = [
    "soccer_italy_serie_a",
    "soccer_uefa_champs_league",
    "soccer_uefa_europa_league",
    "soccer_uefa_europa_conference_league",
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_germany_bundesliga",
    "soccer_france_ligue_one",
    "soccer_netherlands_eredivisie",
    "soccer_portugal_primeira_liga",
    "soccer_turkey_super_league",
]


# =========================================================
# КОМАНДНЫЕ АЛИАСЫ
# =========================================================

TEAM_ALIASES = {

    "juventus fc": [
        "Juventus",
        "Juventus FC",
        "Juventus Turin",
    ],

    "juventus": [
        "Juventus",
        "Juventus FC",
        "Juventus Turin",
    ],

    "fc juventus": [
        "Juventus",
        "Juventus FC",
        "Juventus Turin",
    ],

    "ac milan": [
        "AC Milan",
        "Milan",
        "Milan FC",
    ],

    "milan": [
        "AC Milan",
        "Milan",
        "Milan FC",
    ],

    "fc internazionale milano": [
        "Inter Milan",
        "Inter",
        "Internazionale",
        "FC Internazionale Milano",
    ],

    "internazionale": [
        "Inter Milan",
        "Inter",
        "Internazionale",
        "FC Internazionale Milano",
    ],

    "inter milan": [
        "Inter Milan",
        "Inter",
        "Internazionale",
        "FC Internazionale Milano",
    ],

    "inter": [
        "Inter Milan",
        "Inter",
        "Internazionale",
        "FC Internazionale Milano",
    ],

    "udinese calcio": [
        "Udinese",
        "Udinese Calcio",
    ],

    "udinese": [
        "Udinese",
        "Udinese Calcio",
    ],

    "as roma": [
        "AS Roma",
        "Roma",
        "AS Roma FC",
    ],

    "roma": [
        "AS Roma",
        "Roma",
        "AS Roma FC",
    ],

    "como": [
        "Como",
        "Como 1907",
        "Como FC",
    ],

    "parma": [
        "Parma",
        "Parma Calcio",
    ],

    "torino": [
        "Torino",
        "Torino FC",
    ],

    "atalanta": [
        "Atalanta BC",
        "Atalanta",
        "Atalanta Bergamo",
    ],

    "atalanta bc": [
        "Atalanta BC",
        "Atalanta",
        "Atalanta Bergamo",
    ],

    "lecce": [
        "Lecce",
        "US Lecce",
    ],

    "napoli": [
        "Napoli",
        "SSC Napoli",
    ],

    "fiorentina": [
        "Fiorentina",
        "ACF Fiorentina",
    ],

    "lazio": [
        "Lazio",
        "SS Lazio",
    ],

    "bologna": [
        "Bologna",
        "Bologna FC",
    ],

    "cagliari": [
        "Cagliari",
        "Cagliari Calcio",
    ],

    "genoa": [
        "Genoa",
        "Genoa CFC",
    ],

    "sassuolo": [
        "Sassuolo",
        "US Sassuolo",
    ],

    "monza": [
        "Monza",
        "AC Monza",
    ],
}


# =========================================================
# НОРМАЛИЗАЦИЯ
# =========================================================

def normalize_team(name: str) -> str:

    return (
        name.lower()
        .replace("ё", "е")
        .replace("-", " ")
        .replace("_", " ")
        .replace(".", "")
        .replace(",", "")
        .strip()
    )


def team_matches(
    api_name: str,
    requested_name: str,
) -> bool:

    api_normalized = normalize_team(
        api_name
    )

    requested_normalized = normalize_team(
        requested_name
    )

    # Прямое совпадение
    if api_normalized == requested_normalized:
        return True

    # Проверяем алиасы
    aliases = TEAM_ALIASES.get(
        requested_normalized,
        [],
    )

    for alias in aliases:

        if (
            normalize_team(alias)
            == api_normalized
        ):
            return True

    # Дополнительное частичное совпадение
    if (
        requested_normalized
        in api_normalized
    ):
        return True

    if (
        api_normalized
        in requested_normalized
    ):
        return True

    return False


# =========================================================
# HTTP
# =========================================================

async def fetch_json(
    session,
    url,
    params,
):

    try:

        async with session.get(
            url,
            params=params,
            timeout=aiohttp.ClientTimeout(
                total=20
            ),
        ) as response:

            if response.status != 200:

                text = await response.text()

                print(
                    f"⚠️ Odds API HTTP "
                    f"{response.status}: "
                    f"{text[:500]}"
                )

                return None

            return await response.json()

    except asyncio.TimeoutError:

        print(
            "⚠️ Odds API timeout"
        )

        return None

    except Exception as e:

        print(
            f"⚠️ Odds API error: {e}"
        )

        return None


# =========================================================
# ПОИСК СОБЫТИЯ
# =========================================================

async def find_event(
    session,
    api_key,
    sport_key,
    home_team,
    away_team,
):

    url = (
        f"{ODDS_API_URL}/sports/"
        f"{sport_key}/events"
    )

    params = {
        "apiKey": api_key,
        "dateFormat": "iso",
    }

    print(
        f"🔎 Events → {sport_key}"
    )

    data = await fetch_json(
        session,
        url,
        params,
    )

    if not data:
        return None

    if not isinstance(data, list):
        return None

    for event in data:

        event_home = event.get(
            "home_team",
            "",
        )

        event_away = event.get(
            "away_team",
            "",
        )

        home_match = team_matches(
            event_home,
            home_team,
        )

        away_match = team_matches(
            event_away,
            away_team,
        )

        if home_match and away_match:

            print(
                f"✅ EVENT FOUND: "
                f"{event_home} — "
                f"{event_away}"
            )

            print(
                f"   Event ID: "
                f"{event.get('id')}"
            )

            print(
                f"   Start: "
                f"{event.get('commence_time')}"
            )

            return event

    return None


# =========================================================
# ПОЛУЧЕНИЕ ODDS
# =========================================================

async def get_event_odds(
    session,
    api_key,
    sport_key,
    event_id,
):

    url = (
        f"{ODDS_API_URL}/sports/"
        f"{sport_key}/events/"
        f"{event_id}/odds"
    )

    params = {
        "apiKey": api_key,
        "regions": "eu",
        "markets": "h2h,totals",
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    }

    print(
        f"💰 Получаем odds → "
        f"{event_id}"
    )

    data = await fetch_json(
        session,
        url,
        params,
    )

    if not data:
        return None

    return data


# =========================================================
# ИЗВЛЕЧЕНИЕ КОЭФФИЦИЕНТОВ
# =========================================================

def extract_odds(event):

    result = {
        "1": None,
        "X": None,
        "2": None,

        "over_1_5": None,
        "under_1_5": None,

        "over_2_5": None,
        "under_2_5": None,

        "over_3_5": None,
        "under_3_5": None,

        "bookmakers": [],
    }

    bookmakers = event.get(
        "bookmakers",
        [],
    )

    for bookmaker in bookmakers:

        bookmaker_name = bookmaker.get(
            "title",
            "Unknown",
        )

        if (
            bookmaker_name
            not in result["bookmakers"]
        ):

            result[
                "bookmakers"
            ].append(
                bookmaker_name
            )

        for market in bookmaker.get(
            "markets",
            [],
        ):

            market_key = market.get(
                "key"
            )

            for outcome in market.get(
                "outcomes",
                [],
            ):

                name = outcome.get(
                    "name"
                )

                price = outcome.get(
                    "price"
                )

                if price is None:
                    continue

                try:

                    price = float(
                        price
                    )

                except (
                    TypeError,
                    ValueError,
                ):

                    continue

                key = None

                # -------------------------
                # 1X2
                # -------------------------

                if market_key == "h2h":

                    if (
                        name
                        == event.get(
                            "home_team"
                        )
                    ):

                        key = "1"

                    elif (
                        name
                        == event.get(
                            "away_team"
                        )
                    ):

                        key = "2"

                    elif (
                        name
                        and name.lower()
                        == "draw"
                    ):

                        key = "X"

                # -------------------------
                # TOTALS
                # -------------------------

                elif (
                    market_key
                    == "totals"
                ):

                    point = outcome.get(
                        "point"
                    )

                    if point is None:
                        continue

                    try:

                        point = float(
                            point
                        )

                    except (
                        TypeError,
                        ValueError,
                    ):

                        continue

                    if (
                        name == "Over"
                        and point == 1.5
                    ):

                        key = "over_1_5"

                    elif (
                        name == "Under"
                        and point == 1.5
                    ):

                        key = "under_1_5"

                    elif (
                        name == "Over"
                        and point == 2.5
                    ):

                        key = "over_2_5"

                    elif (
                        name == "Under"
                        and point == 2.5
                    ):

                        key = "under_2_5"

                    elif (
                        name == "Over"
                        and point == 3.5
                    ):

                        key = "over_3_5"

                    elif (
                        name == "Under"
                        and point == 3.5
                    ):

                        key = "under_3_5"

                if key:

                    current = result.get(
                        key
                    )

                    if (
                        current is None
                        or price
                        > current["odds"]
                    ):

                        result[key] = {
                            "odds": price,
                            "bookmaker": (
                                bookmaker_name
                            ),
                        }

    return result


# =========================================================
# ОСНОВНАЯ ФУНКЦИЯ
# =========================================================

async def get_real_odds(
    home_team,
    away_team,
):

    api_key = os.getenv(
        "ODDS_API_KEY"
    )

    if not api_key:

        return {
            "available": False,
            "error": (
                "ODDS_API_KEY "
                "не найден"
            ),
        }

    headers = {
        "Accept": "application/json",
        "User-Agent": (
            "Football-AI-Analyst/2.2"
        ),
    }

    async with aiohttp.ClientSession(
        headers=headers
    ) as session:

        event = None
        found_sport = None

        # =================================================
        # ИЩЕМ СОБЫТИЕ
        # =================================================

        for sport_key in SPORT_KEYS:

            event = await find_event(
                session,
                api_key,
                sport_key,
                home_team,
                away_team,
            )

            if event:

                found_sport = sport_key
                break

        if not event:

            print(
                f"⚠️ Матч не найден "
                f"через Events API: "
                f"{home_team} — "
                f"{away_team}"
            )

            return {
                "available": False,
                "error": (
                    "Событие не найдено"
                ),
            }

        # =================================================
        # EVENT ID
        # =================================================

        event_id = event.get(
            "id"
        )

        # =================================================
        # ПОЛУЧАЕМ ODDS
        # =================================================

        odds_event = (
            await get_event_odds(
                session,
                api_key,
                found_sport,
                event_id,
            )
        )

        if not odds_event:

            return {
                "available": False,
                "event_found": True,
                "sport_key": found_sport,
                "event_id": event_id,
                "home_team": event.get(
                    "home_team"
                ),
                "away_team": event.get(
                    "away_team"
                ),
                "commence_time": event.get(
                    "commence_time"
                ),
                "error": (
                    "Событие найдено, "
                    "но odds "
                    "не получены"
                ),
            }

        # =================================================
        # EXTRACT
        # =================================================

        extracted = extract_odds(
            odds_event
        )

        print(
            "✅ REAL ODDS RECEIVED"
        )

        for key, value in extracted.items():

            if (
                key != "bookmakers"
                and value
            ):

                print(
                    f"   {key}: "
                    f"{value['odds']} "
                    f"({value['bookmaker']})"
                )

        return {

            "available": True,

            "event_found": True,

            "sport_key": found_sport,

            "event_id": event_id,

            "home_team": event.get(
                "home_team"
            ),

            "away_team": event.get(
                "away_team"
            ),

            "commence_time": event.get(
                "commence_time"
            ),

            "odds": extracted,

        }