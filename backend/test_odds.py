import os
import asyncio
import aiohttp
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("ODDS_API_KEY")

URL = "https://api.the-odds-api.com/v4/sports/soccer_italy_serie_a/events"


async def main():

    params = {
        "apiKey": API_KEY,
        "dateFormat": "iso",
    }

    async with aiohttp.ClientSession() as session:

        print("REQUEST:")
        print(URL)
        print()

        async with session.get(
            URL,
            params=params,
            timeout=20,
        ) as response:

            print("HTTP:", response.status)
            print()

            data = await response.json()

            if not isinstance(data, list):

                print(data)
                return

            print(
                "EVENTS:",
                len(data)
            )

            print()

            for event in data:

                print(
                    event.get("commence_time"),
                    "|",
                    event.get("home_team"),
                    "—",
                    event.get("away_team"),
                )


asyncio.run(main())