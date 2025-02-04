from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
import spacy
import pandas as pd
import os
import time
import requests
from fpdf import FPDF
from datetime import datetime
from dotenv import load_dotenv

app = Flask(__name__)

# Bezpośrednio wpisane dane dotyczące bazy danych
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql+psycopg2://baza_stats_user:wxjFNiRghDeh2JFqZE0yOZeWMNXvlaYud@dpg-cug746a3esus73enkhg0-a:5432/baza_stats'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Inne konfiguracje, jeśli są potrzebne
app.config['API_HOST'] = 'api-football-v1.p.rapidapi.com'
app.config['API_KEY'] = '40027c6adcmshfb4e864cb9e7855p12d50cjsn6eb6ef9031a6'

db = SQLAlchemy(app)

# Załaduj model językowy spaCy
nlp = spacy.load('en_core_web_sm')

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

def interpret_query(query):
    doc = nlp(query.lower())
    if "average goals" in query or "average number of goals" in query:
        return "average_goals"
    elif "average corners" in query or "corners on average" in query:
        return "average_corners"
    elif "average yellow cards" in query or "yellow cards per match" in query:
        return "average_yellow_cards"
    elif "average shots" in query or "shots on target" in query:
        return "average_shots"
    else:
        return "unknown_query"

def calculate_statistics(matches):
    df = pd.DataFrame([{
        'date': match.date,
        'home_team': match.home_team,
        'away_team': match.away_team,
        'home_goals': match.home_goals,
        'away_goals': match.away_goals,
        'home_shots': match.home_shots,
        'away_shots': match.away_shots,
        'home_corners': match.home_corners,
        'away_corners': match.away_corners,
        'home_yellow': match.home_yellow,
        'away_yellow': match.away_yellow
    } for match in matches])

    stats = {
        'goals_scored_avg': df['home_goals'].mean(),
        'goals_conceded_avg': df['away_goals'].mean(),
        'shots_off_target_avg': df['home_shots'].mean(),
        'shots_on_target_avg': df['away_shots'].mean(),
        'corners_avg': df['home_corners'].mean(),
        'cards_avg': df['home_yellow'].mean(),
        'matches_won': len(df[df['home_goals'] > df['away_goals']]),
        'both_teams_scored': len(df[(df['home_goals'] > 0) & (df['away_goals'] > 0)]),
        'over_1_5_goals': len(df[(df['home_goals'] + df['away_goals']) > 1.5]),
        'over_2_5_goals': len(df[(df['home_goals'] + df['away_goals']) > 2.5]),
        'form': 'WWDLD'  # Przykładowa forma drużyny
    }
    return stats

def fetch_statistics(fixture_id):
    url = f"https://{app.config['API_HOST']}/v3/fixtures/statistics"
    headers = {
        "X-RapidAPI-Key": app.config['API_KEY'],
        "X-RapidAPI-Host": app.config['API_HOST']
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
    url = f"https://{app.config['API_HOST']}/v3/fixtures"
    headers = {
        "X-RapidAPI-Key": app.config['API_KEY'],
        "X-RapidAPI-Host": app.config['API_HOST']
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
        
        existing_match = Match.query.filter_by(fixture_id=fixture_id).first()
        if existing_match:
            existing_match.home_shots = home_shots
            existing_match.away_shots = away_shots
            existing_match.home_corners = home_corners
            existing_match.away_corners = away_corners
            existing_match.home_yellow = home_yellow
            existing_match.away_yellow = away_yellow
        else:
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
        time.sleep(2)
    
    db.session.commit()

def update_existing_records():
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

        match.home_shots = home_shots
        match.away_shots = away_shots
        match.home_corners = home_corners
        match.away_corners = away_corners
        match.home_yellow = home_yellow
        match.away_yellow = away_yellow

        print(f"Updated fixture {fixture_id}: Home Shots: {home_shots}, Away Shots: {away_shots}, Home Corners: {home_corners}, Away Corners: {away_corners}, Home Yellow Cards: {home_yellow}, Away Yellow Cards: {away_yellow}")
        
        db.session.commit()
        time.sleep(2)

class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, 'Football Data Analysis Report', 0, 1, 'C')
        self.ln(10)

    def chapter_title(self, title):
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, title.encode('latin-1', 'replace').decode('latin-1'), 0, 1)
        self.ln(5)

    def chapter_body(self, body):
        self.set_font('Arial', '', 12)
        self.multi_cell(0, 10, body.encode('latin-1', 'replace').decode('latin-1'))
        self.ln()

    def add_chapter(self, title, body):
        self.add_page()
        self.chapter_title(title)
        self.chapter_body(body)

def generate_pdf_report():
    with app.app_context():
        pdf = PDF()

        total_goals = 0
        total_matches = Match.query.count()
        matches = Match.query.all()
        
        for match in matches:
            total_goals += match.home_goals + match.away_goals
        
        average_goals_per_match = total_goals / total_matches if total_matches != 0 else 0
        pdf.add_chapter('Średnia liczba goli na mecz', f"{average_goals_per_match:.2f}")

        team_goals = {}
        
        for match in matches:
            if match.home_team not in team_goals:
                team_goals[match.home_team] = 0
            if match.away_team not in team_goals:
                team_goals[match.away_team] = 0
            
            team_goals[match.home_team] += match.home_goals
            team_goals[match.away_team] += match.away_goals
        
        sorted_teams = sorted(team_goals.items(), key=lambda x: x[1], reverse=True)
        body = "\n".join([f"{team}: {goals} goli" for team, goals in sorted_teams])
        pdf.add_chapter('Drużyny z największą liczbą strzelonych goli', body)

        total_corners = 0
        
        for match in matches:
            if match.home_corners is not None:
                total_corners += match.home_corners
            if match.away_corners is not None:
                total_corners += match.away_corners
        
        average_corners_per_match = total_corners / total_matches if total_matches != 0 else 0
        pdf.add_chapter('Średnia liczba rzutów rożnych na mecz', f"{average_corners_per_match:.2f}")

        team_defense = {}
        
        for match in matches:
            if match.home_team not in team_defense:
                team_defense[match.home_team] = 0
            if match.away_team not in team_defense:
                team_defense[match.away_team] = 0
            
            team_defense[match.home_team] += match.away_goals
            team_defense[match.away_team] += match.home_goals
        
        best_defense = sorted(team_defense.items(), key=lambda x: x[1])
        
        best_defense_body = "\n".join([f"{team}: {goals_conceded} straconych goli" for team, goals_conceded in best_defense[:5]])
        worst_defense_body = "\n".join([f"{team}: {goals_conceded} straconych goli" for team, goals_conceded in best_defense[-5:]])
        
        pdf.add_chapter('Drużyny z najlepszą defensywą', best_defense_body)
        pdf.add_chapter('Drużyny z najgorszą defensywą', worst_defense_body)

        output_path = os.path.join(basedir, 'Football_Data_Analysis_Report.pdf')
        pdf.output(output_path)
        print(f"Raport PDF został wygenerowany pomyślnie w {output_path}!")

@app.route('/')
def index():
    matches = Match.query.all()
    return render_template('index.html', matches=matches)

@app.route('/query', methods=['POST'])
def query():
    user_query = request.form.get('query')
    interpreted_query = interpret_query(user_query)
    
    matches = Match.query.all()
    stats = calculate_statistics(matches)
    
    if interpreted_query == "average_goals":
        result = {'average_goals': stats['goals_scored_avg']}
    elif interpreted_query == "average_corners":
        result = {'average_corners': stats['corners_avg']}
    elif interpreted_query == "average_yellow_cards":
        result = {'average_yellow_cards': stats['cards_avg']}
    elif interpreted_query == "average_shots":
        result = {'average_shots': stats['shots_on_target_avg']}
    else:
        result = {'error': 'Query not understood'}
    
    return jsonify(result)

@app.route('/fetch', methods=['POST'])
def fetch():
    fetch_and_save_data()
    return "Data fetched and saved successfully!"

@app.route('/update', methods=['POST'])
def update():
    update_existing_records()
    return "Data updated successfully!"

@app.route('/report', methods=['POST'])
def report():
    generate_pdf_report()
    return "PDF report generated successfully!"

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
