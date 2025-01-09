from flask import Flask, render_template, request
import requests
from datetime import datetime

app = Flask(__name__)

# Funkcja pomocnicza do pobrania danych z API
def fetch_matches(league_id, season, date=None, status="FT"):
    url = "https://api-football-v1.p.rapidapi.com/v3/fixtures"
    querystring = {
    "league": league_id,
    "season": season,
    "status": status
    }
    if date:  # Dodaj datę, jeśli została podana
        querystring["date"] = date

    headers = {
        "X-RapidAPI-Key": "40027c6adcmshfb4e864cb9e7855p12d50cjsn6eb6ef9031a6",
        "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
    }

    response = requests.get(url, headers=headers, params=querystring)

    if response.status_code == 200:
        return response.json().get('response', [])
    else:
        print(f"Błąd: {response.status_code}, {response.text}")
    return []

@app.route('/')
def index():
    test_data = [
        {
            "fixture": {"date": "2025-01-09T20:00:00Z"},
            "teams": {"home": {"name": "Team A"}, "away": {"name": "Team B"}},
            "goals": {"home": 2, "away": 1}
        },
        {
            "fixture": {"date": "2025-01-09T18:00:00Z"},
            "teams": {"home": {"name": "Team C"}, "away": {"name": "Team D"}},
            "goals": {"home": 0, "away": 0}
        }
    ]

    return render_template('index.html', daily_matches=test_data, season_matches=test_data)


if __name__ == '__main__':
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT",10000)))