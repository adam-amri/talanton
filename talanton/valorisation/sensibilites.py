"""Tables de sensibilité et fourchettes du « football field ».

Mêmes calculs que les formules de l'onglet Sensibilités : chaque case refait la
valorisation avec deux hypothèses déplacées.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..modele.hypotheses import Hypotheses
from ..modele.projections import Projection
from ..retraitement.etats import Societe
from .comparables import Comparables
from .dcf import Dcf, valeur_par_action, ve_gordon, ve_multiple
from .lbo import Lbo, tri_lbo

CRANS = (-2, -1, 0, 1, 2)
ANNEES_SORTIE = (3, 4, 5)


@dataclass
class Sensibilites:
    wacc: list[float]
    g: list[float]
    multiples_dcf: list[float]
    multiples_lbo: list[float]
    primes: list[float]
    dcf_gordon: list[list[float]]            # lignes : WACC ; colonnes : croissance perpétuelle
    dcf_multiple: list[list[float]]          # lignes : WACC ; colonnes : multiple de sortie
    lbo_sortie: list[list[float | None]]     # lignes : multiple de sortie ; colonnes : année de sortie
    lbo_prime: list[list[float | None]]      # lignes : prime ; colonnes : multiple de sortie


def calculer_sensibilites(soc: Societe, proj: Projection, hyp: Hypotheses, dcf: Dcf, lbo: Lbo) -> Sensibilites:
    wacc = [hyp.wacc + k * hyp.pas_wacc for k in CRANS]
    g = [hyp.croissance_perpetuelle + k * hyp.pas_g for k in CRANS]
    m_dcf = [hyp.multiple_sortie_dcf + k * hyp.pas_multiple for k in CRANS]
    m_lbo = [lbo.multiple_sortie + k * hyp.pas_multiple for k in CRANS]
    primes = [hyp.prime_acquisition + k * hyp.pas_prime for k in CRANS]
    t1 = [[valeur_par_action(ve_gordon(dcf.fcf, dcf.poids, dcf.temps, w, gg), hyp) for gg in g] for w in wacc]
    t2 = [[valeur_par_action(ve_multiple(dcf.fcf, dcf.poids, dcf.temps, dcf.temps_fin,
                                         proj.ebitda[-1], w, m), hyp) for m in m_dcf] for w in wacc]
    t3 = [[tri_lbo(soc, proj, hyp, lbo, multiple_sortie=m, annee=a) for a in ANNEES_SORTIE] for m in m_lbo]
    t4 = [[tri_lbo(soc, proj, hyp, lbo, prime=p, multiple_sortie=m) for m in m_lbo] for p in primes]
    return Sensibilites(wacc, g, m_dcf, m_lbo, primes, t1, t2, t3, t4)


def football_field(hyp: Hypotheses, comps: Comparables, sensi: Sensibilites, lbo: Lbo
                   ) -> list[tuple[str, float | None, float | None]]:
    """Fourchettes de valeur par action, méthode par méthode : (libellé, bas, haut)."""
    def coeur(table):                                    # 3 x 3 cases centrales
        cases = [table[i][j] for i in (1, 2, 3) for j in (1, 2, 3)]
        return min(cases), max(cases)

    lignes = []
    for nom, libelle in (("ve_ebitda", "Comparables : VE / EBITDA"), ("ve_ebit", "Comparables : VE / EBIT"),
                         ("per", "Comparables : PER")):
        imp = comps.implicite.get(nom, {})
        lignes.append((libelle, imp.get("q1"), imp.get("q3")))
    lignes.append(("DCF : croissance perpétuelle", *coeur(sensi.dcf_gordon)))
    lignes.append(("DCF : multiple de sortie", *coeur(sensi.dcf_multiple)))
    lignes.append(("LBO : prix maximum d'un fonds", lbo.prix_max[hyp.tri_cible_haut], lbo.prix_max[hyp.tri_cible]))
    lignes.append(("Cours actuel", hyp.cours, hyp.cours))
    return lignes
