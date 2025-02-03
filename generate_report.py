import os
from fpdf import FPDF
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

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

if __name__ == '__main__':
    with app.app_context():
        pdf = PDF()

        # 1. Średnia liczba goli na mecz
        total_goals = 0
        total_matches = Match.query.count()
        matches = Match.query.all()
        
        for match in matches:
            total_goals += match.home_goals + match.away_goals
        
        average_goals_per_match = total_goals / total_matches if total_matches != 0 else 0
        pdf.add_chapter('Średnia liczba goli na mecz', f"{average_goals_per_match:.2f}")

        # 2. Drużyny z największą liczbą strzelonych goli
        team_goals = {}
        
        for match in matches:
            if match.home_team not in team_goals:
                team_goals[match.home_team] = 0
            if match.away_team not in team_goals:
                team_goals[match.away_team] = 0
            
            team_goals[match.home_team] += match.home_goals
            team_goals[match.away_team] += match.away_goals
        
        # Sortowanie drużyn według liczby strzelonych goli
        sorted_teams = sorted(team_goals.items(), key=lambda x: x[1], reverse=True)
        body = "\n".join([f"{team}: {goals} goli" for team, goals in sorted_teams])
        pdf.add_chapter('Drużyny z największą liczbą strzelonych goli', body)

        # 3. Średnia liczba rzutów rożnych na mecz
        total_corners = 0
        
        for match in matches:
            if match.home_corners is not None:
                total_corners += match.home_corners
            if match.away_corners is not None:
                total_corners += match.away_corners
        
        average_corners_per_match = total_corners / total_matches if total_matches != 0 else 0
        pdf.add_chapter('Średnia liczba rzutów rożnych na mecz', f"{average_corners_per_match:.2f}")

        # 4. Najlepsze i najgorsze drużyny pod względem defensywy
        team_defense = {}
        
        for match in matches:
            if match.home_team not in team_defense:
                team_defense[match.home_team] = 0
            if match.away_team not in team_defense:
                team_defense[match.away_team] = 0
            
            team_defense[match.home_team] += match.away_goals
            team_defense[match.away_team] += match.home_goals
        
        # Sortowanie drużyn według liczby straconych goli (od najmniejszej do największej)
        best_defense = sorted(team_defense.items(), key=lambda x: x[1])
        
        best_defense_body = "\n".join([f"{team}: {goals_conceded} straconych goli" for team, goals_conceded in best_defense[:5]])
        worst_defense_body = "\n".join([f"{team}: {goals_conceded} straconych goli" for team, goals_conceded in best_defense[-5:]])
        
        pdf.add_chapter('Drużyny z najlepszą defensywą', best_defense_body)
        pdf.add_chapter('Drużyny z najgorszą defensywą', worst_defense_body)

        # Zapisanie PDF
        output_path = os.path.expanduser('~\\Football_Data_Analysis_Report.pdf')
        pdf.output(output_path)
        print(f"Raport PDF został wygenerowany pomyślnie w {output_path}!")