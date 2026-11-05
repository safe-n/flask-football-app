"""Starter kopii lokalnej: pobierz najnowszy kod z GitHuba -> doinstaluj biblioteki -> uruchom aplikację; powtórz po „restarcie”.

Przycisk „Aktualizuj i zrestartuj” (strona /restart) kończy serwer kodem RESTART_CODE - wtedy ta pętla robi `git pull`
i startuje aplikację od nowa. Każde inne zakończenie (zamknięcie okna, Ctrl+C, błąd) kończy pętlę.

Git: używamy gita wbudowanego w GitHub Desktop (osobny git nie jest potrzebny); gdy go brak - git z PATH; gdy i tego brak,
aplikacja startuje bez aktualizacji. Pętla jest w Pythonie, a nie w .bat, bo cmd czyta plik .bat w trakcie działania
i podmiana go przez `git pull` mogłaby wykonać przypadkowy fragment.
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESTART_CODE = 3
PORT = os.getenv("PORT", "5000")


def find_git() -> str | None:
    pattern = os.path.expandvars(r"%LOCALAPPDATA%\GitHubDesktop\app-*\resources\app\git\cmd\git.exe")

    def ver(p):  # app-3.4.10 > app-3.4.9
        m = re.search(r"app-([\d.]+)", p)
        return tuple(int(x) for x in m.group(1).split(".") if x.isdigit()) if m else ()
    found = sorted(glob.glob(pattern), key=ver)
    return found[-1] if found else shutil.which("git")


def git(g: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([g, "-C", str(ROOT), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")


def update(g: str | None) -> str:
    """git pull --ff-only; zwraca skrót commita, na którym startujemy."""
    if not g:
        print("[!] Nie znalazłem gita (GitHub Desktop) - startuję bez pobierania zmian.")
        return ""
    before = git(g, "rev-parse", "--short", "HEAD").stdout.strip()
    print("Pobieram najnowszy kod z GitHuba...")
    r = git(g, "pull", "--ff-only")
    after = git(g, "rev-parse", "--short", "HEAD").stdout.strip()
    if r.returncode != 0:
        print("[!] Nie udało się pobrać zmian - startuję dotychczasową wersję.")
        print("    Najczęściej: zmienione pliki w folderze repo. Otwórz GitHub Desktop i sprawdź zakładkę Changes.")
        print("    " + (r.stderr or r.stdout).strip().replace("\n", "\n    "))
    elif before != after:
        print(f"Zaktualizowano: {before} -> {after}")
        log = git(g, "log", "--oneline", f"{before}..{after}").stdout.strip()
        if log:
            print("    " + log.replace("\n", "\n    "))
    else:
        print(f"Kod aktualny ({after}).")
    return after


def main() -> int:
    g = find_git()
    env = os.environ.copy()
    env["LOCAL_RESTART"] = "1"           # włącza przycisk /restart (na Renderze go nie ma)
    env["LOCAL_RESTART_CODE"] = str(RESTART_CODE)
    while True:
        commit = update(g)
        if commit:
            env["RENDER_GIT_COMMIT"] = commit   # tylko do wyświetlenia „commit …” w nagłówku tenisa
        print("Sprawdzam biblioteki...")
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                        "-r", "requirements.txt", "waitress"], cwd=ROOT)
        name = os.getenv("COMPUTERNAME", "NAZWA-KOMPUTERA")
        print(f"\nAplikacja startuje. Na tym komputerze:  http://localhost:{PORT}   (tenis: /tennis/)")
        print(f"Z telefonu przez Tailscale:            http://{name}:{PORT}   (tenis: /tennis/)")
        print(f"Aktualizacja i restart zdalnie:        http://{name}:{PORT}/restart")
        print("Zamknięcie tego okna = wyłączenie aplikacji.\n")
        rc = subprocess.call([sys.executable, "-m", "waitress", "--host=0.0.0.0", f"--port={PORT}", "--threads=6",
                              "combo:app"], cwd=ROOT, env=env)
        if rc != RESTART_CODE:
            return rc
        print("\n=== Restart na żądanie: pobieram zmiany i uruchamiam ponownie ===\n")


if __name__ == "__main__":
    sys.exit(main())
