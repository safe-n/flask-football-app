from flask import Flask, request, jsonify, render_template, send_file
from flask_sqlalchemy import SQLAlchemy
import spacy
import pandas as pd
import os
import time
import requests
from fpdf import FPDF
from datetime import datetime
from fuzzywuzzy import fuzz, process
import openai
import io
import csv

app = Flask(__name__)

# Bezpośrednio wpisane dane dotyczące bazy danych
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql+psycopg2://baza_stats_user:wxjFNiRghDeh2JFqZE0yOZeWMNXvlaYu@dpg-cug746a3esus73enkhg0-a:5432/baza_stats'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Inne konfiguracje, jeśli są potrzebne
app.config['API_HOST'] = 'api-football-v1.p.rapidapi.com'
app.config['API_KEY'] = '40027c6adcmshfb4e864cb9e7855p12d50cjsn6eb6ef9031a6'
app.config['OPENAI_API_KEY'] = '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'  # Klucz API OpenAI

db = SQLAlchemy(app)

# Instalacja modelu spaCy
os.system('python -m spacy download en_core_web_sm')
try:
    nlp = spacy.load('en_core_web_sm')
    print("Model spaCy załadowany poprawnie.")
except Exception as e:
    print(f"Błąd podczas ładowania modelu spaCy: {e}")

# Definicja modelu bazy danych
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
    if not query:
        return "unknown_query"
    query = query.lower()
    choices = {
        "average_goals": ["average goals", "average number of goals", "średnia liczba goli", "średnia goli"],
        "average_corners": ["average corners", "corners on average", "średnia liczba rzutów rożnych", "średnia rzutów rożnych"],
        "average_yellow_cards": ["average yellow cards", "yellow cards per match", "średnia liczba żółtych kartek", "średnia żółtych kartek"],
        "average_shots": ["average shots", "shots on target", "średnia liczba strzałów", "średnia strzałów"]
    }
    
    for key, variations in choices.items():
        if any(fuzz.partial_ratio(query, variation) > 80 for variation in variations):
            return key
    
    return "unknown_query"

def generate_ai_response(prompt):
    openai.api_key = app.config['OPENAI_API_KEY']
    if not openai.api_key:
        raise ValueError("No API key provided. Set the OPENAI_API_KEY environment variable.")
    
    response = openai.Completion.create(
        engine="davinci-codex",
        prompt=prompt,
        max_tokens=150
    )
    return response.choices[0].text.strip()

def fetch_today_matches():
    url = f"https://{app.config['API_HOST']}/v3/fixtures"
    headers = {
        "X-RapidAPI-Key": app.config['API_KEY'],
        "X-RapidAPI-Host": app.config['API_HOST']
    }
    params = {
        'date': datetime.now().strftime('%Y-%m-%d'),  # Dzisiejsza data
        'league': '39,140',  # Przykład: Premier League, La Liga
        'status': 'NS'  # Nadchodzące mecze
    }
    response = requests.get(url, headers=headers, params=params)
    
    if response.status_code != 200:
        print(f"Error fetching data: {response.status_code} {response.text}")
        return []
    
    return response.json().get("response", [])

def save_match_data(match):
    existing_match = Match.query.filter_by(fixture_id=match['fixture']['id']).first()
    if existing_match:
        return existing_match
    
    new_match = Match(
        fixture_id=match['fixture']['id'],
        date=datetime.strptime(match['fixture']['date'], '%Y-%m-%dT%H:%M:%S%z').date(),
        league=match['league']['name'],
        home_team=match['teams']['home']['name'],
        away_team=match['teams']['away']['name'],
        home_goals=match['goals']['home'],
        away_goals=match['goals']['away']
    )
    db.session.add(new_match)
    db.session.commit()
    return new_match

def fetch_and_save_match_data():
    matches = fetch_today_matches()
    for match in matches:
        save_match_data(match)
    return "Today's matches fetched and saved."

def fetch_statistics_and_save(fixture_id):
    statistics = fetch_statistics(fixture_id)
    # Zapisać dane statystyczne do bazy danych
    # Funkcja ta nie jest w pełni zaimplementowana w tym przykładzie
    return "Statistics fetched and saved."

@app.route('/healthz')
def health_check():
    return "OK", 200

@app.route('/')
def index():
    matches = fetch_today_matches()
    return render_template('index.html', matches=matches)

@app.route('/query', methods=['POST'])
def query():
    user_query = request.json.get('query')
    interpreted_query = interpret_query(user_query)
    
    matches = Match.query.all()
    stats = calculate_statistics(matches)
    
    if interpreted_query == "unknown_query":
        prompt = f"User asked: {user_query}\nBased on the stored football data, provide a detailed response."
        result = generate_ai_response(prompt)
    else:
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
    result = fetch_and_save_match_data()
    return jsonify({"status": "success", "message": result})

@app.route('/update', methods=['POST'])
def update():
    update_existing_records()
    return "Data updated successfully!"

@app.route('/report', methods=['POST'])
def report():
    report_path = generate_pdf_report()
    return send_file(report_path, as_attachment=True)

@app.route('/export', methods=['GET'])
def export_csv():
    matches = Match.query.all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['fixture_id', 'date', 'league', 'home_team', 'away_team', 'home_goals', 'away_goals', 'home_shots', 'away_shots', 'home_corners', 'away_corners', 'home_yellow', 'away_yellow'])
    
    for match in matches:
        writer.writerow([match.fixture_id, match.date, match.league, match.home_team, match.away_team, match.home_goals, match.away_goals, match.home_shots, match.away_shots, match.home_corners, match.away_corners, match.home_yellow, match.away_yellow])
    
    output.seek(0)
    return send_file(output, mimetype='text/csv', download_name='matches.csv', as_attachment=True)

@app.route('/team_stats/<team_name>', methods=['GET'])
def get_team_stats(team_name):
    matches = Match.query.filter((Match.home_team == team_name) | (Match.away_team == team_name)).all()
    if not matches:
        return jsonify({"error": "Team not found"}), 404
    
    team_stats = calculate_team_statistics(matches, team_name)
    return jsonify(team_stats)

@app.route('/stats/<fixture_id>', methods=['GET'])
def get_stats(fixture_id):
    result = fetch_statistics_and_save(fixture_id)
    return jsonify({"status": "success", "message": result})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
