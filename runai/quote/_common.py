import re
from html import unescape

import httpx

USER_AGENT = "Mozilla/5.0 (RunAI devis, lecture seule)"
TIMEOUT_S = 30.0

CATEGORIES: list[tuple[str, str]] = [
    ("pass_participation", r"tourisme sportif|sport tourism|runcard|\bpass\b|licence"),
    ("assurance_annulation", r"assurance|annulation|insurance|garantie"),
    ("t_shirt", r"t-shirt|tee-shirt|maillot"),
    ("repas", r"repas|pasta|party|dîner|buffet"),
    ("navette", r"navette|\bbus\b|shuttle"),
    ("photos", r"photo"),
    ("don", r"\bdons?\b|charit|solidaire"),
    ("medaille", r"médaille|gravure|medal"),
    (
        "merchandising",
        (
            r"casquette|sweat|veste|chaussette|\bsac\b|gourde|mug|porte-clés|keychain|tour de cou|"
            r"manchette|bag|magnet|gobelet|peluche|tapis|dossard"
        ),
    ),
]


def categorie(nom: str) -> str:
    for cat, pat in CATEGORIES:
        if re.search(pat, nom, re.IGNORECASE):
            return cat
    return "autre"


def html_to_text(s: str | None) -> str:
    s = re.sub(r"<script.*?</script>|<style.*?</style>", " ", s or "", flags=re.DOTALL)
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def eur(x: str) -> float:
    return float(x.replace(",", "."))


def new_client() -> httpx.Client:
    return httpx.Client(
        timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT}, follow_redirects=True
    )


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.casefold().replace("’", "'")).strip()
