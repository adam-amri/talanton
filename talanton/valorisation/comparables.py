"""Comparables boursiers : multiples des pairs et valeur implicite de la cible.

Un multiple n'est retenu que s'il a un sens : dénominateur positif et résultat
inférieur à un plafond. Sinon il est noté « n.s. » et ignoré par les statistiques.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..collecte.marche import Cours
from ..modele.hypotheses import Hypotheses
from ..retraitement.etats import Societe

MULTIPLES = ("ve_ca", "ve_ebitda", "ve_ebit", "per")


@dataclass
class Comparable:
    societe: Societe
    cours: Cours

    @property
    def capitalisation(self) -> float:
        return self.cours.cours * self.societe.actions

    @property
    def valeur_entreprise(self) -> float:
        b = self.societe.bilan
        return self.capitalisation + b["dette"] - b["tresorerie"] + b["minoritaires"]

    def multiple(self, nom: str, plafond: float) -> float | None:
        ltm = self.societe.ltm
        if nom == "ve_ca":
            return self.valeur_entreprise / ltm["ca"] if ltm["ca"] and ltm["ca"] > 0 else None
        numerateur, denominateur = {
            "ve_ebitda": (self.valeur_entreprise, ltm["ebitda_ajuste"]),
            "ve_ebit": (self.valeur_entreprise, ltm["ebit_ajuste"]),
            "per": (self.capitalisation, ltm["rn_ajuste"]),
        }[nom]
        if denominateur is None or denominateur <= 0:
            return None
        m = numerateur / denominateur
        return m if m <= plafond else None


def quartile(valeurs: list[float], q: float) -> float | None:
    """Quartile par interpolation linéaire, comme QUARTILE / MEDIANE dans Excel."""
    v = sorted(valeurs)
    if not v:
        return None
    pos = (len(v) - 1) * q
    bas = int(pos)
    haut = min(bas + 1, len(v) - 1)
    return v[bas] + (v[haut] - v[bas]) * (pos - bas)


@dataclass
class Comparables:
    pairs: list[Comparable]
    plafond: float
    stats: dict[str, dict[str, float | None]] = field(default_factory=dict)       # multiple -> q1/mediane/q3/min/max
    implicite: dict[str, dict[str, float | None]] = field(default_factory=dict)   # multiple -> valeur par action

    def valeurs(self, nom: str) -> list[float]:
        return [m for p in self.pairs if (m := p.multiple(nom, self.plafond)) is not None]


def calculer_statistiques(pairs: list[Comparable], plafond: float) -> Comparables:
    c = Comparables(pairs=pairs, plafond=plafond)
    for nom in MULTIPLES:
        v = c.valeurs(nom)
        c.stats[nom] = {
            "min": min(v) if v else None, "q1": quartile(v, 0.25), "mediane": quartile(v, 0.5),
            "q3": quartile(v, 0.75), "max": max(v) if v else None,
        }
    return c


def valoriser_cible(c: Comparables, cible: Societe, hyp: Hypotheses) -> None:
    """Applique les multiples des pairs aux agrégats LTM de la cible : valeur par action."""
    agregats = {"ve_ebitda": cible.ltm["ebitda_ajuste"], "ve_ebit": cible.ltm["ebit_ajuste"],
                "per": cible.ltm["rn_ajuste"]}
    for nom, agregat in agregats.items():
        c.implicite[nom] = {}
        for niveau in ("q1", "mediane", "q3"):
            m = c.stats[nom][niveau]
            if m is None or agregat is None:
                c.implicite[nom][niveau] = None
            elif nom == "per":
                c.implicite[nom][niveau] = m * agregat / hyp.actions_diluees
            else:
                c.implicite[nom][niveau] = (m * agregat - hyp.passage) / hyp.actions_diluees
