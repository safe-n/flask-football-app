"""Trwałość bez dysku (jak fbpred): pliki CSV w osobnej gałęzi repo (ledger-data) przez GitHub REST API.

Tenis zapisuje do folderu `tennis/` (TN_LEDGER_PREFIX), więc może dzielić repo i gałąź z aplikacją football.
Commit tylko, gdy treść się zmieniła; gałąź osobna -> brak przebudowy na Renderze. Token wyłącznie ze zmiennej środowiskowej.
"""
from __future__ import annotations

import base64
import io

import pandas as pd
import requests

from . import config

API = "https://api.github.com"
FILES = {"predictions": "predictions.csv", "bets": "bets.csv", "manual": "upcoming_manual.csv"}


class GhStoreError(RuntimeError):
    pass


def enabled() -> bool:
    return bool(config.GITHUB_TOKEN and config.GITHUB_REPO)


def path(kind: str) -> str:
    return config.LEDGER_PREFIX + FILES[kind]


def _call(method: str, p: str, **kw):
    headers = {"Authorization": f"Bearer {config.GITHUB_TOKEN}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "tnpred"}
    r = requests.request(method, API + p, headers=headers, timeout=30, **kw)
    if r.status_code in (401, 403):
        raise GhStoreError(f"GitHub odrzucił token ({r.status_code}) - sprawdź uprawnienie 'Contents: Read and write' do {config.GITHUB_REPO}")
    return r


def pull(p: str, branch: str | None = None) -> tuple[str | None, str | None]:
    branch = branch or config.LEDGER_BRANCH
    r = _call("GET", f"/repos/{config.GITHUB_REPO}/contents/{p}", params={"ref": branch})
    if r.status_code == 404:
        return None, None
    if r.status_code != 200:
        raise GhStoreError(f"odczyt z GitHuba nie powiódł się (HTTP {r.status_code})")
    data = r.json()
    if data.get("encoding") != "base64" or data.get("content") is None:
        raise GhStoreError("GitHub nie zwrócił treści pliku (zbyt duży?)")
    return base64.b64decode(data["content"]).decode("utf-8"), data["sha"]


def _ensure_branch(branch: str) -> None:
    if _call("GET", f"/repos/{config.GITHUB_REPO}/git/ref/heads/{branch}").status_code == 200:
        return
    repo = _call("GET", f"/repos/{config.GITHUB_REPO}")
    if repo.status_code != 200:
        raise GhStoreError(f"nie znaleziono repo {config.GITHUB_REPO} (HTTP {repo.status_code})")
    default = repo.json()["default_branch"]
    ref = _call("GET", f"/repos/{config.GITHUB_REPO}/git/ref/heads/{default}")
    made = _call("POST", f"/repos/{config.GITHUB_REPO}/git/refs",
                 json={"ref": f"refs/heads/{branch}", "sha": ref.json()["object"]["sha"]})
    if made.status_code not in (200, 201, 422):
        raise GhStoreError(f"nie udało się utworzyć gałęzi {branch} (HTTP {made.status_code})")


def push(text: str, p: str, message: str, branch: str | None = None) -> None:
    branch = branch or config.LEDGER_BRANCH
    _ensure_branch(branch)
    _, sha = pull(p, branch)
    body = {"message": message, "content": base64.b64encode(text.encode("utf-8")).decode(), "branch": branch}
    if sha:
        body["sha"] = sha
    r = _call("PUT", f"/repos/{config.GITHUB_REPO}/contents/{p}", json=body)
    if r.status_code not in (200, 201):
        raise GhStoreError(f"zapis do GitHuba nie powiódł się (HTTP {r.status_code})")


def _canonical(text: str | None) -> str:
    if not text or not text.strip():
        return ""
    return pd.read_csv(io.StringIO(text)).drop(columns=["logged_at", "updated_at"], errors="ignore").to_csv(index=False)


def sync_down(kind: str, importer) -> int:
    text, _ = pull(path(kind))
    return importer(text) if text else 0


def sync_up(kind: str, exporter, label: str) -> str:
    local, n = exporter()
    remote, _ = pull(path(kind))
    if _canonical(remote) == _canonical(local):
        return f"bez zmian ({n} {label})"
    push(local, path(kind), message=f"tennis {kind}: {n} {label}")
    return f"zapisano {n} {label}"
