import requests
import time
from datetime import datetime
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import os

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

API_KEY = '40027c6adcmshfb4e864cb9e7855p12d50cjsn6eb6ef9031a6'
API_HOST = 'api-football-v1.p.rapidapi.com'

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

def update_existing_records():
    # Pobierz wszystkie mecze z brakującymi statystykami
    matches = Match.query.filter(
        (Match.home_shots == None) | 
        (Match.away_shots == None) | 
        (Match.home_corners == None) | 
        (Match.away_corners == None) | 
        (Match.home_yellow == None) | 
        (Match.away_yellow == None)
    ).all()
    
    for match in matches:
        fixture_id = match.fixture_id
        statistics = fetch_statistics(fixture_id)
        
        home_shots = away_shots = home_corners = away_corners = home_yellow = away_yellow = None
        
        for team_stats in statistics:
            team_id = team_stats['team']['id']
            stats = {stat['type']: stat['value'] for stat in team_stats['statistics']}
            if match.home_team in stats['team']['name']:
                home_shots = stats.get('Shots on Goal')
                home_corners = stats.get('Corner Kicks')
                home_yellow = stats.get('Yellow Cards')
            elif match.away_team in stats['team']['name']:
                away_shots = stats.get('Shots on Goal')
                away_corners = stats.get('Corner Kicks')
                away_yellow = stats.get('Yellow Cards')

        # Aktualizuj rekord z brakującymi statystykami
        match.home_shots = home_shots
        match.away_shots = away_shots
        match.home_corners = home_corners
        match.away_corners = away_corners
        match.home_yellow = home_yellow
        match.away_yellow = away_yellow

        print(f"Updated fixture {fixture_id}: Home Shots: {home_shots}, Away Shots: {away_shots}, Home Corners: {home_corners}, Away Corners: {away_corners}, Home Yellow Cards: {home_yellow}, Away Yellow Cards: {away_yellow}")
        
        db.session.commit()
        time.sleep(2)  # Opóźnienie 2 sekund między zapytaniami, aby uniknąć przekroczenia limitu

if __name__ == '__main__':
    with app.app_context():
        update_existing_records()
        print("Data updated successfully!")