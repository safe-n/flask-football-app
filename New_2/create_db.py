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
        db.create_all()
        print(f"Database and table created successfully at {database_path}!")