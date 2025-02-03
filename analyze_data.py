import pandas as pd
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

if __name__ == '__main__':
    with app.app_context():
        matches = Match.query.all()
        stats = calculate_statistics(matches)
        print(stats)