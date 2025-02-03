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

if __name__ == '__main__':
    with app.app_context():
        # 1. Najlepsze i najgorsze drużyny pod względem defensywy
        team_defense = {}
        
        matches = Match.query.all()
        
        for match in matches:
            if match.home_team not in team_defense:
                team_defense[match.home_team] = 0
            if match.away_team not in team_defense:
                team_defense[match.away_team] = 0
            
            team_defense[match.home_team] += match.away_goals
            team_defense[match.away_team] += match.home_goals
        
        # Sortowanie drużyn według liczby straconych goli (od najmniejszej do największej)
        best_defense = sorted(team_defense.items(), key=lambda x: x[1])
        
        print("Drużyny z najlepszą defensywą:")
        for team, goals_conceded in best_defense[:5]:
            print(f"{team}: {goals_conceded} straconych goli")
        
        print("Drużyny z najgorszą defensywą:")
        for team, goals_conceded in best_defense[-5:]:
            print(f"{team}: {goals_conceded} straconych goli")
        
        # 2. Średnia liczba goli na mecz dla każdej drużyny
        team_goals = {}
        team_matches = {}
        
        for match in matches:
            if match.home_team not in team_goals:
                team_goals[match.home_team] = 0
                team_matches[match.home_team] = 0
            if match.away_team not in team_goals:
                team_goals[match.away_team] = 0
                team_matches[match.away_team] = 0
            
            team_goals[match.home_team] += match.home_goals
            team_goals[match.away_team] += match.away_goals
            team_matches[match.home_team] += 1
            team_matches[match.away_team] += 1
        
        print("Średnia liczba goli na mecz dla każdej drużyny:")
        for team in team_goals:
            avg_goals = team_goals[team] / team_matches[team]
            print(f"{team}: {avg_goals:.2f} goli na mecz")
        
        # 3. Analiza wyników w domu i na wyjeździe
        home_performance = {}
        away_performance = {}
        
        for match in matches:
            if match.home_team not in home_performance:
                home_performance[match.home_team] = {'goals': 0, 'matches': 0}
            if match.away_team not in away_performance:
                away_performance[match.away_team] = {'goals': 0, 'matches': 0}
            
            home_performance[match.home_team]['goals'] += match.home_goals
            home_performance[match.home_team]['matches'] += 1
            away_performance[match.away_team]['goals'] += match.away_goals
            away_performance[match.away_team]['matches'] += 1
        
        print("Średnia liczba goli w meczach domowych:")
        for team in home_performance:
            avg_home_goals = home_performance[team]['goals'] / home_performance[team]['matches']
            print(f"{team}: {avg_home_goals:.2f} goli na mecz domowy")
        
        print("Średnia liczba goli w meczach wyjazdowych:")
        for team in away_performance:
            avg_away_goals = away_performance[team]['goals'] / away_performance[team]['matches']
            print(f"{team}: {avg_away_goals:.2f} goli na mecz wyjazdowy")