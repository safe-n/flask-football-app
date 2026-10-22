"""Dopasowanie nazw drużyn między źródłami (np. 'Manchester City FC' -> 'Man City').

Obie strony przechodzą tę samą normalizację (małe litery, bez akcentów i dodatków typu FC/AFC/1899),
potem tabela synonimów dla klubów, które football-data.co.uk skraca, a na końcu ostrożne dopasowanie
przez zawieranie słów i podobieństwo. Niejednoznaczne przypadki zwracają None (lepiej brak niż pomyłka).
"""
from __future__ import annotations

import difflib
import re
import unicodedata

STOP = {"fc", "afc", "cf", "sc", "ac", "as", "ssc", "rc", "rcd", "cd", "ud", "sv", "fk", "vfb", "vfl", "tsg", "fsv",
        "bv", "ca", "us", "ss", "sl", "bc", "cfc", "acf", "ogc", "hsc", "club", "de", "del", "la", "le", "the", "calcio",
        "hotspur", "futbol", "balompie", "clube"}
GENERIC = {"city", "united", "town", "albion", "rovers", "county", "athletic", "real", "sporting", "atletico", "sp", "st",
           "rb", "borussia", "olympique", "stade", "dynamo", "inter"}

# formalna nazwa (football-data.org i inne) -> skrót używany przez football-data.co.uk
_SYN_RAW = {
    "Manchester City": "Man City", "Manchester United": "Man United", "Nottingham Forest": "Nott'm Forest",
    "Brighton and Hove Albion": "Brighton", "Newcastle United": "Newcastle", "West Ham United": "West Ham",
    "Leeds United": "Leeds", "Leicester City": "Leicester", "Norwich City": "Norwich", "Wolverhampton Wanderers": "Wolves",
    "Ipswich Town": "Ipswich", "Hull City": "Hull", "Coventry City": "Coventry", "West Bromwich Albion": "West Brom",
    "Queens Park Rangers": "QPR", "Cardiff City": "Cardiff", "Swansea City": "Swansea", "Stoke City": "Stoke",
    "Birmingham City": "Birmingham", "Blackburn Rovers": "Blackburn", "Preston North End": "Preston",
    "Sheffield Wednesday": "Sheffield Weds", "Derby County": "Derby", "Luton Town": "Luton", "Oxford United": "Oxford",
    "Plymouth Argyle": "Plymouth", "Huddersfield Town": "Huddersfield", "Bayern Munchen": "Bayern Munich",
    "Borussia Dortmund": "Dortmund", "Borussia Monchengladbach": "M'gladbach", "Bayer Leverkusen": "Leverkusen",
    "Eintracht Frankfurt": "Ein Frankfurt", "Hamburger": "Hamburg", "Atletico Madrid": "Ath Madrid",
    "Athletic": "Ath Bilbao", "Real Sociedad": "Sociedad", "Real Betis": "Betis", "Celta Vigo": "Celta",
    "Rayo Vallecano Madrid": "Vallecano", "Espanyol Barcelona": "Espanol", "Deportivo Alaves": "Alaves",
    "Real Valladolid": "Valladolid", "Real Oviedo": "Oviedo", "Hellas Verona": "Verona", "Internazionale Milano": "Inter",
    "Paris Saint Germain": "Paris SG", "Olympique Marseille": "Marseille", "Olympique Lyonnais": "Lyon",
    "Stade Rennais": "Rennes", "Stade Brestois": "Brest", "Strasbourg Alsace": "Strasbourg", "Stade Reims": "Reims",
    "PSV Eindhoven": "PSV", "Feyenoord Rotterdam": "Feyenoord", "Sporting Portugal": "Sp Lisbon", "Sporting": "Sp Lisbon",
    "Braga": "Sp Braga", "Vitoria Guimaraes": "Guimaraes", "Atalanta": "Atalanta", "Real Madrid": "Real Madrid",
    "Union Saint Gilloise": "St. Gilloise", "Club Brugge": "Club Brugge", "Red Bull Salzburg": "Salzburg",
    "Shakhtar Donetsk": "Shakhtar", "Dinamo Zagreb": "Dinamo Zagreb", "Young Boys": "Young Boys",
    "Slavia Praha": "Slavia Prague", "Sparta Praha": "Sparta Prague", "Crvena Zvezda": "Crvena Zvezda",
}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower().replace("&", " and ")
    toks = [t for t in re.sub(r"[^a-z0-9]+", " ", s).split() if t not in STOP and not t.isdigit()]
    return " ".join(toks)


SYN = {norm(k): norm(v) for k, v in _SYN_RAW.items()}


def key(s: str) -> str:
    n = norm(s)
    return SYN.get(n, n)


def resolve(candidates: list[str] | str, known: list[str] | set[str]) -> str | None:
    """Zwraca nazwę z `known` pasującą do którejś z `candidates` albo None."""
    cands = [candidates] if isinstance(candidates, str) else [c for c in candidates if c]
    keys = {key(k): k for k in known}
    for c in cands:                                                     # 1. dokładne po normalizacji/synonimach
        if key(c) in keys:
            return keys[key(c)]
    for c in cands:                                                     # 2. zawieranie słów (ostrożnie)
        ct = set(key(c).split())
        hits = []
        for kk, orig in keys.items():
            kt = set(kk.split())
            small, big = (ct, kt) if len(ct) <= len(kt) else (kt, ct)
            if small and small <= big and (small - GENERIC):
                hits.append(orig)
        if len(hits) == 1:
            return hits[0]
    for c in cands:                                                     # 3. podobieństwo napisów
        best = difflib.get_close_matches(key(c), list(keys), n=2, cutoff=0.85)
        if len(best) == 1 or (len(best) == 2 and difflib.SequenceMatcher(None, key(c), best[0]).ratio()
                              - difflib.SequenceMatcher(None, key(c), best[1]).ratio() > 0.05):
            return keys[best[0]]
    return None
