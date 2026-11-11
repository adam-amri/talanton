"""LBO : rachat de la société par un fonds, financé en partie par de la dette.

Hypothèses de structure (version 0.1) :
  - l'opération est bouclée à la fin de l'exercice en cours (année 1 du plan) ;
  - le fonds détient la société cinq ans et la revend à la fin du plan ;
  - une seule tranche de dette, à taux fixe, remboursée par un amortissement
    contractuel puis par la trésorerie excédentaire (cash sweep) ;
  - les intérêts sont calculés sur la dette de début d'année (pas de circularité) ;
  - les frais sont passés en charge à la clôture.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..modele.hypotheses import Hypotheses
from ..modele.projections import Projection
from ..retraitement.etats import Societe

DUREE = 5


@dataclass
class Lbo:
    # entrée
    prix_offre: float
    cp_acquis: float
    dette_refinancee: float
    treso_cloture: float
    dette_nette_entree: float        # dette refinancée - trésorerie + minoritaires
    ve_entree: float
    multiple_entree: float           # VE / EBITDA ajusté LTM
    # financement
    nouvelle_dette: float
    frais_transaction: float
    frais_financement: float
    total_emplois: float
    equity_sponsor: float
    # plan (cinq exercices après la clôture)
    interets: list[float]
    rn: list[float]
    fcf: list[float]
    amortissement: list[float]
    sweep: list[float]
    dette_fin: list[float]
    treso_fin: list[float]
    # sortie
    multiple_sortie: float
    ve_sortie: float
    equity_sortie: float
    moic: float
    tri: float
    # prix maximum par action pour un TRI cible
    prix_max: dict[float, float]


def _plan_dette(proj: Projection, hyp: Hypotheses, dette_initiale: float):
    interets, rns, fcfs, amorts, sweeps, dettes, tresos = [], [], [], [], [], [], []
    dette, treso = dette_initiale, hyp.treso_min
    for k in range(1, DUREE + 1):                 # exercices 2 à 6 du plan
        i = k                                      # index dans la projection (0 = année de clôture)
        interet = dette * hyp.taux_lbo
        rai = proj.ebit[i] - interet
        rn = rai - max(0.0, rai) * hyp.taux_is
        fcf = rn + proj.da[i] - proj.capex[i] - proj.var_bfr[i]
        amort = min(dette, dette_initiale * hyp.amort_pct)
        sweep = max(0.0, min(dette - amort, (fcf - amort) * hyp.sweep_pct))
        treso = treso + fcf - amort - sweep
        dette = dette - amort - sweep
        for liste, v in ((interets, interet), (rns, rn), (fcfs, fcf), (amorts, amort),
                         (sweeps, sweep), (dettes, dette), (tresos, treso)):
            liste.append(v)
    return interets, rns, fcfs, amorts, sweeps, dettes, tresos


def equity_sponsor(cp_acquis: float, hyp: Hypotheses, constante: float) -> float:
    """Mise du fonds en fonction du prix payé pour les actions (relation linéaire)."""
    return (1 + hyp.frais_transaction) * cp_acquis + constante


def calculer_lbo(soc: Societe, proj: Projection, hyp: Hypotheses) -> Lbo:
    if hyp.n < DUREE + 1:
        raise ValueError("Le LBO demande au moins six exercices projetés.")
    ebitda_ltm = soc.ltm["ebitda_ajuste"]
    prix = hyp.cours * (1 + hyp.prime_acquisition)
    cp_acquis = prix * hyp.actions_diluees
    dette_refi, treso_cloture = proj.dette, proj.tresorerie[0]
    dette_nette = dette_refi - treso_cloture + hyp.minoritaires + hyp.autres_ajustements
    ve = cp_acquis + dette_nette
    nouvelle_dette = hyp.levier * ebitda_ltm
    frais_tx = hyp.frais_transaction * ve
    frais_fin = hyp.frais_financement * nouvelle_dette
    emplois = cp_acquis + dette_refi + frais_tx + frais_fin + hyp.treso_min
    sponsor = emplois - nouvelle_dette - treso_cloture

    interets, rns, fcfs, amorts, sweeps, dettes, tresos = _plan_dette(proj, hyp, nouvelle_dette)

    multiple_entree = ve / ebitda_ltm
    multiple_sortie = multiple_entree + hyp.ecart_multiple_sortie
    ebitda_sortie = proj.ebitda[DUREE]
    ve_sortie = ebitda_sortie * multiple_sortie
    passif_sortie = dettes[-1] - tresos[-1] + hyp.minoritaires + hyp.autres_ajustements
    equity_sortie = ve_sortie - passif_sortie
    moic = equity_sortie / sponsor
    tri = moic ** (1 / DUREE) - 1 if moic > 0 else float("nan")

    # Prix maximum : la mise du fonds et la valeur de sortie sont toutes deux linéaires
    # en fonction du prix payé (la dette ne dépend que de l'EBITDA), d'où une solution exacte.
    a = ebitda_sortie / ebitda_ltm
    k = ebitda_sortie * hyp.ecart_multiple_sortie - passif_sortie
    c0 = (dette_refi + hyp.frais_transaction * dette_nette + frais_fin + hyp.treso_min
          - nouvelle_dette - treso_cloture)
    prix_max = {}
    for cible in (hyp.tri_cible, hyp.tri_cible_haut):
        r = (1 + cible) ** DUREE
        cp_max = (r * c0 - a * dette_nette - k) / (a - r * (1 + hyp.frais_transaction))
        prix_max[cible] = cp_max / hyp.actions_diluees

    return Lbo(
        prix_offre=prix, cp_acquis=cp_acquis, dette_refinancee=dette_refi,
        treso_cloture=treso_cloture, dette_nette_entree=dette_nette, ve_entree=ve,
        multiple_entree=multiple_entree, nouvelle_dette=nouvelle_dette,
        frais_transaction=frais_tx, frais_financement=frais_fin, total_emplois=emplois,
        equity_sponsor=sponsor, interets=interets, rn=rns, fcf=fcfs, amortissement=amorts,
        sweep=sweeps, dette_fin=dettes, treso_fin=tresos, multiple_sortie=multiple_sortie,
        ve_sortie=ve_sortie, equity_sortie=equity_sortie, moic=moic, tri=tri, prix_max=prix_max,
    )


def tri_lbo(soc: Societe, proj: Projection, hyp: Hypotheses, lbo: Lbo, *, prime: float | None = None,
            multiple_sortie: float | None = None, annee: int = DUREE) -> float | None:
    """TRI pour une autre prime, un autre multiple ou une autre année de sortie.

    Le plan de dette ne change pas : seuls la mise de départ et le prix de revente bougent.
    """
    cp = hyp.cours * (1 + (hyp.prime_acquisition if prime is None else prime)) * hyp.actions_diluees
    constante = lbo.equity_sponsor - (1 + hyp.frais_transaction) * lbo.cp_acquis
    mise = equity_sponsor(cp, hyp, constante)
    m = lbo.multiple_sortie if multiple_sortie is None else multiple_sortie
    sortie = (proj.ebitda[annee] * m - lbo.dette_fin[annee - 1] + lbo.treso_fin[annee - 1]
              - hyp.minoritaires - hyp.autres_ajustements)
    if sortie <= 0 or mise <= 0:
        return None
    return (sortie / mise) ** (1 / annee) - 1
