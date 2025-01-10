<<<<<<< HEAD
from flask import Flask, render_template, request
import requests
import os
from datetime import datetime, timedelta

app = Flask(__name__)

# RapidAPI configuration
API_HOST = "api-football-v1.p.rapidapi.com"
API_KEY = "40027c6adcmshfb4e864cb9e7855p12d50cjsn6eb6ef9031a6"

# Function to fetch team statistics
def fetch_team_stats(team_id, league_id, season):
    url = f"https://{API_HOST}/v3/teams/statistics"
    headers = {
        "X-RapidAPI-Key": API_KEY,
        "X-RapidAPI-Host": API_HOST
    }
    params = {
        "team": team_id,
        "league": league_id,
        "season": season
    }
    response = requests.get(url, headers=headers, params=params)
    
    if response.status_code == 200:
        stats = response.json().get("response", {})
        return stats
    else:
        print(f"Error fetching stats for team {team_id}: {response.status_code}, {response.text}")
        return None

# Function to fetch matches for a given date
def fetch_matches(date):
    url = f"https://{API_HOST}/v3/fixtures"
    headers = {
        "X-RapidAPI-Key": API_KEY,
        "X-RapidAPI-Host": API_HOST
    }
    params = {
        "date": date,
        "league": "140",  # La Liga ID
        "season": "2024"
    }
    response = requests.get(url, headers=headers, params=params)
    
    if response.status_code == 200:
        matches = response.json()["response"]
        
        # Fetch team statistics for each match
        for match in matches:
            home_team_id = match["teams"]["home"]["id"]
            away_team_id = match["teams"]["away"]["id"]
            league_id = 140  # La Liga ID
            season = "2024"
            
            # Get team stats
            home_team_stats = fetch_team_stats(home_team_id, league_id, season)
            away_team_stats = fetch_team_stats(away_team_id, league_id, season)
            
            # Add stats to match
            match["home_team_stats"] = {
                "position": home_team_stats.get("league", {}).get("position", "N/A"),
                "matches_played": home_team_stats.get("fixtures", {}).get("played", {}).get("total", "N/A"),
                "goals_scored": home_team_stats.get("goals", {}).get("for", {}).get("total", {}).get("total", "N/A")
            } if home_team_stats else None
            
            match["away_team_stats"] = {
                "position": away_team_stats.get("league", {}).get("position", "N/A"),
                "matches_played": away_team_stats.get("fixtures", {}).get("played", {}).get("total", "N/A"),
                "goals_scored": away_team_stats.get("goals", {}).get("for", {}).get("total", {}).get("total", "N/A")
            } if away_team_stats else None
        
        return matches
    else:
        print(f"Error fetching matches: {response.status_code}, {response.text}")
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
=======
from flask import Flask, render_template, request
import requests
import os
from datetime import datetime, timedelta

app = Flask(__name__)

# RapidAPI configuration
API_HOST = "api-football-v1.p.rapidapi.com"
API_KEY = "40027c6adcmshfb4e864cb9e7855p12d50cjsn6eb6ef9031a6"  # Replace this with your API key

# Function to fetch team statistics
def fetch_team_stats(team_id, league_id, season):
    url = f"https://{API_HOST}/v3/teams/statistics"
    headers = {
        "X-RapidAPI-Key": API_KEY,
        "X-RapidAPI-Host": API_HOST
    }
    params = {
        "team": team_id,
        "league": league_id,
        "season": season
    }
    response = requests.get(url, headers=headers, params=params)
    
    if response.status_code == 200:
        stats = response.json().get("response", {})
        return stats
    else:
        print(f"Error fetching stats for team {team_id}: {response.status_code}, {response.text}")
        return None

# Function to fetch matches for a given date
def fetch_matches(date):
    url = f"https://{API_HOST}/v3/fixtures"
    headers = {
        "X-RapidAPI-Key": API_KEY,
        "X-RapidAPI-Host": API_HOST
    }
    params = {
        "date": date,
        "league": "140",  # La Liga ID
        "season": "2024"
    }
    response = requests.get(url, headers=headers, params=params)
    
    if response.status_code == 200:
        matches = response.json()["response"]
        
        # Fetch team statistics for each match
        for match in matches:
            home_team_id = match["teams"]["home"]["id"]
            away_team_id = match["teams"]["away"]["id"]
            league_id = 140  # La Liga ID
            season = "2024"
            
            # Get team stats
            home_team_stats = fetch_team_stats(home_team_id, league_id, season)
            away_team_stats = fetch_team_stats(away_team_id, league_id, season)
            
            # Add stats to match
            match["home_team_stats"] = {
                "position": home_team_stats.get("league", {}).get("position", "N/A"),
                "matches_played": home_team_stats.get("fixtures", {}).get("played", {}).get("total", "N/A"),
                "goals_scored": home_team_stats.get("goals", {}).get("for", {}).get("total", {}).get("total", "N/A")
            } if home_team_stats else None
            
            match["away_team_stats"] = {
                "position": away_team_stats.get("league", {}).get("position", "N/A"),
                "matches_played": away_team_stats.get("fixtures", {}).get("played", {}).get("total", "N/A"),
                "goals_scored": away_team_stats.get("goals", {}).get("for", {}).get("total", {}).get("total", "N/A")
            } if away_team_stats else None
        
        return matches
    else:
        print(f"Error fetching matches: {response.status_code}, {response.text}")
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
>>>>>>> f93745f4271f686cd9fbede01aee17cfdf0d19e1
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))