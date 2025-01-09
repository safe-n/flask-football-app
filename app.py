from flask import Flask, render_template, request
import requests
import pandas as pd
import os
from datetime import datetime, timedelta

app = Flask(__name__)

# RapidAPI configuration
API_HOST = "api-football-v1.p.rapidapi.com"
API_KEY = "your_api_key"  # Replace this with your API key

# Function to fetch matches for a given date
def fetch_match_statistics(fixture_id):
    url = f"https://{API_HOST}/v3/fixtures/statistics"
    headers = {
        "X-RapidAPI-Key": "40027c6adcmshfb4e864cb9e7855p12d50cjsn6eb6ef9031a6",
        "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
    }
    params = {"fixture": fixture_id}
    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        return response.json()["response"]
    else:
        print(f"Error fetching stats for fixture {fixture_id}: {response.status_code}, {response.text}")
        return None

def fetch_matches(date):
    url = f"https://{API_HOST}/v3/fixtures"
    headers = {
        "X-RapidAPI-Key": "40027c6adcmshfb4e864cb9e7855p12d50cjsn6eb6ef9031a6",
        "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
    }
    params = {
        "date": date,
        "league": "140",  # La Liga ID
        "season": "2024"
    }
    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        matches = response.json()["response"]
        # Fetch statistics for each match
        for match in matches:
            fixture_id = match["fixture"]["id"]
            stats = fetch_match_statistics(fixture_id)
            match["statistics"] = stats
        return matches
    else:
        print(f"Error: {response.status_code}, {response.text}")
        return []

@app.route("/", methods=["GET", "POST"])
def home():
    matches = []
    selected_date = None

    if request.method == "POST":
        option = request.form.get("date_option")
        if option == "today":
            selected_date = datetime.now().strftime("%Y-%m-%d")
        elif option == "tomorrow":
            selected_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        elif option == "specific":
            selected_date = request.form.get("specific_date")

        if selected_date:
            matches = fetch_matches(selected_date)

    return render_template("index.html", matches=matches, selected_date=selected_date)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
