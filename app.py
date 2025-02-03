from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
import os
from dotenv import load_dotenv

# Załaduj zmienne środowiskowe z pliku .env
load_dotenv()

app = Flask(__name__)

# Uzyskaj wartość zmiennej środowiskowej DATABASE_URL
database_url = os.getenv('DATABASE_URL')

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# reszta twojego kodu...

# Załaduj model językowy spaCy
nlp = spacy.load('en_core_web_sm')

class Match(db.Model):
    """
    Model reprezentujący mecz piłkarski.
    """
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
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

def calculate_statistics(matches):
    """
    Funkcja do obliczania statystyk na podstawie danych meczowych.
    """
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

def interpret_query(query):
    """
    Funkcja do interpretacji zapytań użytkowników.
    """
    doc = nlp(query.lower())
    
    # Proste słowa kluczowe do interpretacji zapytań
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

@app.route('/')
def index():
    """
    Strona główna aplikacji.
    """
    return render_template('index.html')

@app.route('/matches', methods=['POST'])
def matches():
    """
    Trasa obsługująca wybór ligi i daty.
    """
    league = request.form.get('league')
    date = request.form.get('date')
    # Tu dodaj logikę do przetwarzania wybranej ligi i daty
    return f"Wybrana liga: {league}, Wybrana data: {date}"

@app.route('/api/query', methods=['POST'])
def query():
    """
    API do obsługi zapytań użytkowników.
    """
    data = request.get_json()
    query = data['query']
    interpreted_query = interpret_query(query)
    
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

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)