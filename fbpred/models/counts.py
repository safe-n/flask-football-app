"""Model zliczeń (kartki, rożne, gole w połowach...) - Poisson / ujemna dwumianowa.

log(mu) = b0 + bh*[dom] + za[drużyna] + przeciw[rywal] + sędzia[opcjonalnie]
Ridge (osobno dla drużyn i sędziów), wagi czasowe, nadmierna dyspersja (NB) estymowana z danych.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize, minimize_scalar
from scipy.special import gammaln
from scipy.stats import nbinom, poisson


def to_long(df: pd.DataFrame, hcol: str, acol: str) -> pd.DataFrame:
    """Mecz (1 wiersz) -> format długi (2 wiersze: gospodarz i gość)."""
    ref = df["referee"] if "referee" in df else pd.Series([None] * len(df), index=df.index)
    home = pd.DataFrame({"date": df["date"], "team": df["home"], "opp": df["away"],
                         "is_home": 1, "y": df[hcol], "ref": ref})
    away = pd.DataFrame({"date": df["date"], "team": df["away"], "opp": df["home"],
                         "is_home": 0, "y": df[acol], "ref": ref})
    out = pd.concat([home, away], ignore_index=True)
    return out.dropna(subset=["y"]).reset_index(drop=True)


class CountModel:
    def __init__(self, xi: float = 0.0015, ridge: float = 10.0, ridge_ref: float = 15.0,
                 use_ref: bool = False, kmax: int = 30):
        self.xi, self.ridge, self.ridge_ref = xi, ridge, ridge_ref
        self.use_ref, self.kmax = use_ref, kmax
        self.alpha = 0.0
        self.fitted = False

    def fit(self, long: pd.DataFrame, as_of=None) -> "CountModel":
        d = long.dropna(subset=["y"])
        if len(d) < 40:
            raise ValueError("Za mało danych do modelu zliczeń (min. 40 obserwacji).")
        as_of = pd.Timestamp(as_of) if as_of is not None else d["date"].max()
        days = (as_of - d["date"]).dt.days.clip(lower=0).to_numpy(float)
        w = np.exp(-self.xi * days)

        teams = sorted(set(d["team"]) | set(d["opp"]))
        tix = {t: i for i, t in enumerate(teams)}
        T = len(teams)
        refs = sorted(d["ref"].dropna().unique()) if self.use_ref else []
        rix = {r: i for i, r in enumerate(refs)}
        R = len(refs)

        ti = d["team"].map(tix).to_numpy()
        oi = d["opp"].map(tix).to_numpy()
        ish = d["is_home"].to_numpy(float)
        y = d["y"].to_numpy(float)
        ri = (d["ref"].map(rix).fillna(-1).astype(int).to_numpy() if R
              else -np.ones(len(d), dtype=int))
        rm = ri >= 0
        r1, r2 = self.ridge, self.ridge_ref

        def unpack(th):
            return th[0], th[1], th[2:2 + T], th[2 + T:2 + 2 * T], th[2 + 2 * T:]

        def eta_of(th):
            b0, bh, f, o, r = unpack(th)
            e = b0 + bh * ish + f[ti] + o[oi]
            if R:
                e = e + np.where(rm, r[np.where(rm, ri, 0)], 0.0)
            return e

        def fun(th):
            b0, bh, f, o, r = unpack(th)
            eta = eta_of(th)
            lam = np.exp(eta)
            val = np.sum(w * (lam - y * eta)) + r1 * (f @ f + o @ o) + r2 * (r @ r)
            res = w * (lam - y)
            g = np.empty_like(th)
            g[0] = res.sum()
            g[1] = (res * ish).sum()
            g[2:2 + T] = np.bincount(ti, res, minlength=T) + 2 * r1 * f
            g[2 + T:2 + 2 * T] = np.bincount(oi, res, minlength=T) + 2 * r1 * o
            if R:
                g[2 + 2 * T:] = np.bincount(ri[rm], res[rm], minlength=R) + 2 * r2 * r
            return val, g

        x0 = np.zeros(2 + 2 * T + R)
        x0[0] = np.log(max(y.mean(), 0.05))
        th = minimize(fun, x0, jac=True, method="L-BFGS-B").x
        b0, bh, f, o, r = unpack(th)
        self.b0, self.bh = float(b0), float(bh)
        self.f, self.o = dict(zip(teams, f)), dict(zip(teams, o))
        self.r = dict(zip(refs, r))

        # nadmierna dyspersja: alpha z NB (Var = mu + alpha*mu^2)
        mu = np.exp(eta_of(th))

        def nll(log_a):
            a = np.exp(log_a)
            k = 1.0 / a
            ll = (gammaln(y + k) - gammaln(k) - gammaln(y + 1)
                  + k * np.log(k / (k + mu)) + y * np.log(mu / (k + mu)))
            return -np.sum(w * ll)

        best = minimize_scalar(nll, bounds=(np.log(1e-6), np.log(3.0)), method="bounded").x
        a = float(np.exp(best))
        self.alpha = 0.0 if a < 1e-3 else a
        self.fitted = True
        return self

    def mean(self, team: str, opp: str, is_home: int, ref: str | None = None) -> float:
        e = self.b0 + self.bh * is_home + self.f.get(team, 0.0) + self.o.get(opp, 0.0)
        if ref and self.use_ref:
            e += self.r.get(ref, 0.0)
        return float(np.exp(e))

    def pmf(self, mu: float, kmax: int | None = None) -> np.ndarray:
        k = np.arange((kmax or self.kmax) + 1)
        if self.alpha < 1e-3:
            p = poisson.pmf(k, mu)
        else:
            n = 1.0 / self.alpha
            p = nbinom.pmf(k, n, n / (n + mu))
        return p / p.sum()
