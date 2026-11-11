"""Projection des trois états financiers (compte de résultat, flux, bilan).

Cas « société seule », sans opération : la dette reste constante et la
trésorerie absorbe les flux. Le bilan projeté s'équilibre par construction ;
l'onglet Contrôles du classeur et les tests le vérifient.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date

from ..retraitement.etats import Societe
from .hypotheses import Hypotheses


def edate(d: date, mois: int) -> date:
    """Équivalent de la fonction EDATE d'Excel : même jour, `mois` plus tard."""
    total = d.month - 1 + mois
    annee, m = d.year + total // 12, total % 12 + 1
    return date(annee, m, min(d.day, calendar.monthrange(annee, m)[1]))


@dataclass
class Projection:
    fins: list[date]                 # fins des exercices projetés
    ca: list[float]
    ebitda: list[float]
    da: list[float]
    ebit: list[float]
    interets: list[float]
    produits_fin: list[float]
    rai: list[float]
    impot: list[float]
    rn: list[float]
    capex: list[float]
    bfr: list[float]
    var_bfr: list[float]
    var_treso: list[float]
    tresorerie: list[float]
    actif_circ_expl: list[float]
    immo_nettes: list[float]
    passif_expl: list[float]
    capitaux_propres: list[float]
    total_actif: list[float]
    total_passif: list[float]
    # postes constants
    dette: float
    goodwill: float
    autres_actifs: float
    autres_passifs: float


def projeter(soc: Societe, hyp: Hypotheses) -> Projection:
    d = soc.dernier
    dette, goodwill = d["dette"], d["goodwill"]
    autres_actifs, autres_passifs = d["autres_actifs"], d["autres_passifs"]
    ca_p, treso_p, bfr_p, immo_p, cp_p = d["ca"], d["tresorerie"], d["bfr"], d["immo_nettes"], d["capitaux_propres"]
    fin_p = soc.exercices[-1]
    p = Projection(*[[] for _ in range(21)], dette=dette, goodwill=goodwill,
                   autres_actifs=autres_actifs, autres_passifs=autres_passifs)
    for t in range(hyp.n):
        ca = ca_p * (1 + hyp.croissance[t])
        ebitda = ca * hyp.marge_ebitda[t]
        da = ca * hyp.da_pct[t]
        ebit = ebitda - da
        interets = dette * hyp.cout_dette
        produits = treso_p * hyp.rendement_treso
        rai = ebit - interets + produits
        impot = max(0.0, rai) * hyp.taux_is
        rn = rai - impot
        capex = ca * hyp.capex_pct[t]
        bfr = ca * hyp.bfr_pct[t]
        var_bfr = bfr - bfr_p
        var_treso = rn + da - var_bfr - capex - hyp.distributions[t]
        treso = treso_p + var_treso
        passif_expl = ca * hyp.passif_expl_pct
        actif_circ = bfr + passif_expl
        immo = immo_p + capex - da
        cp = cp_p + rn - hyp.distributions[t]
        fin = edate(fin_p, 12)
        for nom, valeur in (
            ("fins", fin), ("ca", ca), ("ebitda", ebitda), ("da", da), ("ebit", ebit),
            ("interets", interets), ("produits_fin", produits), ("rai", rai), ("impot", impot),
            ("rn", rn), ("capex", capex), ("bfr", bfr), ("var_bfr", var_bfr),
            ("var_treso", var_treso), ("tresorerie", treso), ("actif_circ_expl", actif_circ),
            ("immo_nettes", immo), ("passif_expl", passif_expl), ("capitaux_propres", cp),
            ("total_actif", treso + actif_circ + immo + goodwill + autres_actifs),
            ("total_passif", passif_expl + dette + autres_passifs + cp),
        ):
            getattr(p, nom).append(valeur)
        ca_p, treso_p, bfr_p, immo_p, cp_p, fin_p = ca, treso, bfr, immo, cp, fin
    return p
