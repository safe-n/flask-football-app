"""Stan aplikacji: baza, model, odświeżanie danych (z blokadą), synchronizacja z GitHubem, diagnostyka (zakładka Dane)."""
from __future__ import annotations

import threading
import time
import traceback
from datetime import datetime, timezone

import pandas as pd

from . import bets as bets_mod, config, db, gh_store, ledger, oddsapi, synthetic, tdata
from .model import TennisModel, load_params, save_params
from .names import norm


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class State:
    def __init__(self, db_path=None):
        self.conn = db.connect(db_path)
        ledger.ensure(self.conn)
        bets_mod.ensure(self.conn)
        self.lock = threading.Lock()          # odświeżanie danych
        self.model_lock = threading.Lock()
        self.model: TennisModel | None = None
        self.model_version = 0
        self.data_version = 0
        self.diag: dict = {"kroki": [], "start": _now()}
        self.refreshing = False
        self._lookup = None

    # ------------------------------------------------------------------ diagnostyka
    def step(self, name: str, ok: bool, msg: str) -> None:
        self.diag["kroki"] = [s for s in self.diag["kroki"] if s["krok"] != name] + [
            {"krok": name, "ok": ok, "opis": msg, "czas": _now()}]
        print(f"[tnpred] {name}: {'OK' if ok else 'BŁĄD'} - {msg}", flush=True)

    # ------------------------------------------------------------------ model
    def get_model(self) -> TennisModel:
        if self.model is None or self.model_version != self.data_version:
            with self.model_lock:
                if self.model is None or self.model_version != self.data_version:
                    v = self.data_version
                    self.model = TennisModel(db.load_matches(self.conn))
                    self._lookup = None
                    self.model_version = v
        return self.model

    def lookup(self, tour, date, p1, p2):
        """Wynik meczu p1–p2 (dowolna kolejność) w oknie [data-3, data+4] - albo None."""
        m = self.get_model()
        if self._lookup is None:
            idx: dict = {}
            for r in m.df.to_dict("records"):
                idx.setdefault((r["tour"], frozenset((r["winner"], r["loser"]))), []).append(r)
            self._lookup = idx
        rows = self._lookup.get((tour, frozenset((p1, p2))), [])
        d = pd.Timestamp(str(date)[:10])
        best = [r for r in rows if d - pd.Timedelta(days=3) <= r["date"] <= d + pd.Timedelta(days=4)]
        return best[0] if best else None

    def mark_changed(self) -> None:
        self.data_version += 1


# ---------------------------------------------------------------------- ładowanie
def load_local(st: State) -> int:
    rep: list = []
    df = tdata.load_history_dir(report=rep)
    n = db.upsert_matches(st.conn, df) if len(df) else 0
    if rep:
        st.step("pliki XLSX z repo", not any("BŁĄD" in x for x in rep), "; ".join(rep))
    if n == 0 and config.DEMO and db.load_matches(st.conn).empty:
        demo = synthetic.generate()
        db.upsert_matches(st.conn, demo)
        db.upsert_upcoming(st.conn, synthetic.upcoming(demo))
        st.step("demo", True, f"TN_DEMO=1: {len(demo)} meczów syntetycznych (NIE są prawdziwe)")
        n = len(demo)
    st.step("historia z repo", True, f"{len(df)} meczów z folderu {config.HISTORY_DIR.name}/")
    st.mark_changed()
    return n


def fetch_results(st: State, years: int | None = None, force: bool = False) -> int:
    """tennis-data.co.uk: bieżący rok zawsze, starsze tylko gdy brak ich w bazie/historii."""
    years = years or config.YEARS
    have = db.load_matches(st.conn)
    now = pd.Timestamp.today()
    total = 0
    for tour in config.TOURS:
        for y in range(now.year - years + 1, now.year + 1):
            have_y = have[(have.tour == tour) & (have.date.dt.year == y)] if len(have) else have
            if y < now.year and len(have_y) > 500 and not force:
                continue
            if y == now.year and now.month == 1 and now.day < 3:
                continue
            try:
                df, src = tdata.download_any(tour, y)
                n = db.upsert_matches(st.conn, df)
                total += n
                st.step(f"wyniki {tour} {y}", True, f"{len(df)} meczów (nowe/zmienione: {n}) - źródło: {src}")
            except Exception as e:  # noqa: BLE001
                ok = len(have_y) > 0
                st.step(f"wyniki {tour} {y}", ok, (f"nie pobrano nowszych danych ({str(e)[:200]}); używam {len(have_y)} meczów z repo. "
                                                    f"Aktualizacja: pobierz plik ręcznie (README)") if ok else str(e))
    db.meta_set(st.conn, "results_at", _now())
    if total:
        st.mark_changed()
    return total


def history_surface_lookup(st: State):
    m = st.get_model()
    df = m.df
    if df.empty:
        return lambda title: None
    last = df.sort_values("date").groupby("location").surface.last().to_dict()
    last.update(df.sort_values("date").groupby("tournament").surface.last().to_dict())
    keys = {norm(k): v for k, v in last.items() if k}

    def look(title: str):
        t = norm(title).replace("atp ", "").replace("wta ", "")
        for k, v in keys.items():
            if k and (k in t or t in k):
                return v
        return None
    return look


def fetch_odds(st: State, force: bool = False) -> int:
    if not oddsapi.enabled():
        st.step("kursy (The Odds API)", True, "wyłączone - brak ODDS_API_KEY (możesz dodawać mecze ręcznie w zakładce Mecze)")
        return 0
    last = db.meta_get(st.conn, "odds_at")
    if last and not force:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() / 3600
        if age < config.ODDS_REFRESH_HOURS:
            st.step("kursy (The Odds API)", True, f"pominięte - ostatnio {age:.1f} h temu (limit kredytów)")
            return 0
    m = st.get_model()
    try:
        rows, info = oddsapi.fetch_all(resolve=m.resolve, history_lookup=history_surface_lookup(st))
    except Exception as e:  # noqa: BLE001
        st.step("kursy (The Odds API)", False, str(e))
        return 0
    n = db.upsert_upcoming(st.conn, rows)
    db.meta_set(st.conn, "odds_at", _now())
    q = info.get("quota") or {}
    st.step("kursy (The Odds API)", not info["errors"],
            f"{n} meczów; kredyty: zostało {q.get('remaining')}, zużyto {q.get('used')}" +
            (f"; problemy: {'; '.join(info['errors'][:3])}" if info["errors"] else ""))
    return n


def prune_played(st: State) -> int:
    up = db.load_upcoming(st.conn, include_past_days=30)
    if up.empty:
        return 0
    drop = [r["id"] for r in up.to_dict("records") if st.lookup(r["tour"], r["date"], r["p1"], r["p2"]) is not None]
    for i in drop:
        db.delete_upcoming(st.conn, i)
    return len(drop) + db.prune_upcoming(st.conn, set(), older_than_days=3)


def log_predictions(st: State) -> int:
    m = st.get_model()
    up = db.load_upcoming(st.conn, include_past_days=0)
    if up.empty:
        return 0
    horizon = (pd.Timestamp.today() + pd.Timedelta(days=config.LOG_HORIZON_DAYS)).strftime("%Y-%m-%d")
    rows = []
    for r in up.to_dict("records"):
        if str(r["date"])[:10] > horizon:
            continue
        p = m.predict(r["tour"], r["surface"], r["best_of"], r["p1"], r["p2"], r.get("o1"), r.get("o2"))
        line = r.get("total_line")
        if line is None or line != line:
            line = 22.5 if p["best_of"] == 3 else 38.5
        over = sum(v for k, v in p["m"]["games_pmf"].items() if k > float(line))
        rows.append({"id": r["id"], "date": str(r["date"])[:10], "tour": r["tour"], "tournament": r.get("tournament"),
                     "surface": p["surface"], "best_of": p["best_of"], "p1": p["p1"], "p2": p["p2"], "p_model": p["p"],
                     "p_elo": p["p_elo"], "p_market": p["p_market"], "o1": r.get("o1"), "o2": r.get("o2"),
                     "games_mean": p["m"]["games_mean"], "total_line": float(line), "p_over": over,
                     "p_tb": p["m"]["p_tb"], "p_straight": p["m"]["straight"]})
    return ledger.log(st.conn, rows)


def manual_export(st: State) -> tuple[str, int]:
    up = db.load_upcoming(st.conn, include_past_days=7)
    up = up[up.source == "manual"] if len(up) else up
    cols = [c for c in db.UP_COLS]
    return (up[cols].to_csv(index=False) if len(up) else ",".join(cols) + "\n"), len(up)


def manual_import(st: State, text: str) -> int:
    import io
    df = pd.read_csv(io.StringIO(text))
    if df.empty:
        return 0
    rows = df.astype(object).where(df.notna(), None).to_dict("records")
    return db.upsert_upcoming(st.conn, rows)


def sync_down(st: State) -> None:
    if not gh_store.enabled():
        st.step("GitHub (zapis trwały)", True, "wyłączone - brak GITHUB_TOKEN/GITHUB_REPO: dziennik i zakłady znikną przy restarcie")
        return
    try:
        a = gh_store.sync_down("predictions", lambda t: ledger.import_text(st.conn, t))
        b = gh_store.sync_down("bets", lambda t: bets_mod.import_text(st.conn, t))
        c = gh_store.sync_down("manual", lambda t: manual_import(st, t))
        st.step("GitHub: odczyt", True, f"prognozy {a}, zakłady {b}, ręczne mecze {c} (gałąź {config.LEDGER_BRANCH}, folder {config.LEDGER_PREFIX})")
    except Exception as e:  # noqa: BLE001
        st.step("GitHub: odczyt", False, str(e))


def sync_up(st: State, kinds=("predictions", "bets", "manual")) -> None:
    if not gh_store.enabled():
        return
    ex = {"predictions": (lambda: ledger.export_text(st.conn), "prognoz"),
          "bets": (lambda: bets_mod.export_text(st.conn), "zakładów"),
          "manual": (lambda: manual_export(st), "ręcznych meczów")}
    for k in kinds:
        try:
            st.step(f"GitHub: zapis {k}", True, gh_store.sync_up(k, *ex[k]))
        except Exception as e:  # noqa: BLE001
            st.step(f"GitHub: zapis {k}", False, str(e))


def sync_up_bg(st: State, kinds=("bets",)) -> None:
    threading.Thread(target=sync_up, args=(st, kinds), daemon=True).start()


def autotune(st: State) -> None:
    """Brak tennis_params/model.json -> dobierz parametry w tle (ok. 10-30 s) i użyj ich do końca życia procesu."""
    if load_params().get("s0"):
        return
    m = st.get_model()
    if len(m.df) < 500:
        return
    try:
        p = {"s0": m.fit_s0(), "blend_w": m.fit_blend(), "fitted_at": _now(), "auto": True}
        m.params = p
        m.s0.update(p["s0"])
        m.w.update(p["blend_w"])
        try:
            save_params(p)
        except OSError:
            pass
        st.step("strojenie modelu", True, f"s0={p['s0']} waga modelu={p['blend_w']}")
    except Exception as e:  # noqa: BLE001
        st.step("strojenie modelu", False, str(e))


def refresh(st: State, force: bool = False, network: bool = True) -> None:
    if not st.lock.acquire(blocking=False):
        return
    st.refreshing = True
    try:
        if network:
            fetch_results(st, force=force)
        m = st.get_model()
        st.step("model", True, f"{len(m.df)} meczów, {sum(1 for _ in m.elo.r)} zawodników; ostatni mecz {m.df.date.max():%Y-%m-%d}"
                if len(m.df) else "brak meczów w bazie")
        autotune(st)
        if network:
            fetch_odds(st, force=force)
        pr = prune_played(st)
        lg = log_predictions(st)
        sb = bets_mod.settle_open(st.conn, st.lookup)
        st.step("dziennik", True, f"zapisano/odświeżono {lg} prognoz, rozliczono {sb} zakładów, usunięto {pr} rozegranych/starych meczów z listy")
        if network:
            sync_up(st)
        st.diag["refreshed_at"] = _now()
    except Exception as e:  # noqa: BLE001
        st.step("odświeżanie", False, f"{e}\n{traceback.format_exc()[-800:]}")
    finally:
        st.refreshing = False
        st.lock.release()


def start_background(st: State) -> None:
    """Start: GitHub -> pełne odświeżenie; potem pętla co TN_REFRESH_HOURS."""
    def loop():
        sync_down(st)
        refresh(st)
        while config.REFRESH_HOURS > 0:
            time.sleep(max(600, config.REFRESH_HOURS * 3600))
            refresh(st)
    threading.Thread(target=loop, daemon=True, name="tnpred-refresh").start()
