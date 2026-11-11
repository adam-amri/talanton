"""Sélection des bons chiffres dans le document « companyfacts » de la SEC.

Un même chiffre y figure plusieurs fois : l'exercice 2024 apparaît dans le 10-K
2024, puis comme comparatif dans ceux de 2025 et 2026. Les champs `fy` et `fp`
décrivent le dépôt, pas la période du chiffre : on ne s'y fie donc jamais.
Toutes les règles ci-dessous raisonnent sur les dates de début et de fin.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

JOURS_ANNEE_MIN, JOURS_ANNEE_MAX = 350, 380   # exercices de 52 ou 53 semaines compris
TOLERANCE_J = 10


@dataclass(frozen=True)
class Fait:
    balise: str
    unite: str
    debut: date | None      # None pour un chiffre de bilan (instantané)
    fin: date
    valeur: float
    formulaire: str
    depose: date
    depot: str              # numéro d'accession SEC, pour la traçabilité

    @property
    def jours(self) -> int | None:
        return None if self.debut is None else (self.fin - self.debut).days

    @property
    def annuel(self) -> bool:
        return (self.debut is not None and self.formulaire == "10-K"
                and JOURS_ANNEE_MIN <= self.jours <= JOURS_ANNEE_MAX)


class Faits:
    """Accès aux faits d'une société, par balise."""

    FORMULAIRES = ("10-K", "10-Q")

    def __init__(self, brut: dict):
        self.nom: str = brut.get("entityName", "")
        self.cik: int = int(brut.get("cik", 0))
        self._brut = brut.get("facts", {})
        self._cache: dict[tuple[str, str], list[Fait]] = {}

    def liste(self, balise: str, espace: str = "us-gaap") -> list[Fait]:
        cle = (espace, balise)
        if cle not in self._cache:
            faits: list[Fait] = []
            noeud = self._brut.get(espace, {}).get(balise)
            if noeud:
                for unite, lignes in noeud.get("units", {}).items():
                    for e in lignes:
                        if e.get("form") not in self.FORMULAIRES:
                            continue
                        faits.append(Fait(
                            balise=balise, unite=unite,
                            debut=date.fromisoformat(e["start"]) if e.get("start") else None,
                            fin=date.fromisoformat(e["end"]), valeur=float(e["val"]),
                            formulaire=e["form"], depose=date.fromisoformat(e["filed"]),
                            depot=e.get("accn", ""),
                        ))
            self._cache[cle] = faits
        return self._cache[cle]

    def existe(self, balise: str) -> bool:
        return bool(self.liste(balise))

    # -- calendrier ---------------------------------------------------------
    def exercices(self, balises_reperes: tuple[str, ...]) -> list[tuple[date, date]]:
        """Liste chronologique des exercices publiés : (début, fin)."""
        vus: dict[date, date] = {}
        for b in balises_reperes:
            for f in self.liste(b):
                if f.annuel:
                    vus[f.fin] = f.debut
        return [(vus[fin], fin) for fin in sorted(vus)]

    def dernier_trimestre(self, balises_reperes: tuple[str, ...], fin_exercice: date) -> date | None:
        """Fin du dernier trimestre publié après la clôture annuelle (None s'il n'y en a pas)."""
        fins = [f.fin for b in balises_reperes for f in self.liste(b)
                if f.formulaire == "10-Q" and f.fin > fin_exercice]
        return max(fins) if fins else None

    # -- lecture d'une valeur -----------------------------------------------
    @staticmethod
    def _plus_recent(candidats: list[Fait]) -> Fait | None:
        """Parmi plusieurs publications d'un même chiffre, garde la dernière déposée."""
        return max(candidats, key=lambda f: f.depose) if candidats else None

    def annuel(self, balise: str, fin: date) -> Fait | None:
        return self._plus_recent([f for f in self.liste(balise) if f.annuel and f.fin == fin])

    def instant(self, balise: str, fin: date) -> Fait | None:
        return self._plus_recent([f for f in self.liste(balise) if f.debut is None and f.fin == fin])

    def cumul(self, balise: str, debut_exercice: date, fin: date) -> Fait | None:
        """Cumul depuis le début de l'exercice jusqu'à `fin` (6 mois, 9 mois...).

        Un 10-Q donne à la fois le trimestre seul et le cumul : on exige que le
        chiffre parte bien du début de l'exercice, sinon on ne renvoie rien.
        """
        candidats = [f for f in self.liste(balise)
                     if f.debut is not None and f.fin == fin and f.jours < JOURS_ANNEE_MIN
                     and abs((f.debut - debut_exercice).days) <= TOLERANCE_J]
        return self._plus_recent(candidats)

    def cumul_precedent(self, balise: str, debut_exercice_precedent: date, fin: date) -> Fait | None:
        """Même cumul un an plus tôt (fin à environ 365 jours de `fin`)."""
        cible = fin - timedelta(days=365)
        candidats = [f for f in self.liste(balise)
                     if f.debut is not None and f.jours < JOURS_ANNEE_MIN
                     and abs((f.fin - cible).days) <= TOLERANCE_J
                     and abs((f.debut - debut_exercice_precedent).days) <= TOLERANCE_J]
        return self._plus_recent(candidats)
