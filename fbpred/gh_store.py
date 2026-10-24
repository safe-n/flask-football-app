"""Trwały dziennik prognoz bez GitHub Actions: plik CSV w osobnej gałęzi repo, zapisywany przez GitHub REST API.

Po co: SQLite na darmowym Renderze znika przy każdym restarcie/uśpieniu. Aplikacja po zapisaniu prognoz wysyła `predictions.csv`
do gałęzi `ledger-data` (commit tylko gdy treść faktycznie się zmieniła), a przy starcie wczytuje go z powrotem.
Gałąź jest osobna, więc commity NIE wywołują przebudowy serwisu. Token: wyłącznie ze zmiennej środowiskowej.
"""
from __future__ import annotations

import base64
import io
import tempfile
from pathlib import Path

import pandas as pd
import requests

from . import config, ledger

API = "https://api.github.com"


class GhStoreError(RuntimeError):
    pass


def enabled() -> bool:
    return bool(config.GITHUB_TOKEN and config.GITHUB_REPO)


def _call(method: str, path: str, **kw):
    headers = {"Authorization": f"Bearer {config.GITHUB_TOKEN}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "fbpred"}
    r = requests.request(method, API + path, headers=headers, timeout=30, **kw)
    if r.status_code in (401, 403):
        raise GhStoreError(f"GitHub odrzucił token ({r.status_code}) - sprawdź, czy ma uprawnienie 'Contents: Read and write' "
                           f"do repo {config.GITHUB_REPO} i czy nie wygasł")
    return r


def pull(path: str | None = None, branch: str | None = None) -> tuple[str | None, str | None]:
    """(treść pliku, sha) albo (None, None), gdy pliku lub gałęzi jeszcze nie ma."""
    path, branch = path or config.LEDGER_REMOTE_PATH, branch or config.LEDGER_BRANCH
    r = _call("GET", f"/repos/{config.GITHUB_REPO}/contents/{path}", params={"ref": branch})
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
    if ref.status_code != 200:
        raise GhStoreError(f"nie znaleziono gałęzi {default} (HTTP {ref.status_code})")
    made = _call("POST", f"/repos/{config.GITHUB_REPO}/git/refs",
                 json={"ref": f"refs/heads/{branch}", "sha": ref.json()["object"]["sha"]})
    if made.status_code not in (200, 201, 422):  # 422 = ktoś właśnie utworzył
        raise GhStoreError(f"nie udało się utworzyć gałęzi {branch} (HTTP {made.status_code})")


def push(text: str, path: str | None = None, branch: str | None = None, message: str = "ledger: aktualizacja") -> None:
    path, branch = path or config.LEDGER_REMOTE_PATH, branch or config.LEDGER_BRANCH
    _ensure_branch(branch)
    _, sha = pull(path, branch)
    body = {"message": message, "content": base64.b64encode(text.encode("utf-8")).decode(), "branch": branch}
    if sha:
        body["sha"] = sha
    r = _call("PUT", f"/repos/{config.GITHUB_REPO}/contents/{path}", json=body)
    if r.status_code not in (200, 201):
        raise GhStoreError(f"zapis do GitHuba nie powiódł się (HTTP {r.status_code})")


def _canonical(text: str | None) -> str:
    """CSV bez kolumny logged_at - sam znacznik czasu nie jest powodem do nowego commita."""
    if not text:
        return ""
    return pd.read_csv(io.StringIO(text)).drop(columns=["logged_at"], errors="ignore").to_csv(index=False)


def sync_down(conn) -> int:
    """Wczytuje dziennik z GitHuba do bazy (istniejące wiersze mają pierwszeństwo). Zwraca liczbę wczytanych prognoz."""
    text, _ = pull()
    if not text:
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "p.csv"
        f.write_text(text, encoding="utf-8")
        return ledger.import_csv(conn, f)


def sync_up(conn) -> str:
    """Wysyła dziennik do GitHuba tylko, gdy zmieniła się jego treść. Zwraca opis wyniku."""
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "p.csv"
        n = ledger.export_csv(conn, f)
        local = f.read_text(encoding="utf-8")
    if n == 0:
        return "nic do zapisania (dziennik pusty)"
    remote, _ = pull()
    if _canonical(remote) == _canonical(local):
        return f"bez zmian ({n} prognoz)"
    push(local, message=f"ledger: {n} prognoz")
    return f"zapisano {n} prognoz w gałęzi {config.LEDGER_BRANCH}"
