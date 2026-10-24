"""Zasilanie bazy: historia z CSV (offline) -> uzupełnienie brakujących sezonów -> bieżący sezon i terminarz.

Na Renderze (plan darmowy) SQLite jest tymczasowy, więc przy każdym starcie odtwarzamy ją z `history/` (offline, sekundy),
a sieć służy tylko do uzupełnień. Każdy krok zapisuje diagnostykę w DIAG (widoczną na stronie /data).
"""
from __future__ import annotations

import os
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from . import config, csvdata, db, fdorg, gh_store, history, names
from .leagues import NO_CSV


def _log(msg: str) -> None:
    print(msg, flush=True)   # flush: bez tego logi z wątku mogą nie pojawić się w panelu Rendera


STATUS = {"state": "idle", "message": "Dane nie zostały jeszcze załadowane.", "updated": None}
DIAG: dict[str, dict[str, str]] = {}      # liga -> {krok: wynik}
_started = False
_start_lock = threading.Lock()
_work_lock = threading.Lock()


def season_now() -> int:
    t = date.today()
    return t.year if t.month >= 7 else t.year - 1


def _set(state: str, message: str) -> None:
    STATUS.update(state=state, message=message, updated=datetime.now().isoformat(timespec="seconds"))


def leagues() -> list[str]:
    """Jawna lista z BOOTSTRAP_LEAGUES albo wszystkie ligi z history/ (tryb 'auto')."""
    return list(config.BOOTSTRAP_LEAGUES) or history.discover_leagues(config.HISTORY_DIR) or [config.DEFAULT_LEAGUE]


def describe() -> dict:
    hd = Path(config.HISTORY_DIR)
    return {"AUTO_BOOTSTRAP": config.AUTO_BOOTSTRAP, "RENDER": os.getenv("RENDER", "-"),
            "ligi": ",".join(leagues()), "REFRESH_HOURS": config.REFRESH_HOURS,
            "football-data.org": "token ustawiony" if fdorg.enabled() else "brak tokenu", "pid": os.getpid(),
            "pliki_historii": len(list(hd.glob("*.csv"))) if hd.exists() else 0, "DB_PATH": str(config.DB_PATH)}


def count_finished(conn, league: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM matches WHERE league=? AND hg IS NOT NULL", (league,)).fetchone()[0]


def seasons_in_db(conn, league: str) -> set[int]:
    return {r[0] for r in conn.execute(
        "SELECT DISTINCT season FROM matches WHERE league=? AND hg IS NOT NULL AND season IS NOT NULL", (league,))}


def _known_teams(conn, league: str) -> list[str]:
    rows = conn.execute("SELECT DISTINCT home FROM matches WHERE league=? AND season>=?",
                        (league, season_now() - 2)).fetchall()
    return [r[0] for r in rows]


def load_local(leagues_: list[str] | None = None, log=_log) -> int:
    """Wczytuje historię z CSV do SQLite OD RAZU i OFFLINE (bez sieci, bez wątku). Zwraca liczbę meczów w bazie."""
    lgs = leagues_ or leagues()
    conn = db.connect(config.DB_PATH)
    history.load_into_db(conn, config.HISTORY_DIR, lgs)
    from . import ledger
    ledger.import_csv(conn, config.LEDGER_CSV)
    total = sum(count_finished(conn, lg) for lg in lgs)
    if total:
        _set("ready", f"Wczytano {total} meczów z historii (CSV). Odświeżanie z internetu: "
                      f"{'w tle' if config.AUTO_BOOTSTRAP else 'wyłączone (AUTO_BOOTSTRAP)'}.")
    log(f"[bootstrap] start: {describe()} | w bazie: {total} meczów")
    return total


def ensure_data(leagues_: list[str] | None = None, years: int = 4, min_matches: int = 200, log=_log) -> dict[str, int]:
    """Historia z CSV, a potem dociągnięcie BRAKUJĄCYCH sezonów z ostatnich `years` (np. luka 2025 w E0)."""
    conn = db.connect(config.DB_PATH)
    out: dict[str, int] = {}
    for lg in leagues_ or leagues():
        d = DIAG.setdefault(lg, {})
        n_hist = history.load_into_db(conn, config.HISTORY_DIR, [lg])
        if n_hist:
            log(f"[bootstrap] {lg}: wczytano {n_hist} meczów z historii (CSV)")
        have = seasons_in_db(conn, lg)
        missing = [y for y in range(season_now() - years + 1, season_now() + 1) if y not in have]
        n = 0
        for y in missing:
            try:
                if lg in NO_CSV:
                    if not fdorg.enabled():
                        d["sezony"] = "brak tokenu football-data.org - nie uzupełniam"
                        break
                    rows = fdorg.fetch_season(lg, y)
                else:
                    rows = history.apply_aliases(csvdata.parse_csv(csvdata.download(lg, y), lg, y))
                db.upsert_matches(conn, rows)
                n += len(rows)
            except Exception as e:  # noqa: BLE001 - jeden brakujący sezon nie może zatrzymać reszty
                log(f"[bootstrap] {lg} {y}: {e}")
        d.setdefault("sezony", f"w bazie {sorted(seasons_in_db(conn, lg))}; dociągnięto {n} meczów ({len(missing)} sezonów brakowało)")
        out[lg] = n_hist + n
        if n:
            log(f"[bootstrap] {lg}: dociągnięto brakujące sezony {missing}: {n} meczów")
    return out


def _fdorg_rows(conn, lg: str, fetch) -> list[dict]:
    known = _known_teams(conn, lg)
    resolver = (lambda c: names.resolve(c, known)) if known and lg not in NO_CSV else None
    return fetch(resolver)


def settle_pending(conn, lg: str, season_rows, log=_log) -> tuple[int, str]:
    """Wyniki meczów z ostatnich dni, które już się odbyły, a jeszcze nie dotarły do CSV (opóźnienie źródła).

    Uzupełnia je z football-data.org (tylko wynik i wynik do przerwy, bez kartek/rożnych - te przyjdą z CSV).
    Wiersz zachowuje swój fixture_id, więc późniejszy plik CSV po prostu go uzupełni, bez duplikatów."""
    pend = conn.execute("SELECT fixture_id, date, home, away FROM matches WHERE league=? AND hg IS NULL AND date < ? "
                        "AND date >= date(?, '-7 day')", (lg, db.today(), db.today())).fetchall()
    if not pend:
        return 0, "brak meczów czekających na wynik"
    if not (fdorg.enabled() and fdorg.supports(lg)):
        return 0, f"{len(pend)} meczów czeka na wynik; szybsze wyniki wymagają tokenu FOOTBALL_DATA_ORG_TOKEN"
    finished = [r for r in season_rows() if r["status"] == "FT"]
    n = 0
    for fid, date, h, a in pend:
        day = pd.Timestamp(date)
        for r in finished:
            if r["home"] == h and r["away"] == a and abs((pd.Timestamp(r["date"]) - day).days) <= 1:   # UTC vs czas lokalny
                db.update_fields(conn, fid, {"hg": r["hg"], "ag": r["ag"], "hg_ht": r["hg_ht"], "ag_ht": r["ag_ht"], "status": "FT"})
                n += 1
                break
    return n, f"dopisano {n} z {len(pend)} wyników (football-data.org)"


def refresh(leagues_: list[str] | None = None, log_predictions: bool = True, log=_log) -> None:
    """Bieżący sezon + terminarz (z kursami, jeśli są), sprzątanie, zapis prognoz do dziennika."""
    lgs = leagues_ or leagues()
    conn = db.connect(config.DB_PATH)
    for lg in lgs:
        d = DIAG.setdefault(lg, {})
        y = season_now()
        if lg in NO_CSV:
            if not fdorg.enabled():
                d["football-data.org"] = "brak tokenu FOOTBALL_DATA_ORG_TOKEN - brak odświeżania"
                continue
            try:
                rows = fdorg.fetch_season(lg, y)
                db.upsert_matches(conn, rows)
                d["football-data.org"] = f"ok: {len(rows)} meczów sezonu {y} (wyniki + terminarz)"
            except Exception as e:  # noqa: BLE001
                d["football-data.org"] = f"błąd: {e}"
                log(f"[refresh] {lg}: {e}")
            continue
        try:                                                                  # wyniki bieżącego sezonu
            rows = history.apply_aliases(csvdata.parse_csv(csvdata.download(lg, y), lg, y))
            db.upsert_matches(conn, rows)
            d["sezon_csv"] = f"ok: {len(rows)} meczów sezonu {y}"
        except Exception as e:  # noqa: BLE001
            d["sezon_csv"] = f"błąd: {e}"
            log(f"[refresh] sezon {lg}: {e}")
        fixtures: list[dict] = []
        fd_cache: dict[str, list] = {}

        def fd_season(lg=lg, y=y, fd_cache=fd_cache):                        # jedno zapytanie na ligę: wyniki + terminarz
            if "rows" not in fd_cache:
                fd_cache["rows"] = _fdorg_rows(conn, lg, lambda res: fdorg.fetch_season(lg, y, res))
            return fd_cache["rows"]
        try:                                                                  # terminarz + kursy (football-data.co.uk)
            fixtures = history.apply_aliases(csvdata.parse_csv(csvdata.download_fixtures(), lg, None, only_div=True))
            db.upsert_matches(conn, fixtures)
            d["fixtures_csv"] = f"{len(fixtures)} nadchodzących meczów" if fixtures else \
                "plik pobrany, ale bez nadchodzących meczów tej ligi"
            if config.ARCHIVE_ODDS and fixtures:
                log(f"[refresh] archiwum kursów {lg}: +{history.archive_odds(fixtures, config.HISTORY_DIR)}")
        except Exception as e:  # noqa: BLE001
            d["fixtures_csv"] = f"błąd: {e}"
            log(f"[refresh] fixtures {lg}: {e}")
        try:                                                                  # wyniki wcześniej niż CSV
            d["wyniki_szybkie"] = settle_pending(conn, lg, fd_season, log)[1]
        except Exception as e:  # noqa: BLE001
            d["wyniki_szybkie"] = f"błąd: {e}"
            log(f"[refresh] wyniki {lg}: {e}")
        if not fixtures:                                                      # zapasowe źródło terminarza
            if fdorg.enabled() and fdorg.supports(lg):
                try:
                    rows = [r for r in fd_season() if r["status"] == "NS"]
                    db.upsert_matches(conn, rows)
                    d["football-data.org"] = f"ok: {len(rows)} nadchodzących (bez kursów)"
                except Exception as e:  # noqa: BLE001
                    d["football-data.org"] = f"błąd: {e}"
                    log(f"[refresh] fdorg {lg}: {e}")
            elif not fdorg.enabled():
                d["football-data.org"] = "zapas wyłączony: brak tokenu FOOTBALL_DATA_ORG_TOKEN"
    db.purge_stale_upcoming(conn)
    if not log_predictions:
        return
    from . import ledger, params as prm
    horizon = pd.Timestamp.today().normalize() + pd.Timedelta(days=config.LOG_HORIZON_DAYS)
    for lg in lgs:
        df, up = db.load_matches(conn, lg), db.load_upcoming(conn, lg, since=db.today())  # nie dla meczów już rozegranych
        up = up[up["date"] <= horizon]
        if len(df) >= 100 and not up.empty:
            try:
                P, p = prm.build_predictor(df, lg)
                ledger.log_predictions(conn, P, up, lg, blend_w=p["blend_w"])
            except Exception as e:  # noqa: BLE001
                log(f"[refresh] dziennik {lg}: {e}")


def _ledger_pull(conn, log) -> None:
    d = DIAG.setdefault("dziennik", {})
    if not gh_store.enabled():
        d["trwalosc"] = ("WYŁĄCZONA - ustaw GITHUB_TOKEN i GITHUB_REPO w Render → Environment; bez tego dziennik znika "
                         "przy każdym restarcie lub uśpieniu serwisu")
        return
    try:
        d["trwalosc"] = f"GitHub, gałąź {config.LEDGER_BRANCH}: wczytano {gh_store.sync_down(conn)} prognoz przy starcie"
    except Exception as e:  # noqa: BLE001 - problem z GitHubem nie może zatrzymać aplikacji
        d["trwalosc"] = f"błąd odczytu z GitHuba: {e}"
        log(f"[ledger] {e}")


def _ledger_push(conn, log) -> None:
    d = DIAG.setdefault("dziennik", {})
    if not gh_store.enabled():
        return
    try:
        d["zapis"] = gh_store.sync_up(conn)
    except Exception as e:  # noqa: BLE001
        d["zapis"] = f"błąd zapisu do GitHuba: {e}"
        log(f"[ledger] {e}")


def run_once(leagues_: list[str] | None = None, years: int | None = None, log=_log, export_ledger: bool = False) -> None:
    lgs = leagues_ or leagues()
    with _work_lock:
        try:
            if STATUS["state"] != "ready":
                _set("loading", f"Pobieram dane ({', '.join(lgs)}) - to potrwa kilka sekund, odśwież stronę.")
            ensure_data(lgs, years or config.BOOTSTRAP_YEARS, log=log)
            from . import ledger
            conn = db.connect(config.DB_PATH)
            n_imp = ledger.import_csv(conn, config.LEDGER_CSV)  # dziennik z repo (jeśli jest)
            if n_imp:
                log(f"[bootstrap] wczytano {n_imp} prognoz z {config.LEDGER_CSV}")
            _ledger_pull(conn, log)
            refresh(lgs, log=log)
            _ledger_push(conn, log)
            if export_ledger:
                log(f"[bootstrap] zapisano {ledger.export_csv(conn, config.LEDGER_CSV)} prognoz do {config.LEDGER_CSV}")
            total = sum(count_finished(conn, lg) for lg in lgs)
            _set("ready" if total else "error", f"Gotowe: {total} meczów w bazie." if total else
                 "Nie udało się pobrać danych (sprawdź logi serwisu).")
        except Exception as e:  # noqa: BLE001
            _set("error", f"Błąd zasilania bazy: {e}")
            log(f"[bootstrap] błąd: {e}")


def start_background() -> None:
    """Uruchamia (raz na proces) wątek: zasilenie przy starcie, potem odświeżanie co REFRESH_HOURS."""
    global _started
    with _start_lock:
        if _started:
            return
        _started = True

    def loop():
        run_once()
        while True:
            if STATUS["state"] == "error":      # chwilowa awaria (sieć, źródło danych) -> ponów za 5 minut
                time.sleep(300)
                run_once()
                continue
            if config.REFRESH_HOURS <= 0:
                return
            time.sleep(config.REFRESH_HOURS * 3600)
            with _work_lock:
                try:
                    refresh()
                    _ledger_push(db.connect(config.DB_PATH), _log)
                    _set("ready", "Odświeżono dane.")
                except Exception as e:  # noqa: BLE001
                    print(f"[refresh] błąd: {e}", flush=True)

    if STATUS["state"] != "ready":
        _set("loading", "Start aplikacji - zasilanie bazy w toku.")
    threading.Thread(target=loop, name="fbpred-bootstrap", daemon=True).start()
