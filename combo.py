"""Jedna usługa Render, dwie aplikacje: piłka pod „/”, tenis pod „/tennis”.

Użycie (w repo football): skopiuj obok folderu fbpred/ folder tnpred/ i ten plik, dopisz `openpyxl>=3.1` do requirements.txt,
a w Render -> Settings -> Start Command wpisz:
    gunicorn combo:app --workers 1 --threads 4 --timeout 120
UptimeRobot dalej pinguje /healthz (piłka) - to wystarcza, by cała usługa (z tenisem) nie zasypiała.
"""
import os

from werkzeug.middleware.dispatcher import DispatcherMiddleware

os.environ.setdefault("TN_FOOTBALL_LINK", "/")    # link „⚽ Piłka” w menu tenisa

from fbpred.web import app  # noqa: E402  - aplikacja football (bez zmian)
from tnpred.web import create_app as _tennis  # noqa: E402

tennis = _tennis()
app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {"/tennis": tennis})
