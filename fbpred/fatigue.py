"""Czy krótka przerwa / mecz Ligi Mistrzów naprawdę zmienia wyniki? Test na prognozach walk-forward.

1. Efekt na średnią goli: regresja Poissona z offsetem log(xG modelu) - czy drużyny po krótkiej przerwie strzelają mniej/więcej
   niż przewidział model, a ich rywale?  Do modelu trafia tylko to, co ma |z| >= Z_MIN (domyślnie 2.5).
2. Efekt na PRZEWIDYWALNOŚĆ: czy model jest gorszy od średniej ligowej po krótkiej przerwie niż w zwykłych meczach?
"""
from __future__ import annotations

import numpy as np
import pandas as pd

Z_MIN = 2.5
TERMS = ("own_short", "opp_short", "own_cl", "opp_cl")
LABELS = {"own_short": "własna krótka przerwa (≤4 dni) → gole własne",
          "opp_short": "krótka przerwa rywala → gole własne",
          "own_cl": "własny mecz LM w ciągu 5 dni → gole własne",
          "opp_cl": "mecz LM rywala w ciągu 5 dni → gole własne"}


def poisson_offset(y: np.ndarray, offset: np.ndarray, X: np.ndarray, iters: int = 100) -> tuple[np.ndarray, np.ndarray]:
    """Regresja Poissona z offsetem (Newton-Raphson). Zwraca (współczynniki, błędy standardowe)."""
    beta = np.zeros(X.shape[1])
    H = np.eye(X.shape[1])
    for _ in range(iters):
        mu = np.exp(np.clip(offset + X @ beta, -20, 20))
        g = X.T @ (y - mu)
        H = (X * mu[:, None]).T @ X + 1e-9 * np.eye(X.shape[1])
        step = np.linalg.solve(H, g)
        beta += step
        if np.max(np.abs(step)) < 1e-9:
            break
    return beta, np.sqrt(np.diag(np.linalg.inv(H)))


def side_frame(res: pd.DataFrame, feats: pd.DataFrame, league: str = "") -> pd.DataFrame:
    """Wynik backtestu + cechy odpoczynku -> po jednym wierszu na stronę meczu (gole własne vs xG modelu)."""
    f = feats.reset_index(drop=True)
    r = res.reset_index(drop=True)
    home = pd.DataFrame({"y": r["hg"], "xg": r["xg_h"], "own_short": f["short_h"], "opp_short": f["short_a"],
                         "own_cl": f["cl_h"], "opp_cl": f["cl_a"]})
    away = pd.DataFrame({"y": r["ag"], "xg": r["xg_a"], "own_short": f["short_a"], "opp_short": f["short_h"],
                         "own_cl": f["cl_a"], "opp_cl": f["cl_h"]})
    out = pd.concat([home, away], ignore_index=True)
    out["league"] = league
    out["date"] = pd.concat([r["date"], r["date"]], ignore_index=True)
    return out


def _design(sides: pd.DataFrame, terms: list[str], leagues: list[str]) -> np.ndarray:
    lg = np.column_stack([(sides["league"] == l).astype(float).to_numpy() for l in leagues])   # wyraz wolny osobno dla ligi
    return np.column_stack([sides[terms].astype(float).to_numpy(), lg]) if terms else lg


def _offset(sides: pd.DataFrame) -> np.ndarray:
    return np.log(np.clip(sides["xg"].to_numpy(float), 0.05, None))


def holdout_gain(sides: pd.DataFrame, split: float = 0.6) -> dict:
    """Czy współczynniki wyestymowane na pierwszych 60% meczów poprawiają prognozę goli na ostatnich 40%?
    Zwraca przyrost log-wiarygodności na 100 obserwacji (>0 = poprawa) - drugi bezpiecznik obok progu |z|."""
    s = sides.sort_values("date", kind="stable").reset_index(drop=True)
    cut = int(len(s) * split)
    tr, te = s.iloc[:cut], s.iloc[cut:]
    leagues = sorted(s["league"].unique())
    terms = [t for t in TERMS if 0 < tr[t].astype(int).sum() < len(tr) and te[t].astype(int).sum() > 0]
    if not terms or len(te) < 100:
        return {"gain_per_100": 0.0, "n_test": len(te), "terms": terms}
    b_full, _ = poisson_offset(tr["y"].to_numpy(float), _offset(tr), _design(tr, terms, leagues))
    b_base, _ = poisson_offset(tr["y"].to_numpy(float), _offset(tr), _design(tr, [], leagues))
    y = te["y"].to_numpy(float)
    ll = lambda eta: float(np.sum(y * eta - np.exp(eta)))  # noqa: E731
    gain = ll(_offset(te) + _design(te, terms, leagues) @ b_full) - ll(_offset(te) + _design(te, [], leagues) @ b_base)
    return {"gain_per_100": 100 * gain / len(te), "n_test": len(te), "terms": terms}


def mean_shift_test(sides: pd.DataFrame) -> pd.DataFrame:
    """Efekt na gole z przedziałami ufności; pomija człony bez zmienności (np. brak danych LM)."""
    terms = [t for t in TERMS if 0 < sides[t].astype(int).sum() < len(sides)]
    if not terms:
        return pd.DataFrame()
    X = _design(sides, terms, sorted(sides["league"].unique()))
    beta, se = poisson_offset(sides["y"].to_numpy(float), _offset(sides), X)
    rows = []
    for i, t in enumerate(terms):
        b, s = beta[i], se[i]
        z = b / s
        rows.append({"efekt": LABELS[t], "klucz": t, "zmiana_goli_%": 100 * (np.exp(b) - 1),
                     "przedzial_95_%": f"{100 * (np.exp(b - 1.96 * s) - 1):+.0f} … {100 * (np.exp(b + 1.96 * s) - 1):+.0f}",
                     "z": z, "wspolczynnik": b, "n_dotknietych": int(sides[t].sum()),
                     "wniosek": "ISTOTNE" if abs(z) >= Z_MIN else "szum (za mało dowodów)"})
    return pd.DataFrame(rows).round(3)


def _loss(P: np.ndarray, y: np.ndarray) -> np.ndarray:
    return -np.log(np.clip(P[np.arange(len(y)), y], 1e-12, 1))


def uncertainty_test(res: pd.DataFrame, feats: pd.DataFrame, n_boot: int = 2000, seed: int = 0) -> dict:
    """Umiejętność modelu (strata średniej ligowej − strata modelu, 1X2) po krótkiej przerwie vs w zwykłych meczach."""
    f = feats.reset_index(drop=True)
    r = res.reset_index(drop=True)
    y = r["y"].to_numpy(int)
    skill = _loss(r[["b1", "bx", "b2"]].to_numpy(), y) - _loss(r[["p1", "px", "p2"]].to_numpy(), y)
    flag = (f["short_h"] | f["short_a"]).to_numpy()
    a, b = skill[flag], skill[~flag]
    out = {"n_krotka": int(flag.sum()), "n_zwykle": int((~flag).sum())}
    if len(a) < 30 or len(b) < 30:
        return {**out, "wniosek": "za mało meczów po krótkiej przerwie, by cokolwiek stwierdzić"}
    rng = np.random.default_rng(seed)
    diff = np.array([rng.choice(a, len(a)).mean() - rng.choice(b, len(b)).mean() for _ in range(n_boot)])
    lo, hi = np.percentile(diff, [2.5, 97.5])
    d = float(a.mean() - b.mean())
    verdict = ("po krótkiej przerwie model jest ISTOTNIE gorszy (mecze mniej przewidywalne) - rozważ ostrożność / mniejsze stawki"
               if hi < 0 else "po krótkiej przerwie model jest istotnie lepszy (nietypowe - sprawdź dane)" if lo > 0
               else "różnica w przewidywalności nieistotna (w granicach szumu)")
    return {**out, "umiejetnosc_krotka": float(a.mean()), "umiejetnosc_zwykle": float(b.mean()), "roznica": d,
            "przedzial_95": (float(lo), float(hi)), "wniosek": verdict}


def significant_coefs(table: pd.DataFrame, holdout: dict | None = None) -> dict[str, float]:
    """Tylko współczynniki z |z| >= próg ORAZ (jeśli podano) dodatnim przyrostem na danych kontrolnych."""
    if table.empty or (holdout is not None and holdout.get("gain_per_100", 0.0) <= 0):
        return {}
    ok = table[table["z"].abs() >= Z_MIN]
    return {r["klucz"]: round(float(r["wspolczynnik"]), 4) for _, r in ok.iterrows()}
