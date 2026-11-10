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
FILES = {"predictions": "predictions.csv", "bets": "bets.csv", "manual": "upcoming_manual.csv", "picks": "picks.csv", "coupons": "coupons.csv"}


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


def check() -> tuple[bool, str]:
    """Czy token widzi repo i może do niego pisać - czytelny opis do zakładki Dane (bez ujawniania tokenu)."""
    try:
        r = _call("GET", f"/repos/{config.GITHUB_REPO}")
    except GhStoreError as e:
        return False, str(e)
    except requests.RequestException as e:
        return False, f"brak połączenia z GitHubem: {e}"
    if r.status_code == 404:
        return False, (f"token nie widzi repo „{config.GITHUB_REPO}” - sprawdź GITHUB_REPO (ma być safe-n/flask-football-app) "
                       f"i czy token ma dostęp do tego repo")
    if config.GITHUB_REPO_RAW != config.GITHUB_REPO:
        return True, (f"token OK, repo {config.GITHUB_REPO} - UWAGA: zmienna GITHUB_REPO zawiera dodatkowe znaki "
                      f"({config.GITHUB_REPO_RAW!r}); popraw ją w Render → Environment (dla piłki też)")
    if r.status_code != 200:
        return False, f"GitHub odpowiedział HTTP {r.status_code}"
    perm = (r.json().get("permissions") or {})
    if perm and not perm.get("push"):
        return False, f"token widzi {config.GITHUB_REPO}, ale nie może zapisywać - nadaj mu „Contents: Read and write”"
    return True, f"token OK, repo {config.GITHUB_REPO}"


def git_sha(text: str) -> str:
    """Sha pliku liczone jak w gicie - pozwala pominąć wysyłkę, gdy treść się nie zmieniła."""
    import hashlib
    raw = text.encode("utf-8")
    return hashlib.sha1(b"blob %d\0" % len(raw) + raw).hexdigest()


def list_dir(p: str, branch: str | None = None) -> dict[str, str]:
    """{nazwa pliku: sha} w folderze gałęzi (pusty słownik, gdy folderu nie ma)."""
    branch = branch or config.LEDGER_BRANCH
    r = _call("GET", f"/repos/{config.GITHUB_REPO}/contents/{p}", params={"ref": branch})
    if r.status_code == 404:
        return {}
    if r.status_code != 200:
        raise GhStoreError(f"odczyt folderu {p} z GitHuba nie powiódł się (HTTP {r.status_code})")
    return {x["name"]: x["sha"] for x in r.json() if x.get("type") == "file"}


def pull_raw(p: str, branch: str | None = None) -> str | None:
    """Treść pliku bez limitu 1 MB (format surowy)."""
    branch = branch or config.LEDGER_BRANCH
    headers = {"Authorization": f"Bearer {config.GITHUB_TOKEN}", "Accept": "application/vnd.github.raw",
               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "tnpred"}
    r = requests.get(API + f"/repos/{config.GITHUB_REPO}/contents/{p}", params={"ref": branch}, headers=headers, timeout=60)
    if r.status_code == 404:
        return None
    if r.status_code in (401, 403):
        raise GhStoreError(f"GitHub odrzucił token ({r.status_code})")
    if r.status_code != 200:
        raise GhStoreError(f"odczyt {p} z GitHuba nie powiódł się (HTTP {r.status_code})")
    r.encoding = "utf-8"
    return r.text


HISTORY_DIR = "history"


def history_path(name: str = "") -> str:
    return config.LEDGER_PREFIX + HISTORY_DIR + ("/" + name if name else "")


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
