"""Stan aplikacji: baza, model, odświeżanie danych (z blokadą), synchronizacja z GitHubem, diagnostyka (zakładka Dane)."""
from __future__ import annotations

import threading
import time
import traceback
from datetime import datetime, timezone

import pandas as pd

from . import bets as bets_mod, picks as picks_mod, config, db, espn, gh_store, ledger, oddsapi, synthetic, tdata
from .model import TennisModel, load_params, save_params
from .names import norm


def all_stacks() -> str:
    """Gdzie są teraz wątki tenisa (diagnostyka zawieszeń, pokazywana w Dane podczas startu)."""
    import sys
    frames = sys._current_frames()
    out = []
    for t in threading.enumerate():
        if not t.name.startswith("tnpred") or t.ident not in frames:
            continue
        lines = [f"{f.filename.rsplit('/', 2)[-1]}:{f.lineno} {f.name}" for f in traceback.extract_stack(frames[t.ident])[-5:]]
        out.append(f"{t.name}: " + " → ".join(lines))
    return "\n".join(out)


def stuck_where(st: State) -> str:
    """Gdzie stoi wątek odświeżania (diagnostyka zawieszeń - widoczne w zakładce Dane)."""
    import sys
    import traceback
    fr = sys._current_frames().get(st.refresh_thread or -1) or sys._current_frames().get(st.bg_thread or -1)
    if fr is None:
        return ""
    lines = [f"{f.filename.rsplit('/', 2)[-1]}:{f.lineno} {f.name}" for f in traceback.extract_stack(fr)[-6:]]
    return " → ".join(lines)


def free_memory() -> None:
    """Oddaje zwolnioną pamięć systemowi (glibc trzyma ją „na zapas”, a Render liczy ją jako zajętą)."""
    import ctypes
    import gc
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass


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
        self.refresh_started: float | None = None
        self.refresh_thread: int | None = None
        self.bg_thread: int | None = None
        self.bg_pid: int | None = None
        self.gh_loaded = False          # zapis do GitHuba dopiero po udanym odczycie (ochrona przed nadpisaniem pustą bazą)
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
                    t0 = time.time()
                    self.step("model: liczę", True, "start (wczytanie meczów z bazy, Elo, kursy historyczne)")
                    df_m = db.load_matches(self.conn)
                    self.step("model: liczę", True, f"wczytano {len(df_m)} meczów z bazy w {time.time() - t0:.0f} s, liczę Elo…")
                    new = TennisModel(df_m)     # stary model obsługuje strony, dopóki nowy się liczy
                    del df_m
                    self.step("model: liczę", True, f"gotowy w {time.time() - t0:.0f} s")
                    self.model, self._lookup, self.model_version = new, None, v
                    del new
                    free_memory()
        return self.model

    def model_for_web(self):
        """Dla stron: nigdy nie czekamy minutami na przeliczenie (Render po ok. minucie zwraca 502).
        Jest model (nawet sprzed nowych danych) -> używamy go, a nowy liczy się w tle. Brak modelu -> None (strona „Ładuję…”)."""
        stale = self.model is None or self.model_version != self.data_version
        if stale and not self.model_lock.locked():
            threading.Thread(target=self.get_model, daemon=True, name="tnpred-model").start()
        return self.model

    def lookup(self, tour, date, p1, p2):
        """Wynik meczu p1–p2 (dowolna kolejność) w oknie [data-3, data+4] - albo None."""
        m = self.model if self.model is not None else self.get_model()
        if self._lookup is None:
            idx: dict = {}
            for i, (t, w, l) in enumerate(zip(m.df.tour.astype(str), m.df.winner.astype(str), m.df.loser.astype(str))):
                idx.setdefault((t, frozenset((w, l))), []).append(i)
            self._lookup = idx
        rows = self._lookup.get((tour, frozenset((p1, p2))), [])
        d = pd.Timestamp(str(date)[:10])
        dates = m.df["date"]
        for i in rows:
            if d - pd.Timedelta(days=3) <= dates.iat[i] <= d + pd.Timedelta(days=4):
                r = m.df.iloc[i].to_dict()
                for c in ("tour", "winner", "loser", "comment", "tournament", "surface", "round", "series"):
                    if c in r:
                        r[c] = str(r[c])
                return r
        return None

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
    del df
    free_memory()
    st.mark_changed()
    return n


def fetch_results(st: State, years: int | None = None, force: bool = False) -> int:
    """tennis-data.co.uk: bieżący rok zawsze, starsze tylko gdy brak ich w bazie/historii."""
    years = years or config.YEARS
    blocked = db.meta_get(st.conn, "tdata_blocked_at")
    if blocked and not force:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(blocked)).total_seconds() / 3600
        if age < 24:
            st.step("wyniki (tennis-data.co.uk)", True,
                    f"pominięte: {age:.0f} h temu strona zablokowała ten serwer (HTTP 403) - to normalne. Nowe wyniki przychodzą "
                    f"z Twojego komputera przez GitHuba (krok „wyniki z GitHuba”)")
            return 0
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
            st.step(f"wyniki {tour} {y}", True, "pobieram…")
            try:
                df, src = tdata.download_any(tour, y)
                n = db.upsert_matches(st.conn, df)
                total += n
                st.step(f"wyniki {tour} {y}", True, f"{len(df)} meczów (nowe/zmienione: {n}) - źródło: {src}")
            except Exception as e:  # noqa: BLE001
                ok = len(have_y) > 0
                if "403" in str(e):
                    db.meta_set(st.conn, "tdata_blocked_at", _now())
                    st.step(f"wyniki {tour} {y}", ok, f"tennis-data.co.uk blokuje serwer Rendera (HTTP 403) - to normalne. "
                            f"Nowe wyniki przychodzą z Twojego komputera przez GitHuba (python -m tnpred push-history / zaplanowane zadanie)")
                    return total
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
    last: dict = {}
    for col in ("location", "tournament"):          # „location” nie ma w odchudzonych danych modelu - bierzemy, co jest
        if col in df.columns:
            g = df[[col, "surface", "date"]].sort_values("date").groupby(col, observed=True).surface.last()
            last.update({str(k): str(v) for k, v in g.items()})
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
    st.step("kursy (The Odds API)", True, "czekam na model…")
    m = st.get_model()
    st.step("kursy (The Odds API)", True, "pobieram z the-odds-api.com…")
    try:
        rows, info = oddsapi.fetch_all(resolve=m.resolve, history_lookup=history_surface_lookup(st))
    except Exception as e:  # noqa: BLE001
        st.step("kursy (The Odds API)", False, str(e))
        return 0
    rows = keep_prematch_odds(st, rows)
    n = db.upsert_upcoming(st.conn, rows)
    db.meta_set(st.conn, "odds_at", _now())
    q = info.get("quota") or {}
    st.step("kursy (The Odds API)", not info["errors"],
            f"{n} meczów; kredyty: zostało {q.get('remaining')}, zużyto {q.get('used')}" +
            (f"; problemy: {'; '.join(info['errors'][:3])}" if info["errors"] else ""))
    return n


def fetch_espn(st: State) -> int:
    """ESPN: (1) wyniki z ostatnich dni, których nie ma jeszcze w tennis-data - znikają, gdy tennis-data je opublikuje;
    (2) terminarz na dziś/jutro dla meczów, których nie zna The Odds API (bez kursów)."""
    name = "ESPN: wyniki i terminarz"
    if not config.ESPN:
        st.step(name, True, "wyłączone (TN_ESPN=0)")
        return 0
    m = st.get_model()
    hist = db.load_matches(st.conn)
    now = datetime.now(timezone.utc)
    res, sched, info = espn.fetch_all(hist, resolve=m.resolve, tours=config.TOURS, days_back=config.ESPN_DAYS, now=now)
    if info["errors"] and not res and not sched:
        st.step(name, False, "feed niedostępny - zostają same dane tennis-data i The Odds API: " + "; ".join(info["errors"])[:300])
        return 0
    # wyniki: nowe z feedu + starsze łatki spoza okna (dopóki tennis-data ich nie ma, max 30 dni)
    since = f"{now - pd.Timedelta(days=config.ESPN_DAYS):%Y-%m-%d}"
    old = hist[(hist["location"].astype(str) == espn.MARK)] if len(hist) else hist
    keep = []
    if len(old):
        o = old[(old.date < pd.Timestamp(since)) & (old.date >= pd.Timestamp(now.date()) - pd.Timedelta(days=30))].copy()
        o["date"] = o["date"].dt.strftime("%Y-%m-%d")
        keep = o.astype(object).where(o.notna(), None).to_dict("records")
    rows = espn.uncovered(res + keep, hist)
    changed = db.set_espn_matches(st.conn, espn.results_frame(rows))
    if changed:
        st.mark_changed()
    # terminarz: tylko mecze, których nie ma z innego źródła (The Odds API / ręczne)
    up = db.load_upcoming(st.conn, include_past_days=2)
    other = up[up.source != "espn"] if len(up) else up
    pairs = {(t, frozenset((a, b))): str(d)[:10] for t, a, b, d in zip(other.tour, other.p1, other.p2, other.date)} if len(other) else {}
    with db._LOCK:
        st.conn.execute("DELETE FROM upcoming WHERE source='espn'")
        st.conn.commit()
    add = []
    for r in sched:
        d = pairs.get((r["tour"], frozenset((r["p1"], r["p2"]))))
        if d and abs((pd.Timestamp(d) - pd.Timestamp(r["date"][:10])).days) <= 1:
            continue
        r = {k: v for k, v in r.items() if k != "live"}
        if r["date"][:10] < f"{now - pd.Timedelta(days=1):%Y-%m-%d}":
            continue
        add.append(r)
    n_up = db.upsert_upcoming(st.conn, add)
    last = max((r["date"] for r in rows), default="-")
    st.step(name, True, f"wyniki: {len(rows)} meczów spoza tennis-data (ostatni {last}); terminarz: {n_up} meczów bez kursów "
            f"(The Odds API ich nie ma)" + (f"; pominięte turnieje (ITF/125/spoza tennis-data): {', '.join(info['skipped'][:6])}"
                                           if info["skipped"] else "") + (f"; problemy: {'; '.join(info['errors'])}" if info["errors"] else ""))
    return len(rows)


def keep_prematch_odds(st: State, rows: list[dict]) -> list[dict]:
    """Mecz już trwa -> The Odds API zwraca kursy NA ŻYWO. Zostawiamy zapisane kursy sprzed meczu (albo żadnych)."""
    from .views import start_time
    now = pd.Timestamp.now(tz="UTC")
    have = db.load_upcoming(st.conn, include_past_days=2)
    known = set(have.id) if len(have) else set()
    out = []
    for r in rows:
        t = start_time(r.get("date"))
        if t is not None and t <= now:
            if db.up_id(r["tour"], r["date"], r["p1"], r["p2"]) in known:
                continue
            r = {**r, "o1": None, "o2": None, "total_line": None, "o_over": None, "o_under": None,
                 "hcp_line": None, "o_h1": None, "o_h2": None}
        out.append(r)
    return out


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


def sync_history(st: State) -> int:
    """Świeże wyniki wysłane z Twojego komputera (python -m tnpred push-history) leżą w gałęzi ledger-data,
    folder tennis/history/. Pobieramy tylko pliki, które się zmieniły (porównanie sha) + nowe parametry modelu."""
    if not gh_store.enabled():
        return 0
    try:
        files = gh_store.list_dir(gh_store.history_path())
    except Exception as e:  # noqa: BLE001
        st.step("wyniki z GitHuba", False, str(e))
        return 0
    if not files:
        st.step("wyniki z GitHuba", True, "brak plików w gałęzi - uruchom u siebie python -m tnpred push-history "
                                         "(albo zaplanuj: python -m tnpred install-task)")
        return 0
    n, names = 0, []
    for name, sha in sorted(files.items()):
        key = f"hist_sha:{name}"
        if db.meta_get(st.conn, key) == sha:
            continue
        try:
            if name.endswith(".csv"):
                df = tdata.read_csv_text(gh_store.pull_raw(gh_store.history_path(name)) or "")
                n += db.upsert_matches(st.conn, df)
                names.append(f"{name} ({len(df)})")
            elif name == "model.json":
                import json
                from .model import save_params
                save_params(json.loads(gh_store.pull_raw(gh_store.history_path(name)) or "{}"))
                names.append("parametry modelu")
                n += 1
            elif name == "style.json":            # styl TB zawodników - liczy Twój komputer (push-history)
                import json
                from . import style as _style
                _style.save(json.loads(gh_store.pull_raw(gh_store.history_path(name)) or "{}"))
                names.append("styl zawodników")
                n += 1
            db.meta_set(st.conn, key, sha)
        except Exception as e:  # noqa: BLE001
            st.step(f"wyniki z GitHuba: {name}", False, str(e))
    if names:
        st.mark_changed()
    st.step("wyniki z GitHuba", True, ("wczytano: " + ", ".join(names)) if names else "bez zmian od ostatniego sprawdzenia")
    return n


def sync_down(st: State) -> None:
    if not gh_store.enabled():
        st.step("GitHub (zapis trwały)", True, "wyłączone - brak GITHUB_TOKEN/GITHUB_REPO: dziennik i zakłady znikną przy restarcie")
        return
    ok, msg = gh_store.check()
    st.step("GitHub: token", ok, msg)
    if not ok:
        return
    try:
        a = gh_store.sync_down("predictions", lambda t: ledger.import_text(st.conn, t))
        b = gh_store.sync_down("bets", lambda t: bets_mod.import_text(st.conn, t))
        c = gh_store.sync_down("manual", lambda t: manual_import(st, t))
        gh_store.sync_down("coupons", lambda t: picks_mod.import_coupons(st.conn, t))
        d = gh_store.sync_down("picks", lambda t: picks_mod.import_text(st.conn, t))
        st.gh_loaded = True
        st.step("GitHub: odczyt", True, f"prognozy {a}, zakłady {b}, typy {d}, ręczne mecze {c} (gałąź {config.LEDGER_BRANCH}, folder {config.LEDGER_PREFIX})")
    except Exception as e:  # noqa: BLE001
        st.step("GitHub: odczyt", False, str(e))


def sync_up(st: State, kinds=("predictions", "bets", "picks", "coupons", "manual")) -> None:
    if not gh_store.enabled():
        return
    if not st.gh_loaded:
        # 0.3.14: po restarcie Rendera baza jest pusta - zapis przed odczytem nadpisywał dziennik, zakłady i kupony
        st.step("GitHub: zapis", True, "wstrzymany - najpierw odczyt z GitHuba (ochrona przed nadpisaniem pustą bazą)")
        return
    ex = {"predictions": (lambda: ledger.export_text(st.conn), "prognoz"),
          "bets": (lambda: bets_mod.export_text(st.conn), "zakładów"),
          "picks": (lambda: picks_mod.export_text(st.conn), "typów"),
          "coupons": (lambda: picks_mod.export_coupons(st.conn), "kuponów"),
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
    if not config.AUTOTUNE:
        st.step("strojenie modelu", True, "parametry domyślne - dobierz je u siebie: python -m tnpred fetch-history (stroi automatycznie), potem Commit/Push")
        return
    m = st.get_model()
    if len(m.df) < 500:
        return
    try:
        s0 = m.fit_s0()
        p = {"s0": s0, "sigma": m.fitted_sigma, "blend_w": m.fit_blend(), "fitted_at": _now(), "auto": True}
        m.params = p
        m.s0.update(p["s0"])
        m.w.update(p["blend_w"])
        m.sigma.update(p["sigma"])
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
    st.refresh_started = time.time()
    st.refresh_thread = threading.get_ident()
    st.step("odświeżanie", True, "start")
    try:
        if network:
            fetch_odds(st, force=force)       # najpierw mecze z kursami - nie mogą czekać na GitHuba ani tennis-data
            sync_history(st)
            fetch_results(st, force=force)
            try:
                fetch_espn(st)                # po tennis-data: łatka tylko tego, czego tam jeszcze nie ma
            except Exception as e:  # noqa: BLE001
                st.step("ESPN: wyniki i terminarz", False, f"{type(e).__name__}: {e}")
        m = st.get_model()
        st.step("model", True, f"{len(m.df)} meczów, {sum(1 for _ in m.elo.r)} zawodników; ostatni mecz {m.df.date.max():%Y-%m-%d}"
                if len(m.df) else "brak meczów w bazie")
        autotune(st)
        from . import features
        features._index(m.df)                 # rozgrzewka: indeks zawodników przed pierwszym wejściem na stronę
        pr = prune_played(st)
        lg = log_predictions(st)
        sb = bets_mod.settle_open(st.conn, st.lookup)
        sp = picks_mod.settle_open(st.conn, st.lookup)
        st.step("dziennik", True, f"zapisano/odświeżono {lg} prognoz, rozliczono {sb} zakładów i {sp} typów, "
                f"usunięto {pr} rozegranych/starych meczów z listy")
        if network:
            sync_up(st)
        st.diag["refreshed_at"] = _now()
        st.step("odświeżanie", True, f"zakończone w {time.time() - st.refresh_started:.0f} s")
        free_memory()
    except Exception as e:  # noqa: BLE001
        st.step("odświeżanie", False, f"{e}\n{traceback.format_exc()[-800:]}")
    finally:
        st.refreshing = False
        st.lock.release()


def ensure_background(st: State) -> bool:
    """Startuje wątek tła w procesie, który NAPRAWDĘ obsługuje strony. Serwer (gunicorn z --preload / Render)
    może wczytać aplikację w procesie głównym i obsługiwać strony w procesie potomnym - wątki z procesu głównego
    tam nie istnieją, a blokady skopiowane w trakcie liczenia zostają „zamknięte” na zawsze. Wołane przy każdym zapytaniu."""
    import os
    pid = os.getpid()
    if st.bg_pid == pid:
        return False
    with _START_LOCK:
        if st.bg_pid == pid:
            return False
        if st.bg_pid is not None:                 # jesteśmy kopią po fork - świeże blokady i flagi
            st.lock = threading.Lock()
            st.model_lock = threading.Lock()
            st.refreshing = False
            st.step("proces", True, f"nowy proces serwera (pid {pid}) - startuję wątek tła tutaj")
        st.bg_pid = pid
        start_background(st)
        return True


_START_LOCK = threading.Lock()


def start_background(st: State) -> None:
    """Wątek w tle: najpierw odczyt z GitHuba, potem kursy, model i zapis; dalej pętla co TN_REFRESH_HOURS.
    Każdy błąd - także taki, który wcześniej po cichu kończył wątek - trafia do zakładki Dane."""
    def guarded(name, fn):
        try:
            fn()
        except BaseException as e:  # noqa: BLE001 - wątek tła nie może zginąć bez śladu
            st.step(f"wątek tła: {name}", False, f"{type(e).__name__}: {e}\n{traceback.format_exc()[-700:]}")

    def loop():
        st.bg_thread = threading.get_ident()
        st.step("wątek tła", True, "start")
        guarded("GitHub", lambda: sync_down(st))          # NAJPIERW odczyt (dziennik, zakłady, typy, kupony)
        guarded("odświeżanie", lambda: refresh(st))       # potem odświeżenie i zapis
        while config.REFRESH_HOURS > 0:
            time.sleep(max(600, config.REFRESH_HOURS * 3600))
            if not st.gh_loaded:
                guarded("GitHub", lambda: sync_down(st))
            guarded("odświeżanie", lambda: refresh(st))

    threading.Thread(target=loop, daemon=True, name="tnpred-refresh").start()
