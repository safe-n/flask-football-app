import requests
import time
from datetime import datetime
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import os
from dotenv import load_dotenv

app = Flask(__name__)

# Uzyskaj ścieżkę absolutną do pliku bazy danych w głównym folderze
basedir = os.path.abspath(os.path.dirname(__file__))
database_path = os.path.join(basedir, 'matches.db')

app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{database_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class Match(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fixture_id = db.Column(db.Integer, unique=True, nullable=False)
    date = db.Column(db.Date, nullable=False)
    league = db.Column(db.String(50), nullable=False)
    home_team = db.Column(db.String(50), nullable=False)
    away_team = db.Column(db.String(50), nullable=False)
    home_goals = db.Column(db.Integer)
    away_goals = db.Column(db.Integer)
    home_shots = db.Column(db.Integer)
    away_shots = db.Column(db.Integer)
    home_corners = db.Column(db.Integer)
    away_corners = db.Column(db.Integer)
    home_yellow = db.Column(db.Integer)
    away_yellow = db.Column(db.Integer)

# Ładowanie zmiennych środowiskowych z pliku .env w lokalnym środowisku
load_dotenv()

# Pobieranie zmiennych środowiskowych
DATABASE_URL = os.getenv('DATABASE_URL')
API_KEY = os.getenv('API_KEY')
API_HOST = os.getenv('API_HOST')

def fetch_statistics(fixture_id):
    url = f"https://{API_HOST}/v3/fixtures/statistics"
    headers = {
        "X-RapidAPI-Key": API_KEY,
        "X-RapidAPI-Host": API_HOST
    }
    params = {
        'fixture': fixture_id
    }
    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 429:
        print(f"Rate limit exceeded for fixture {fixture_id}. Retrying after delay...")
        time.sleep(60)  # Opóźnienie 60 sekund przed ponowną próbą
        response = requests.get(url, headers=headers, params=params)
    return response.json().get("response", [])

def fetch_and_save_data():
    url = f"https://{API_HOST}/v3/fixtures"
    headers = {
        "X-RapidAPI-Key": API_KEY,
        "X-RapidAPI-Host": API_HOST
    }
    params = {
        'league': '39',  # Przykład: Premier League
        'season': '2024',  # Przykład: sezon 2024/25
        'status': 'FT'  # Tylko zakończone mecze
    }
    response = requests.get(url, headers=headers, params=params)
    data = response.json().get("response", [])
    
    max_requests = 50  # Maksymalna liczba zapytań do API
    request_count = 0
    
    for match in data:
        if request_count >= max_requests:
            print("Reached maximum number of API requests.")
            break
        
        fixture_id = match['fixture']['id']
        statistics = fetch_statistics(fixture_id)
        
        # Pobieramy statystyki, jeśli są dostępne
        home_shots = away_shots = home_corners = away_corners = home_yellow = away_yellow = None
        
        for team_stats in statistics:
            team_id = team_stats['team']['id']
            stats = {stat['type']: stat['value'] for stat in team_stats['statistics']}
            if team_id == match['teams']['home']['id']:
                home_shots = stats.get('Shots on Goal')
                home_corners = stats.get('Corner Kicks')
                home_yellow = stats.get('Yellow Cards')
            elif team_id == match['teams']['away']['id']:
                away_shots = stats.get('Shots on Goal')
                away_corners = stats.get('Corner Kicks')
                away_yellow = stats.get('Yellow Cards')

        # Debugowanie - wyświetlanie statystyk
        print(f"Fixture ID: {fixture_id}")
        print(f"Home Shots: {home_shots}, Away Shots: {away_shots}")
        print(f"Home Corners: {home_corners}, Away Corners: {away_corners}")
        print(f"Home Yellow Cards: {home_yellow}, Away Yellow Cards: {away_yellow}")
        print("------")
        
        # Sprawdź, czy mecz już istnieje w bazie danych
        existing_match = Match.query.filter_by(fixture_id=fixture_id).first()
        if existing_match:
            # Aktualizuj istniejący rekord
            existing_match.home_shots = home_shots
            existing_match.away_shots = away_shots
            existing_match.home_corners = home_corners
            existing_match.away_corners = away_corners
            existing_match.home_yellow = home_yellow
            existing_match.away_yellow = away_yellow
        else:
            # Dodaj nowy rekord
            new_match = Match(
                fixture_id=fixture_id,
                date=datetime.strptime(match['fixture']['date'], '%Y-%m-%dT%H:%M:%S%z').date(),
                league=match['league']['name'],
                home_team=match['teams']['home']['name'],
                away_team=match['teams']['away']['name'],
                home_goals=match['goals']['home'],
                away_goals=match['goals']['away'],
                home_shots=home_shots,
                away_shots=away_shots,
                home_corners=home_corners,
                away_corners=away_corners,
                home_yellow=home_yellow,
                away_yellow=away_yellow
            )
            db.session.add(new_match)
        
        request_count += 1
        time.sleep(2)  # Opóźnienie 2 sekund między zapytaniami, aby uniknąć przekroczenia limitu
    
    db.session.commit()

if __name__ == '__main__':
    with app.app_context():
        fetch_and_save_data()
        print("Data fetched and saved successfully!")
