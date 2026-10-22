"""Automatyczne zasilanie bazy: pierwsze pobranie danych + okresowe odświeżanie w tle.

Po co: na Renderze (plan darmowy) system plików jest tymczasowy - baza SQLite znika przy każdym
restarcie/uśpieniu, a Cron Job nie ma dostępu do plików serwisu WWW. Dlatego aplikacja sama
dociąga dane przy starcie (kilka plików CSV, to kilka sekund) i odświeża je w tle.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from datetime import date, datetime

from . import config, csvdata, db, history

def _log(msg: str) -> None:
    print(msg, flush=True)   # flush: bez tego logi z wątku mogą nie pojawić się w panelu Rendera


STATUS = {"state": "idle", "message": "Dane nie zostały jeszcze załadowane.", "updated": None}
_started = False
_start_lock = threading.Lock()
_work_lock = threading.Lock()


def season_now() -> int:
    t = date.today()
    return t.year if t.month >= 7 else t.year - 1


def _set(state: str, message: str) -> None:
    STATUS.update(state=state, message=message, updated=datetime.now().isoformat(timespec="seconds"))


def count_finished(conn, league: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM matches WHERE league=? AND hg IS NOT NULL", (league,)).fetchone()[0]


def describe() -> dict:
    """Konfiguracja widoczna w logach i na stronie /data (do diagnozy 'czemu nie ładuje')."""
    hd = Path(config.HISTORY_DIR)
    return {"AUTO_BOOTSTRAP": config.AUTO_BOOTSTRAP, "RENDER": os.getenv("RENDER", "-"),
            "ligi": ",".join(config.BOOTSTRAP_LEAGUES), "REFRESH_HOURS": config.REFRESH_HOURS,
            "HISTORY_DIR": str(hd), "pliki_historii": len(list(hd.glob("*.csv"))) if hd.exists() else 0,
            "DB_PATH": str(config.DB_PATH)}


def load_local(leagues: list[str] | None = None, log=_log) -> int:
    """Wczytuje historię z CSV do SQLite OD RAZU i OFFLINE (bez sieci, bez wątku). Zwraca liczbę meczów w bazie."""
    leagues = leagues or config.BOOTSTRAP_LEAGUES
    conn = db.connect(config.DB_PATH)
    history.load_into_db(conn, config.HISTORY_DIR, leagues)
    from . import ledger
    ledger.import_csv(conn, config.LEDGER_CSV)
    total = sum(count_finished(conn, lg) for lg in leagues)
    if total:
        _set("ready", f"Wczytano {total} meczów z historii (CSV). Odświeżanie z internetu: "
                      f"{'w tle' if config.AUTO_BOOTSTRAP else 'wyłączone (AUTO_BOOTSTRAP)'}.")
    log(f"[bootstrap] start: {describe()} | w bazie: {total} meczów")
    return total


def ensure_data(leagues: list[str], years: int = 4, min_matches: int = 200, log=_log) -> dict[str, int]:
    """Jeśli w bazie brakuje danych ligi - pobiera ostatnie `years` sezonów (idempotentne)."""
    conn = db.connect(config.DB_PATH)
    out: dict[str, int] = {}
    for lg in leagues:
        n_hist = history.load_into_db(conn, config.HISTORY_DIR, [lg])  # 1. historia z CSV - offline i szybko
        if n_hist:
            log(f"[bootstrap] {lg}: wczytano {n_hist} meczów z historii (CSV)")
        if count_finished(conn, lg) >= min_matches:
            out[lg] = n_hist
            continue
        n = 0                                                          # 2. awaryjnie: pobierz ze źródła
        for y in range(season_now() - years + 1, season_now() + 1):
            try:
                rows = csvdata.parse_csv(csvdata.download(lg, y), lg, y)
                db.upsert_matches(conn, rows)
                n += len(rows)
            except Exception as e:  # noqa: BLE001 - jeden brakujący sezon nie może zatrzymać reszty
                log(f"[bootstrap] {lg} {y}: {e}")
        out[lg] = n
        log(f"[bootstrap] {lg}: pobrano {n} meczów")
    return out


def refresh(leagues: list[str], log_predictions: bool = True, log=_log) -> None:
    """Bieżący sezon + nadchodzące mecze z kursami, sprzątanie, opcjonalnie zapis prognoz do dziennika."""
    conn = db.connect(config.DB_PATH)
    for lg in leagues:
        try:
            y = season_now()
            db.upsert_matches(conn, history.apply_aliases(csvdata.parse_csv(csvdata.download(lg, y), lg, y)))
        except Exception as e:  # noqa: BLE001
            log(f"[refresh] sezon {lg}: {e}")
        try:
            rows = history.apply_aliases(csvdata.parse_csv(csvdata.download_fixtures(), lg, None, only_div=True))
            db.upsert_matches(conn, rows)
            if config.ARCHIVE_ODDS:
                log(f"[refresh] archiwum kursów {lg}: +{history.archive_odds(rows, config.HISTORY_DIR)}")
        except Exception as e:  # noqa: BLE001
            log(f"[refresh] fixtures {lg}: {e}")
    db.purge_stale_upcoming(conn)
    if not log_predictions:
        return
    from . import ledger, params as prm
    for lg in leagues:
        df, up = db.load_matches(conn, lg), db.load_upcoming(conn, lg)
        if len(df) >= 100 and not up.empty:
            try:
                P, p = prm.build_predictor(df, lg)
                ledger.log_predictions(conn, P, up, lg, blend_w=p["blend_w"])
            except Exception as e:  # noqa: BLE001
                log(f"[refresh] dziennik {lg}: {e}")


def run_once(leagues: list[str] | None = None, years: int | None = None, log=_log,
             export_ledger: bool = False) -> None:
    leagues = leagues or config.BOOTSTRAP_LEAGUES
    with _work_lock:
        try:
            if STATUS["state"] != "ready":
                _set("loading", f"Pobieram dane ({', '.join(leagues)}) - to potrwa kilka sekund, odśwież stronę.")
            ensure_data(leagues, years or config.BOOTSTRAP_YEARS, log=log)
            from . import ledger
            conn = db.connect(config.DB_PATH)
            n_imp = ledger.import_csv(conn, config.LEDGER_CSV)  # dziennik z repo (jeśli jest)
            if n_imp:
                log(f"[bootstrap] wczytano {n_imp} prognoz z {config.LEDGER_CSV}")
            refresh(leagues, log=log)
            if export_ledger:
                log(f"[bootstrap] zapisano {ledger.export_csv(conn, config.LEDGER_CSV)} prognoz do {config.LEDGER_CSV}")
            total = sum(count_finished(conn, lg) for lg in leagues)
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
                    refresh(config.BOOTSTRAP_LEAGUES)
                    _set("ready", "Odświeżono dane.")
                except Exception as e:  # noqa: BLE001
                    print(f"[refresh] błąd: {e}")

    if STATUS["state"] != "ready":
        _set("loading", "Start aplikacji - zasilanie bazy w toku.")
    threading.Thread(target=loop, name="fbpred-bootstrap", daemon=True).start()
