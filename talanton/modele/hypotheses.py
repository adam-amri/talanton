"""Hypothèses du modèle et valeurs proposées par défaut.

Les valeurs par défaut sont mécaniques : elles partent du dernier chiffre publié
et convergent vers une situation normale. Elles servent de point de départ, pas
de prévision. Chacune apparaît en bleu dans l'onglet « Hypothèses » du classeur
et se modifie soit dans Excel, soit dans un fichier TOML passé à Talanton.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from datetime import date
from pathlib import Path

from ..collecte.marche import Cours
from ..retraitement.etats import Societe

N_PROJECTION = 6                 # exercices projetés
TAUX_IS_NORMATIF = 0.25          # impôt fédéral américain (21 %) + impôts des États
PRIME_MARCHE = 0.0441            # prime de risque implicite du S&P 500 (Damodaran, 1er nov. 2026)
SOURCE_PRIME_MARCHE = ("Prime de risque implicite du S&P 500 publiée par A. Damodaran "
                       "(NYU Stern), 1er novembre 2026 : 4,41 %")
CROISSANCE_PERPETUELLE = 0.02
POIDS_BLUME = 0.67               # bêta ajusté = 0,67 x bêta brut + 0,33 x 1


def _borner(x: float, bas: float, haut: float) -> float:
    return max(bas, min(haut, x))


def _rampe(depart: float, arrivee: float, n: int) -> list[float]:
    """n valeurs allant linéairement de `depart` (année 1) à `arrivee` (année n)."""
    if n == 1:
        return [depart]
    return [depart + (arrivee - depart) * k / (n - 1) for k in range(n)]


@dataclass
class Hypotheses:
    n: int
    # --- marché et passage de la valeur d'entreprise aux capitaux propres ---
    date_valo: date
    cours: float
    actions: float
    dilution: float
    dette: float
    tresorerie: float
    minoritaires: float
    autres_ajustements: float
    # --- exploitation (une valeur par exercice projeté) ---
    croissance: list[float]
    marge_ebitda: list[float]
    da_pct: list[float]
    capex_pct: list[float]
    bfr_pct: list[float]
    distributions: list[float]
    passif_expl_pct: float
    taux_is: float
    cout_dette: float
    rendement_treso: float
    # --- coût du capital et valeur terminale ---
    taux_sans_risque: float
    prime_marche: float
    beta_brut: float
    poids_blume: float
    prime_specifique: float
    poids_dette: float
    croissance_perpetuelle: float
    multiple_sortie_dcf: float
    mi_annee: int
    # --- LBO ---
    prime_acquisition: float
    levier: float
    taux_lbo: float
    amort_pct: float
    sweep_pct: float
    treso_min: float
    frais_transaction: float
    frais_financement: float
    ecart_multiple_sortie: float
    tri_cible: float
    tri_cible_haut: float
    # --- pas des tables de sensibilité et seuil des multiples ---
    pas_wacc: float = 0.005
    pas_g: float = 0.005
    pas_multiple: float = 1.0
    pas_prime: float = 0.05
    plafond_multiple: float = 40.0
    # --- justification affichée à côté de chaque hypothèse ---
    notes: dict[str, str] = field(default_factory=dict)

    # grandeurs dérivées (mêmes formules que dans le classeur)
    @property
    def actions_diluees(self) -> float:
        return self.actions + self.dilution

    @property
    def capitalisation(self) -> float:
        return self.cours * self.actions_diluees

    @property
    def dette_nette(self) -> float:
        return self.dette - self.tresorerie

    @property
    def passage(self) -> float:
        """Montant à retrancher de la valeur d'entreprise pour obtenir les capitaux propres."""
        return self.dette_nette + self.minoritaires + self.autres_ajustements

    @property
    def valeur_entreprise(self) -> float:
        return self.capitalisation + self.passage

    @property
    def beta(self) -> float:
        return self.poids_blume * self.beta_brut + (1 - self.poids_blume)

    @property
    def cout_fonds_propres(self) -> float:
        return self.taux_sans_risque + self.beta * self.prime_marche + self.prime_specifique

    @property
    def wacc(self) -> float:
        return ((1 - self.poids_dette) * self.cout_fonds_propres
                + self.poids_dette * self.cout_dette * (1 - self.taux_is))


def hypotheses_par_defaut(soc: Societe, cours: Cours, taux: Cours,
                          beta: tuple[float, int, float] | None,
                          multiple_pairs: float | None, n: int = N_PROJECTION) -> Hypotheses:
    h, d, ltm = soc.hist, soc.dernier, soc.ltm
    notes: dict[str, str] = {}

    # Croissance : rythme des douze derniers mois, puis convergence vers le long terme.
    g1 = _borner(ltm["ca"] / d["ca"] - 1, -0.05, 0.10)
    croissance = _rampe(g1, CROISSANCE_PERPETUELLE, n)
    notes["croissance"] = (f"Année 1 : CA des 12 derniers mois rapporté au dernier exercice "
                           f"({g1:+.1%}), puis convergence linéaire vers {CROISSANCE_PERPETUELLE:.1%}.")

    # Marge : marge des douze derniers mois, puis retour vers la moyenne de trois exercices.
    marges = [e / c for e, c in zip(h["ebitda_ajuste"][-3:], h["ca"][-3:])]
    marge_normale = sum(marges) / len(marges)
    marge_ltm = ltm["ebitda_ajuste"] / ltm["ca"]
    marge = _rampe(marge_ltm, marge_normale, n)
    notes["marge_ebitda"] = (f"Année 1 : marge d'EBITDA ajusté des 12 derniers mois ({marge_ltm:.1%}), "
                             f"puis retour linéaire vers la moyenne des {len(marges)} derniers exercices "
                             f"({marge_normale:.1%}).")

    da_pct = d["da"] / d["ca"]
    notes["da_pct"] = "Ratio du dernier exercice, maintenu."
    capex = [c / v for c, v in zip(h["capex"][-3:], h["ca"][-3:]) if c is not None]
    capex_pct = sum(capex) / len(capex) if capex else da_pct
    notes["capex_pct"] = f"Moyenne des {len(capex)} derniers exercices, maintenue."
    bfr_pct = d["bfr"] / d["ca"]
    notes["bfr_pct"] = "Ratio du dernier exercice, maintenu."
    distributions = [soc.distributions_cumul] + [0.0] * (n - 1)
    notes["distributions"] = ("Année 1 : rachats d'actions et dividendes déjà versés depuis la clôture "
                              f"(au {soc.date_bilan.strftime('%d/%m/%Y')}). Ensuite : aucun, la trésorerie s'accumule.")

    dette_moyenne = (h["dette"][-1] + h["dette"][-2]) / 2 if len(h["dette"]) > 1 else h["dette"][-1]
    cout_dette = _borner(d["interets"] / dette_moyenne, 0.02, 0.12) if d["interets"] and dette_moyenne else 0.06
    notes["cout_dette"] = "Charges d'intérêts du dernier exercice rapportées à la dette moyenne."
    treso_moyenne = (h["tresorerie"][-1] + h["tresorerie"][-2]) / 2 if len(h["tresorerie"]) > 1 else h["tresorerie"][-1]
    rendement = _borner((d["produits_fin"] or 0.0) / treso_moyenne, 0.0, 0.05) if treso_moyenne else 0.0
    notes["rendement_treso"] = "Produits financiers du dernier exercice rapportés à la trésorerie moyenne."
    notes["taux_is"] = "Taux normatif : impôt fédéral américain de 21 % plus impôts des États."

    if beta is not None:
        beta_brut, n_obs, r2 = beta
        notes["beta_brut"] = (f"Régression de {n_obs} rendements mensuels sur le S&P 500 (R² = {r2:.2f}). "
                              "Un R² faible signale un bêta peu fiable : envisager un bêta sectoriel.")
    else:
        beta_brut = 1.0
        notes["beta_brut"] = "Historique de cours indisponible : bêta de 1 par défaut, à renseigner."
    notes["poids_blume"] = "Ajustement de Blume : bêta ajusté = poids x bêta brut + (1 - poids) x 1. Mettre 1 pour garder le bêta brut."
    notes["taux_sans_risque"] = f"Rendement du Treasury à 10 ans. {taux.source}."
    notes["prime_marche"] = SOURCE_PRIME_MARCHE + "."

    capitalisation = cours.cours * soc.actions
    poids_dette = soc.bilan["dette"] / (soc.bilan["dette"] + capitalisation)
    notes["poids_dette"] = "Structure actuelle : dette financière / (dette + capitalisation boursière)."
    notes["croissance_perpetuelle"] = "Proche de l'inflation de long terme ; doit rester inférieure au WACC."

    ve = capitalisation + soc.bilan["dette"] - soc.bilan["tresorerie"] + soc.bilan["minoritaires"]
    if multiple_pairs is None:
        multiple_pairs = ve / ltm["ebitda_ajuste"]
        notes["multiple_sortie_dcf"] = "Multiple VE/EBITDA actuel de la société (aucun comparable exploitable)."
    else:
        notes["multiple_sortie_dcf"] = "Médiane VE/EBITDA des comparables (onglet Comparables)."

    taux_lbo = round(taux.cours + 0.04, 4)
    notes["taux_lbo"] = "Taux sans risque + 4 points : ordre de grandeur d'un prêt à effet de levier."
    notes["prime_acquisition"] = "Prime payée sur le cours pour retirer la société de la cote (usuel : 20 à 40 %)."
    notes["levier"] = "Dette d'acquisition, en multiple de l'EBITDA ajusté des 12 derniers mois."
    notes["amort_pct"] = "Remboursement contractuel annuel, en % de la dette initiale."
    notes["sweep_pct"] = "Part de la trésorerie excédentaire affectée au remboursement anticipé."
    treso_min = float(round(0.02 * ltm["ca"]))
    notes["treso_min"] = "Trésorerie laissée dans la société à la clôture (environ 2 % du CA)."
    notes["frais_transaction"] = "Conseils, juridique : en % de la valeur d'entreprise. Passés en charge."
    notes["frais_financement"] = "Commissions d'arrangement : en % de la nouvelle dette. Passés en charge."
    notes["ecart_multiple_sortie"] = "Multiple de sortie = multiple d'entrée + cet écart. Zéro : hypothèse prudente usuelle."
    notes["tri_cible"] = "TRI visé par un fonds : sert à calculer le prix maximum qu'il peut payer."
    notes["date_valo"] = "Date du dernier bilan publié : les flux postérieurs sont dans le DCF."
    notes["cours"] = cours.source + "."
    notes["actions"] = soc.source_actions.capitalize() + "."
    notes["dilution"] = "Options et actions gratuites : à estimer (méthode du rachat d'actions)."
    notes["dette"] = f"Dette financière au {soc.date_bilan.strftime('%d/%m/%Y')} (hors dettes de location)."
    notes["tresorerie"] = f"Trésorerie et placements au {soc.date_bilan.strftime('%d/%m/%Y')}."
    notes["minoritaires"] = "Intérêts minoritaires au dernier bilan."
    notes["autres_ajustements"] = "Retraites non financées, dettes de location, participations... (0 par défaut)."
    notes["passif_expl_pct"] = "Ratio du dernier exercice : sert à présenter le bilan, sans effet sur les flux."
    notes["mi_annee"] = "1 : les flux tombent en milieu d'année. 0 : en fin d'année."

    return Hypotheses(
        n=n, date_valo=soc.date_bilan, cours=cours.cours, actions=soc.actions, dilution=0.0,
        dette=soc.bilan["dette"], tresorerie=soc.bilan["tresorerie"],
        minoritaires=soc.bilan["minoritaires"], autres_ajustements=0.0,
        croissance=croissance, marge_ebitda=marge, da_pct=[da_pct] * n, capex_pct=[capex_pct] * n,
        bfr_pct=[bfr_pct] * n, distributions=distributions,
        passif_expl_pct=d["passif_expl"] / d["ca"], taux_is=TAUX_IS_NORMATIF,
        cout_dette=cout_dette, rendement_treso=rendement,
        taux_sans_risque=taux.cours, prime_marche=PRIME_MARCHE, beta_brut=beta_brut,
        poids_blume=POIDS_BLUME, prime_specifique=0.0, poids_dette=poids_dette,
        croissance_perpetuelle=CROISSANCE_PERPETUELLE, multiple_sortie_dcf=multiple_pairs, mi_annee=1,
        prime_acquisition=0.30, levier=5.0, taux_lbo=taux_lbo, amort_pct=0.01, sweep_pct=1.0,
        treso_min=treso_min, frais_transaction=0.02, frais_financement=0.025,
        ecart_multiple_sortie=0.0, tri_cible=0.20, tri_cible_haut=0.25, notes=notes,
    )


def appliquer_surcharges(hyp: Hypotheses, fichier: Path | None) -> list[str]:
    """Remplace des hypothèses par celles d'un fichier TOML. Renvoie les champs modifiés.

    Une hypothèse annuelle accepte une liste de `n` valeurs ou un nombre unique
    (appliqué à tous les exercices).
    """
    if fichier is None:
        return []
    brut = tomllib.loads(Path(fichier).read_text(encoding="utf-8"))
    connus = {f.name: f for f in fields(hyp)}
    modifies = []
    for cle, valeur in brut.items():
        if cle not in connus or cle in ("n", "notes"):
            raise ValueError(f"Hypothèse inconnue dans {fichier} : {cle}")
        actuel = getattr(hyp, cle)
        if isinstance(actuel, list):
            valeurs = [float(v) for v in valeur] if isinstance(valeur, list) else [float(valeur)] * hyp.n
            if len(valeurs) != hyp.n:
                raise ValueError(f"{cle} : {hyp.n} valeurs attendues, {len(valeurs)} fournies.")
            setattr(hyp, cle, valeurs)
        elif isinstance(actuel, date):
            setattr(hyp, cle, valeur if isinstance(valeur, date) else date.fromisoformat(str(valeur)))
        elif isinstance(actuel, int) and not isinstance(actuel, bool):
            setattr(hyp, cle, int(valeur))
        else:
            setattr(hyp, cle, float(valeur))
        hyp.notes[cle] = f"Valeur imposée par {Path(fichier).name}."
        modifies.append(cle)
    return modifies
