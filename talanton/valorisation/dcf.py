"""DCF : actualisation des flux de trésorerie disponibles.

Deux valeurs terminales sont calculées côte à côte : croissance perpétuelle
(Gordon-Shapiro) et multiple de sortie. La première année est proratisée :
seule la fraction de l'exercice postérieure à la date de valorisation compte.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..modele.hypotheses import Hypotheses
from ..modele.projections import Projection


@dataclass
class Dcf:
    fcf: list[float]                 # flux disponibles, exercices entiers
    fraction: float                  # part du premier exercice restant à courir
    poids: list[float]
    temps: list[float]               # durées d'actualisation, en années
    facteurs: list[float]
    somme_fcf: float                 # flux actualisés
    temps_fin: float                 # durée jusqu'à la fin du dernier exercice
    vt_gordon: float
    vt_gordon_act: float
    ve_gordon: float
    vt_multiple: float
    vt_multiple_act: float
    ve_multiple: float
    cp_gordon: float
    cp_multiple: float
    action_gordon: float
    action_multiple: float

    @property
    def part_vt_gordon(self) -> float:
        return self.vt_gordon_act / self.ve_gordon

    @property
    def part_vt_multiple(self) -> float:
        return self.vt_multiple_act / self.ve_multiple


def flux_disponibles(proj: Projection, hyp: Hypotheses) -> list[float]:
    return [e * (1 - hyp.taux_is) + d - c - v
            for e, d, c, v in zip(proj.ebit, proj.da, proj.capex, proj.var_bfr)]


def calendrier(proj: Projection, hyp: Hypotheses) -> tuple[float, list[float], list[float], float]:
    """Renvoie (fraction, poids, durées d'actualisation, durée jusqu'à la fin du plan)."""
    n = hyp.n
    f = max(0.0, min(1.0, (proj.fins[0] - hyp.date_valo).days / 365))
    c = hyp.mi_annee
    poids = [f] + [1.0] * (n - 1)
    temps = [f * (1 - 0.5 * c)] + [f + (k - 1) - 0.5 * c for k in range(2, n + 1)]
    return f, poids, temps, f + n - 1


def valeur_par_action(ve: float, hyp: Hypotheses) -> float:
    return (ve - hyp.passage) / hyp.actions_diluees


def ve_gordon(fcf, poids, temps, wacc: float, g: float) -> float:
    """Valeur d'entreprise, méthode de la croissance perpétuelle (sert aussi aux sensibilités)."""
    somme = sum(x * p / (1 + wacc) ** t for x, p, t in zip(fcf, poids, temps))
    return somme + fcf[-1] * (1 + g) / (wacc - g) / (1 + wacc) ** temps[-1]


def ve_multiple(fcf, poids, temps, temps_fin: float, ebitda_fin: float, wacc: float, multiple: float) -> float:
    """Valeur d'entreprise, méthode du multiple de sortie (sert aussi aux sensibilités)."""
    somme = sum(x * p / (1 + wacc) ** t for x, p, t in zip(fcf, poids, temps))
    return somme + ebitda_fin * multiple / (1 + wacc) ** temps_fin


def calculer_dcf(proj: Projection, hyp: Hypotheses) -> Dcf:
    fcf = flux_disponibles(proj, hyp)
    f, poids, temps, temps_fin = calendrier(proj, hyp)
    w, g = hyp.wacc, hyp.croissance_perpetuelle
    facteurs = [(1 + w) ** -t for t in temps]
    somme = sum(x * p * a for x, p, a in zip(fcf, poids, facteurs))
    vt_g = fcf[-1] * (1 + g) / (w - g)
    vt_g_act = vt_g * facteurs[-1]
    vt_m = proj.ebitda[-1] * hyp.multiple_sortie_dcf
    vt_m_act = vt_m / (1 + w) ** temps_fin
    ve_g, ve_m = somme + vt_g_act, somme + vt_m_act
    return Dcf(
        fcf=fcf, fraction=f, poids=poids, temps=temps, facteurs=facteurs, somme_fcf=somme,
        temps_fin=temps_fin, vt_gordon=vt_g, vt_gordon_act=vt_g_act, ve_gordon=ve_g,
        vt_multiple=vt_m, vt_multiple_act=vt_m_act, ve_multiple=ve_m,
        cp_gordon=ve_g - hyp.passage, cp_multiple=ve_m - hyp.passage,
        action_gordon=valeur_par_action(ve_g, hyp), action_multiple=valeur_par_action(ve_m, hyp),
    )
