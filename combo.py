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


@app.before_request
def _tennis_background():
    # UptimeRobot pinguje /healthz piłki - przy okazji upewniamy się, że tenis ma działający wątek tła w tym procesie
    tennis.config["TN_ENSURE_BG"]()


# --- Kopia lokalna (PC): przycisk „Aktualizuj i zrestartuj” -------------------------------------------------------
# Działa tylko, gdy aplikację uruchomił lokalnie/serwer.py (LOCAL_RESTART=1). Serwer kończy się kodem
# LOCAL_RESTART_CODE, a serwer.py robi `git pull` i startuje go od nowa. Na Renderze strona tylko informuje.
import json  # noqa: E402
import threading  # noqa: E402
from html import escape as _esc  # noqa: E402
from urllib.parse import urlparse  # noqa: E402

from flask import request  # noqa: E402

_PAGE = """<!doctype html><html lang="pl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Restart aplikacji</title><style>
:root{{color-scheme:light dark;--bg:#f6f7f9;--fg:#1c2330;--card:#fff;--mut:#667085;--acc:#1f7ae0}}
@media (prefers-color-scheme:dark){{:root{{--bg:#141922;--fg:#e6e9ef;--card:#1d2430;--mut:#9aa4b2;--acc:#4ea1ff}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif}}
main{{max-width:560px;margin:0 auto;padding:24px 16px}}.card{{background:var(--card);border-radius:14px;padding:18px;margin:14px 0}}
button{{font:inherit;font-weight:600;border:0;border-radius:10px;padding:14px 18px;width:100%;background:var(--acc);color:#fff;cursor:pointer}}
.m{{color:var(--mut);font-size:.92em}}a{{color:var(--acc)}}code{{font-size:.9em}}</style></head><body><main>{body}</main></body></html>"""


def _local_restart_enabled() -> bool:
    return os.getenv("LOCAL_RESTART") == "1"


@app.route("/restart", methods=["GET", "POST"])
def local_restart():
    import fbpred
    import tnpred
    back = request.args.get("back") or request.form.get("back") or "/tennis/"
    if not back.startswith("/"):
        back = "/tennis/"
    ver = (f'<p class="m">Piłka {fbpred.__version__} · tenis {tnpred.__version__}'
           f'{" · commit " + _esc(os.getenv("RENDER_GIT_COMMIT", "")[:7]) if os.getenv("RENDER_GIT_COMMIT") else ""}</p>')
    if not _local_restart_enabled():
        body = ('<h1>Restart</h1><div class="card"><p>Ten przycisk działa tylko w kopii lokalnej na PC '
                '(uruchomionej przez <code>lokalnie\\uruchom_aplikacje.bat</code>).</p>'
                '<p class="m">Render aktualizuje się sam kilka minut po wysłaniu zmian na GitHub.</p>' + ver + '</div>')
        return _PAGE.format(body=body), 404
    if request.method == "POST":
        origin = request.headers.get("Origin")
        if origin and urlparse(origin).netloc != request.host:      # inna strona nie może zrestartować aplikacji
            return "Niedozwolone źródło żądania", 403
        code = int(os.getenv("LOCAL_RESTART_CODE", "3"))
        threading.Timer(1.0, lambda: os._exit(code)).start()
        body = ('<h1>Restartuję…</h1><div class="card"><p>Pobieram najnowszy kod z GitHuba i uruchamiam aplikację od nowa. '
                'Zwykle trwa to 30–90 s – strona przejdzie dalej sama.</p><p class="m" id="st">czekam na zatrzymanie…</p></div>'
                '<script>var back=' + json.dumps(back).replace('<', '\\u003c') + ',down=false,t0=Date.now();'
                'function tick(){fetch("/tennis/healthz",{cache:"no-store"}).then(function(r){if(r.ok&&down){location.href=back;return;}'
                'if(!r.ok)down=true;more();}).catch(function(){down=true;more();});}'
                'function more(){var s=Math.round((Date.now()-t0)/1000);document.getElementById("st").textContent='
                '(down?"uruchamiam ponownie… ":"czekam na zatrzymanie… ")+s+" s";'
                'if(s>240){document.getElementById("st").textContent="Długo to trwa – sprawdź czarne okno na PC.";return;}setTimeout(tick,3000);}'
                'setTimeout(tick,2500);</script>')
        return _PAGE.format(body=body)
    body = ('<h1>Aktualizuj i zrestartuj</h1><div class="card"><p>Pobiera najnowszy kod z GitHuba (to, co wysłał Claude) '
            'i uruchamia aplikację od nowa: piłkę i tenis. Przez ok. minutę strona nie będzie odpowiadać.</p>'
            f'<form method="post"><input type="hidden" name="back" value="{_esc(back)}"><button>🔄 Aktualizuj i zrestartuj</button></form>'
            + ver + f'</div><p><a href="{_esc(back)}">← wróć</a></p>')
    return _PAGE.format(body=body)
