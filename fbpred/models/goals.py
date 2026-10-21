"""Model Dixon-Coles (1997) dla bramek: 1X2, over/under, BTTS, dokładne wyniki.

Wersja dwuetapowa (szybka i stabilna):
  1. Regresja Poissona z ridge i wagami czasowymi: log(lambda) = mu + ha*[dom] + atak[A] + obrona[B]
     (analityczny gradient, L-BFGS). `obrona` to "podatność na stratę gola" - wyższa = gorsza.
  2. Parametr rho (korekta niskich wyników 0-0, 1-0, 0-1, 1-1) dobierany osobno 1D.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize, minimize_scalar
from scipy.stats import poisson

MAX_GOALS = 10


def tau(x, y, lh, la, rho):
    """Korekta Dixon-Coles dla niskich wyników (wektorowo)."""
    x = np.asarray(x)
    y = np.asarray(y)
    lh = np.asarray(lh, dtype=float)
    la = np.asarray(la, dtype=float)
    t = np.ones(lh.shape, dtype=float)
    m = (x == 0) & (y == 0)
    t[m] = 1 - lh[m] * la[m] * rho
    m = (x == 0) & (y == 1)
    t[m] = 1 + lh[m] * rho
    m = (x == 1) & (y == 0)
    t[m] = 1 + la[m] * rho
    m = (x == 1) & (y == 1)
    t[m] = 1 - rho
    return t


def score_matrix(lh: float, la: float, rho: float = 0.0, max_goals: int = MAX_GOALS) -> np.ndarray:
    """Macierz P(gole gospodarzy = i, gole gości = j)."""
    g = np.arange(max_goals + 1)
    m = np.outer(poisson.pmf(g, lh), poisson.pmf(g, la))
    m[0, 0] *= max(1 - lh * la * rho, 0.0)
    m[0, 1] *= max(1 + lh * rho, 0.0)
    m[1, 0] *= max(1 + la * rho, 0.0)
    m[1, 1] *= max(1 - rho, 0.0)
    return m / m.sum()


class DixonColes:
    def __init__(self, xi: float = 0.0019, ridge: float = 10.0):
        """xi: zanik wagi na dzień (0.0019 ~ połowa wagi po ~1 roku). ridge: shrinkage do średniej."""
        self.xi = xi
        self.ridge = ridge
        self.fitted = False

    # ------------------------------------------------------------------ fit
    def fit(self, df: pd.DataFrame, as_of=None) -> "DixonColes":
        d = df.dropna(subset=["hg", "ag"])
        if len(d) < 20:
            raise ValueError("Za mało meczów do dopasowania modelu bramek (min. 20).")
        as_of = pd.Timestamp(as_of) if as_of is not None else d["date"].max()
        days = (as_of - d["date"]).dt.days.clip(lower=0).to_numpy(float)
        w = np.exp(-self.xi * days)

        teams = sorted(set(d["home"]) | set(d["away"]))
        idx = {t: i for i, t in enumerate(teams)}
        T, n = len(teams), len(d)
        h = d["home"].map(idx).to_numpy()
        a = d["away"].map(idx).to_numpy()
        hg = d["hg"].to_numpy(float)
        ag = d["ag"].to_numpy(float)

        y = np.concatenate([hg, ag])
        atk = np.concatenate([h, a])
        dfn = np.concatenate([a, h])
        ish = np.concatenate([np.ones(n), np.zeros(n)])
        ww = np.concatenate([w, w])
        ridge = self.ridge

        def f(theta):
            mu, ha = theta[0], theta[1]
            att, de = theta[2:2 + T], theta[2 + T:]
            eta = mu + ha * ish + att[atk] + de[dfn]
            lam = np.exp(eta)
            val = np.sum(ww * (lam - y * eta)) + ridge * (att @ att + de @ de)
            r = ww * (lam - y)
            g = np.empty_like(theta)
            g[0] = r.sum()
            g[1] = (r * ish).sum()
            g[2:2 + T] = np.bincount(atk, r, minlength=T) + 2 * ridge * att
            g[2 + T:] = np.bincount(dfn, r, minlength=T) + 2 * ridge * de
            return val, g

        x0 = np.zeros(2 + 2 * T)
        x0[0] = np.log(max(y.mean(), 0.1))
        res = minimize(f, x0, jac=True, method="L-BFGS-B")
        th = res.x
        self.mu, self.ha = float(th[0]), float(th[1])
        self.att = dict(zip(teams, th[2:2 + T]))
        self.de = dict(zip(teams, th[2 + T:]))
        self.teams = teams

        # etap 2: rho
        lh = np.exp(self.mu + self.ha + th[2:2 + T][h] + th[2 + T:][a])
        la = np.exp(self.mu + th[2:2 + T][a] + th[2 + T:][h])
        low = (hg <= 1) & (ag <= 1)
        if low.sum() >= 10:
            def nll_rho(r):
                t = tau(hg[low], ag[low], lh[low], la[low], r)
                return -np.sum(w[low] * np.log(np.clip(t, 1e-9, None)))

            self.rho = float(minimize_scalar(nll_rho, bounds=(-0.4, 0.4), method="bounded").x)
        else:
            self.rho = 0.0
        self.fitted = True
        return self

    # -------------------------------------------------------------- predict
    def knows(self, team: str) -> bool:
        return team in self.att

    def lambdas(self, home: str, away: str) -> tuple[float, float]:
        """Oczekiwane gole gospodarzy i gości (nieznana drużyna = średnia ligowa)."""
        ah, dh = self.att.get(home, 0.0), self.de.get(home, 0.0)
        aa, da = self.att.get(away, 0.0), self.de.get(away, 0.0)
        lh = np.exp(self.mu + self.ha + ah + da)
        la = np.exp(self.mu + aa + dh)
        return float(lh), float(la)

    def matrix(self, home: str, away: str, max_goals: int = MAX_GOALS) -> np.ndarray:
        lh, la = self.lambdas(home, away)
        return score_matrix(lh, la, self.rho, max_goals)

    def strengths(self) -> pd.DataFrame:
        """Ranking drużyn: atak (wyżej = lepiej), obrona (niżej = lepiej), ogółem."""
        df = pd.DataFrame({"atak": self.att, "obrona": self.de})
        df["ogolem"] = df["atak"] - df["obrona"]
        return df.sort_values("ogolem", ascending=False).round(3)
