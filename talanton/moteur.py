"""Assemblage : de la collecte au résultat complet, en Python pur.

Ce module ne connaît pas Excel. Le classeur refait les mêmes calculs avec des
formules ; `points_de_controle` liste les chiffres comparés entre les deux.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .collecte import ClientEdgar, ClientMarche, ErreurCollecte
from .modele import Hypotheses, Projection, appliquer_surcharges, hypotheses_par_defaut, projeter
from .retraitement import Societe, charger_ajustements, construire_societe
from .valorisation import (Comparable, Comparables, Dcf, Lbo, Sensibilites, calculer_dcf,
                           calculer_lbo, calculer_sensibilites, calculer_statistiques,
                           football_field, valoriser_cible)


@dataclass
class Resultat:
    cible: Societe
    hyp: Hypotheses
    proj: Projection
    dcf: Dcf
    comps: Comparables
    lbo: Lbo
    sensi: Sensibilites
    football: list[tuple[str, float | None, float | None]]
    surcharges: list[str]

    def points_de_controle(self) -> dict[str, float]:
        """Chiffres clés recalculés par Python, à rapprocher des formules du classeur."""
        h, p, d, lbo = self.hyp, self.proj, self.dcf, self.lbo
        points = {
            "proj.ca_fin": p.ca[-1],
            "proj.ebitda_fin": p.ebitda[-1],
            "proj.rn_fin": p.rn[-1],
            "proj.tresorerie_fin": p.tresorerie[-1],
            "proj.total_actif_fin": p.total_actif[-1],
            "dcf.wacc": h.wacc,
            "dcf.fcf_fin": d.fcf[-1],
            "dcf.ve_gordon": d.ve_gordon,
            "dcf.ve_multiple": d.ve_multiple,
            "dcf.action_gordon": d.action_gordon,
            "dcf.action_multiple": d.action_multiple,
            "lbo.ve_entree": lbo.ve_entree,
            "lbo.equity_sponsor": lbo.equity_sponsor,
            "lbo.dette_fin": lbo.dette_fin[-1],
            "lbo.equity_sortie": lbo.equity_sortie,
            "lbo.moic": lbo.moic,
            "lbo.tri": lbo.tri,
            "lbo.prix_max_cible": lbo.prix_max[h.tri_cible],
            "lbo.prix_max_haut": lbo.prix_max[h.tri_cible_haut],
        }
        mediane = self.comps.stats["ve_ebitda"]["mediane"]
        if mediane is not None:
            points["comps.mediane_ve_ebitda"] = mediane
            points["comps.action_mediane_ve_ebitda"] = self.comps.implicite["ve_ebitda"]["mediane"]
        return points


def collecter(ticker: str, pairs: list[str], cache: Path, hors_ligne: bool,
              fichier_ajustements: Path | None, journal=print):
    """Récupère et retraite la cible, ses comparables et les données de marché."""
    edgar = ClientEdgar(cache, hors_ligne=hors_ligne)
    marche = ClientMarche(cache, hors_ligne=hors_ligne)

    journal(f"Collecte des comptes de {ticker} (SEC EDGAR)")
    cible = construire_societe(ticker, edgar.faits(ticker), 5, charger_ajustements(fichier_ajustements))
    cours = marche.dernier_cours(ticker)
    taux = marche.taux_sans_risque()
    try:
        beta = marche.beta(ticker)
    except ErreurCollecte as exc:
        journal(f"  bêta indisponible : {exc}")
        beta = None

    comparables: list[Comparable] = []
    for t in pairs:
        journal(f"Collecte du comparable {t}")
        try:
            societe = construire_societe(t, edgar.faits(t), 1, None, bilan_detaille=False)
            comparables.append(Comparable(societe, marche.dernier_cours(t)))
        except Exception as exc:     # un comparable inexploitable n'arrête pas le modèle
            journal(f"  {t} écarté : {exc}")
    return cible, cours, taux, beta, comparables


def calculer(cible: Societe, cours, taux, beta, comparables: list[Comparable],
             fichier_hypotheses: Path | None = None) -> Resultat:
    """Hypothèses, projections et valorisations, à partir des données retraitées."""
    plafond = 40.0
    comps = calculer_statistiques(comparables, plafond)
    hyp = hypotheses_par_defaut(cible, cours, taux, beta, comps.stats["ve_ebitda"]["mediane"])
    surcharges = appliquer_surcharges(hyp, fichier_hypotheses)
    if hyp.plafond_multiple != plafond:
        comps = calculer_statistiques(comparables, hyp.plafond_multiple)
        if "multiple_sortie_dcf" not in surcharges and comps.stats["ve_ebitda"]["mediane"] is not None:
            hyp.multiple_sortie_dcf = comps.stats["ve_ebitda"]["mediane"]
    valoriser_cible(comps, cible, hyp)
    proj = projeter(cible, hyp)
    dcf = calculer_dcf(proj, hyp)
    lbo = calculer_lbo(cible, proj, hyp)
    sensi = calculer_sensibilites(cible, proj, hyp, dcf, lbo)
    return Resultat(cible, hyp, proj, dcf, comps, lbo, sensi,
                    football_field(hyp, comps, sensi, lbo), surcharges)
