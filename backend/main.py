import os

from dotenv import load_dotenv

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from services.odds_service import get_real_odds


load_dotenv()


app = FastAPI(
    title="Football AI Analyst",
    description="Football match analysis API",
    version="2.2.0",
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


class MatchRequest(BaseModel):
    home_team: str
    away_team: str


def calculate_value(
    probability: float,
    odd: float | None,
) -> float:

    if not odd or odd <= 1:
        return 0.0

    return round(
        (probability / 100) * odd - 1,
        3,
    )


@app.get("/")
async def root():

    return {
        "status": "ok",
        "app": "Football AI Analyst",
        "version": "2.2.0",
        "odds": "The Odds API",
    }


@app.get("/health")
async def health():

    return {
        "status": "healthy",
        "version": "2.2.0",
    }


@app.post("/analyze")
async def analyze_match(
    match: MatchRequest,
):

    home_team = match.home_team
    away_team = match.away_team

    # =====================================================
    # ТЕСТОВАЯ МОДЕЛЬ
    # =====================================================

    prediction = {
        "home": 45,
        "draw": 28,
        "away": 27,
    }

    xg = {
        "home": 1.82,
        "away": 1.14,
        "total": 2.96,
    }

    goals = {
        "over_0_5": 94,
        "under_0_5": 6,

        "over_1_5": 78,
        "under_1_5": 22,

        "over_2_5": 57,
        "under_2_5": 43,

        "over_3_5": 31,
        "under_3_5": 69,
    }

    btts = {
        "yes": 54,
        "no": 46,
    }

    corners = {
        "home": 5.7,
        "away": 4.3,
        "total": 10.0,
    }

    form = {
        "home": [
            "W",
            "W",
            "D",
            "W",
            "L",
        ],
        "away": [
            "W",
            "D",
            "L",
            "W",
            "W",
        ],
    }

    attack = {
        "home": 82,
        "away": 71,
    }

    defense = {
        "home": 76,
        "away": 68,
    }

    # =====================================================
    # РЕАЛЬНЫЕ КОЭФФИЦИЕНТЫ
    # =====================================================

    real_odds = await get_real_odds(
        home_team,
        away_team,
    )

    odds = {}

    if real_odds.get("available"):

        api_odds = real_odds.get(
            "odds",
            {},
        )

        for key, value in api_odds.items():

            if key == "bookmakers":
                continue

            if value and isinstance(value, dict):
                odds[key] = value.get("odds")

    # =====================================================
    # BETTING MARKETS
    # =====================================================

    betting_markets = []

    # -----------------------------------------------------
    # 1X
    # -----------------------------------------------------

    if odds.get("1") and odds.get("X"):

        probability_1x = (
            prediction["home"]
            + prediction["draw"]
        )

        # Для 1X используем отдельную оценку.
        probability_1x = min(
            95,
            probability_1x,
        )

        # Реального 1X рынка пока может не быть.
        # Рассчитываем синтетическую оценку только
        # если есть обе цены 1 и X.
        odd_1x = round(
            1 /
            (
                (1 / odds["1"])
                + (1 / odds["X"])
            ),
            2,
        )

        betting_markets.append(
            {
                "market": "1X",
                "selection": (
                    f"{home_team} или ничья"
                ),
                "odds": odd_1x,
                "probability": probability_1x,
                "value": calculate_value(
                    probability_1x,
                    odd_1x,
                ),
            }
        )

    # -----------------------------------------------------
    # OVER 2.5
    # -----------------------------------------------------

    if odds.get("over_2_5"):

        probability = goals["over_2_5"]

        betting_markets.append(
            {
                "market": "TOTAL",
                "selection": "ТБ 2.5",
                "odds": odds["over_2_5"],
                "probability": probability,
                "value": calculate_value(
                    probability,
                    odds["over_2_5"],
                ),
            }
        )

    # -----------------------------------------------------
    # UNDER 2.5
    # -----------------------------------------------------

    if odds.get("under_2_5"):

        probability = goals["under_2_5"]

        betting_markets.append(
            {
                "market": "TOTAL",
                "selection": "ТМ 2.5",
                "odds": odds["under_2_5"],
                "probability": probability,
                "value": calculate_value(
                    probability,
                    odds["under_2_5"],
                ),
            }
        )

    # =====================================================
    # BTTS
    # =====================================================

    # Пока BTTS не запрашиваем через основной endpoint,
    # потому что это дополнительный market.
    #
    # Добавим его отдельным модулем следующим этапом.

    # =====================================================
    # BEST BET
    # =====================================================

    if betting_markets:

        best_bet = max(
            betting_markets,
            key=lambda x: x["value"],
        )

    else:

        best_bet = {
            "market": "NONE",
            "selection": "Нет доступного value",
            "odds": None,
            "probability": 0,
            "value": 0,
        }

    confidence = round(
        min(
            95,
            max(
                50,
                best_bet["probability"] * 0.9
                + best_bet["value"] * 100 * 0.5,
            ),
        )
    )

    # =====================================================
    # AI ASSESSMENT
    # =====================================================

    if confidence >= 75:
        rating = "VERY GOOD"
        risk = "LOW"

    elif confidence >= 65:
        rating = "GOOD"
        risk = "MEDIUM"

    else:
        rating = "MODERATE"
        risk = "HIGH"

    if real_odds.get("available"):

        odds_status = (
            "Использованы реальные коэффициенты "
            "The Odds API."
        )

    else:

        odds_status = (
            "Реальные коэффициенты для этого матча "
            "не найдены."
        )

    summary = (
        f"{home_team} имеет преимущество по "
        f"тестовой модели. "
        f"{odds_status}"
    )

    return {

        "status": "success",

        "match": {
            "home_team": home_team,
            "away_team": away_team,
        },

        "prediction": prediction,

        "xg": xg,

        "goals": goals,

        "btts": btts,

        "corners": corners,

        "form": form,

        "attack": attack,

        "defense": defense,

        "odds": odds,

        "odds_info": {
            "available": real_odds.get(
                "available",
                False,
            ),
            "sport_key": real_odds.get(
                "sport_key"
            ),
            "event_id": real_odds.get(
                "event_id"
            ),
            "commence_time": real_odds.get(
                "commence_time"
            ),
            "bookmakers": (
                real_odds
                .get("odds", {})
                .get("bookmakers", [])
            ),
            "error": real_odds.get(
                "error"
            ),
        },

        "betting_markets": betting_markets,

        "best_bet": best_bet,

        "confidence": confidence,

        "ai_assessment": {
            "rating": rating,
            "risk": risk,
            "summary": summary,
        },
    }