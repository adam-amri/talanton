"""Écriture du classeur Excel : neuf onglets reliés par de vraies formules.

Python n'écrit en dur que les données publiées et les hypothèses (en bleu).
Tout le reste est une formule : changer une cellule bleue recalcule le modèle.
Le registre renvoyé associe chaque chiffre clé à sa cellule, pour le
rapprochement avec le moteur Python.
"""

from __future__ import annotations

from datetime import date

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.utils import get_column_letter as L

from .. import __version__
from ..moteur import Resultat
from ..valorisation.sensibilites import ANNEES_SORTIE, CRANS
from . import styles as S

SY, HY, HI, PR, DCF, CO, LBO, SE, CT = ("Synthèse", "Hypothèses", "Historique", "Projections",
                                         "DCF", "Comparables", "LBO", "Sensibilités", "Contrôles")
FMT_PCT2 = "0.00%"


class Feuille:
    """Un onglet, avec la mémoire de la ligne de chaque poste."""

    def __init__(self, wb: Workbook, nom: str, couleur: str):
        self.ws = wb.create_sheet(nom)
        self.nom = nom
        self.lig: dict[str, int] = {}
        self.ws.sheet_view.showGridLines = False
        self.ws.sheet_properties.tabColor = couleur

    def r(self, cle: str) -> int:
        return self.lig[cle]

    def a(self, cle: str, col: str, fixe: bool = False) -> str:
        """Adresse dans l'onglet lui-même."""
        return f"${col}${self.lig[cle]}" if fixe else f"{col}{self.lig[cle]}"

    def x(self, cle: str, col: str) -> str:
        """Adresse vue d'un autre onglet (toujours figée)."""
        return f"'{self.nom}'!${col}${self.lig[cle]}"

    def xp(self, cle: str, c1: str, c2: str) -> str:
        """Plage d'une ligne vue d'un autre onglet."""
        r = self.lig[cle]
        return f"'{self.nom}'!${c1}${r}:${c2}${r}"

    def ecrire(self, ref: str, valeur, style: str = "calcul", fmt: str | None = None, **kw):
        cell = self.ws[ref]
        cell.value = valeur
        S.appliquer(cell, style, fmt, **kw)
        return cell

    def titre(self, texte: str, sous_titre: str = "") -> None:
        self.ws["A1"].value = texte
        self.ws["A1"].font = S.police(S.ENCRE, gras=True, taille=14)
        if sous_titre:
            self.ws["A2"].value = sous_titre
            self.ws["A2"].font = S.police(S.GRIS, italique=True)

    def disposer(self, lignes: list[tuple], depart: int, largeur: int, unite_col: str | None = "B") -> int:
        """Place les postes les uns sous les autres et écrit leurs libellés.

        ("#", texte) : bandeau de section ; ("",) : ligne vide ;
        (clé, libellé[, unité]) : poste.
        """
        r = depart
        for ligne in lignes:
            if ligne[0] == "#":
                S.bandeau(self.ws, r, ligne[1], largeur)
            elif ligne[0]:
                self.lig[ligne[0]] = r
                self.ws.cell(row=r, column=1, value=ligne[1]).font = S.police()
                if len(ligne) > 2 and unite_col:
                    self.ecrire(f"{unite_col}{r}", ligne[2], "note")
            r += 1
        return r


def construire_classeur(res: Resultat, genere_le: date) -> tuple[Workbook, dict[str, tuple[str, str]]]:
    soc, h, proj = res.cible, res.hyp, res.proj
    n, nh = h.n, len(soc.exercices)
    wb = Workbook()
    wb.remove(wb.active)
    f = {nom: Feuille(wb, nom, couleur) for nom, couleur in (
        (SY, "1F2A44"), (HY, "E0A800"), (HI, "7F7F7F"), (PR, "7F7F7F"), (DCF, "2E75B6"),
        (CO, "2E75B6"), (LBO, "2E75B6"), (SE, "2E75B6"), (CT, "C00000"))}
    sy, hy, hi, pr, dcf, co, lbo, se, ct = (f[x] for x in (SY, HY, HI, PR, DCF, CO, LBO, SE, CT))

    HC = [L(3 + i) for i in range(nh)]         # colonnes des exercices historiques
    HL, HS = L(3 + nh), L(4 + nh)              # colonne LTM, colonne des sources
    HD = HC[-1]                                # dernier exercice clos
    PB, PC = "B", [L(3 + i) for i in range(n)]  # colonne de base, colonnes projetées
    P1, PN = PC[0], PC[-1]
    annees_h = [f"{d.year}A" for d in soc.exercices]
    annees_p = [f"{d.year}E" for d in proj.fins]
    nom_court = soc.nom.title().replace(" /De/", "").replace(" Inc", " Inc.").replace("..", ".")
    registre: dict[str, tuple[str, str]] = {}

    # ------------------------------------------------------------------ plans
    hy.disposer([
        ("#", "Marché et passage de la valeur d'entreprise aux capitaux propres"),
        ("date_valo", "Date de valorisation", "date"),
        ("cours", "Cours de l'action", "$"),
        ("actions", "Actions en circulation", "millions"),
        ("dilution", "Titres dilutifs (options, actions gratuites)", "millions"),
        ("actions_diluees", "Actions diluées", "millions"),
        ("capitalisation", "Capitalisation boursière", "M$"),
        ("dette", "Dette financière", "M$"),
        ("tresorerie", "Trésorerie et placements", "M$"),
        ("minoritaires", "Intérêts minoritaires", "M$"),
        ("autres_ajustements", "Autres ajustements (retraites, locations...)", "M$"),
        ("dette_nette", "Dette financière nette", "M$"),
        ("passage", "Total à déduire de la valeur d'entreprise", "M$"),
        ("valeur_entreprise", "Valeur d'entreprise au cours actuel", "M$"),
        ("",),
        ("#", "Exploitation : une hypothèse par exercice projeté"),
        ("annees", "Exercice"),
        ("croissance", "Croissance du chiffre d'affaires", "%"),
        ("marge_ebitda", "Marge d'EBITDA", "% du CA"),
        ("da_pct", "Dotations aux amortissements", "% du CA"),
        ("capex_pct", "Investissements (capex)", "% du CA"),
        ("bfr_pct", "Besoin en fonds de roulement", "% du CA"),
        ("distributions", "Dividendes et rachats d'actions", "M$"),
        ("",),
        ("passif_expl_pct", "Passif d'exploitation courant", "% du CA"),
        ("taux_is", "Taux d'impôt sur les sociétés", "%"),
        ("cout_dette", "Coût de la dette avant impôt", "%"),
        ("rendement_treso", "Rendement de la trésorerie", "%"),
        ("",),
        ("#", "Coût du capital et valeur terminale"),
        ("taux_sans_risque", "Taux sans risque", "%"),
        ("prime_marche", "Prime de risque du marché actions", "%"),
        ("beta_brut", "Bêta brut (régression)", "x"),
        ("poids_blume", "Poids du bêta brut (ajustement de Blume)", "x"),
        ("beta", "Bêta retenu", "x"),
        ("prime_specifique", "Prime de risque spécifique", "%"),
        ("cout_fonds_propres", "Coût des fonds propres", "%"),
        ("poids_dette", "Poids de la dette dans le financement", "%"),
        ("wacc", "Coût moyen pondéré du capital (WACC)", "%"),
        ("croissance_perpetuelle", "Croissance perpétuelle", "%"),
        ("multiple_sortie_dcf", "Multiple de sortie VE/EBITDA (DCF)", "x"),
        ("mi_annee", "Convention de milieu d'année (1 = oui, 0 = non)", ""),
        ("",),
        ("#", "LBO"),
        ("prime_acquisition", "Prime d'acquisition sur le cours", "%"),
        ("levier", "Dette d'acquisition", "x EBITDA LTM"),
        ("taux_lbo", "Taux d'intérêt de la dette d'acquisition", "%"),
        ("amort_pct", "Amortissement contractuel annuel", "% dette initiale"),
        ("sweep_pct", "Trésorerie excédentaire affectée au remboursement", "%"),
        ("treso_min", "Trésorerie minimale conservée", "M$"),
        ("frais_transaction", "Frais de transaction", "% de la VE"),
        ("frais_financement", "Frais de financement", "% de la dette"),
        ("ecart_multiple_sortie", "Écart entre multiple de sortie et multiple d'entrée", "x"),
        ("tri_cible", "TRI visé par le fonds", "%"),
        ("tri_cible_haut", "TRI visé, variante exigeante", "%"),
        ("",),
        ("#", "Tables de sensibilité et seuil des multiples"),
        ("pas_wacc", "Pas de variation du WACC", "%"),
        ("pas_g", "Pas de variation de la croissance perpétuelle", "%"),
        ("pas_multiple", "Pas de variation des multiples", "x"),
        ("pas_prime", "Pas de variation de la prime d'acquisition", "%"),
        ("plafond_multiple", "Multiple maximal jugé significatif", "x"),
    ], depart=4, largeur=3 + n)

    hi.disposer([
        ("fin", "Exercice clos le"),
        ("#", "Compte de résultat"),
        ("ca", "Chiffre d'affaires"),
        ("croissance", "  croissance"),
        ("marge_brute", "Marge brute"),
        ("marge_brute_pct", "  en % du CA"),
        ("ebit", "Résultat opérationnel publié (EBIT)"),
        ("da", "Dotations aux amortissements (D&A)"),
        ("ebitda_publie", "EBITDA publié"),
        ("depreciations", "Dépréciations d'actifs réintégrées"),
        ("ajust", "Ajustements d'analyste"),
        ("ebitda_ajuste", "EBITDA ajusté"),
        ("marge_ebitda", "  marge d'EBITDA ajusté"),
        ("ebit_ajuste", "EBIT ajusté"),
        ("interets", "Charges d'intérêts"),
        ("produits_fin", "Produits financiers"),
        ("rai", "Résultat avant impôt"),
        ("impot", "Impôt sur les sociétés"),
        ("taux_effectif", "  taux d'impôt effectif"),
        ("rn", "Résultat net part du groupe"),
        ("ajust_rn", "Ajustements d'analyste (après impôt)"),
        ("rn_ajuste", "Résultat net ajusté"),
        ("sbc", "Pour mémoire : rémunérations en actions"),
        ("#", "Flux de trésorerie"),
        ("cfo", "Flux de trésorerie d'exploitation"),
        ("capex", "Investissements (capex)"),
        ("fcf", "Flux de trésorerie disponible (exploitation - capex)"),
        ("rachats", "Rachats d'actions"),
        ("dividendes", "Dividendes versés"),
        ("da_pct", "  D&A en % du CA"),
        ("capex_pct", "  capex en % du CA"),
        ("#", "Bilan simplifié"),
        ("tresorerie", "Trésorerie et placements"),
        ("actif_circ_expl", "Actif circulant d'exploitation"),
        ("immo_nettes", "Immobilisations nettes (hors goodwill)"),
        ("goodwill", "Goodwill"),
        ("autres_actifs", "Autres actifs non courants"),
        ("total_actif", "Total de l'actif"),
        ("passif_expl", "Passif d'exploitation courant"),
        ("dette", "Dette financière"),
        ("autres_passifs", "Autres passifs non courants"),
        ("capitaux_propres", "Capitaux propres"),
        ("total_passif", "Total du passif"),
        ("ecart", "Contrôle : actif - passif"),
        ("bfr", "Besoin en fonds de roulement (BFR)"),
        ("bfr_pct", "  BFR en % du CA"),
        ("passif_expl_pct", "  passif d'exploitation en % du CA"),
    ], depart=5, largeur=4 + nh, unite_col=None)

    pr.disposer([
        ("fin", "Exercice clos le"),
        ("#", "Compte de résultat"),
        ("ca", "Chiffre d'affaires"),
        ("croissance", "  croissance"),
        ("ebitda", "EBITDA"),
        ("marge", "  marge d'EBITDA"),
        ("da", "Dotations aux amortissements"),
        ("ebit", "Résultat opérationnel (EBIT)"),
        ("interets", "Charges d'intérêts"),
        ("produits_fin", "Produits financiers"),
        ("rai", "Résultat avant impôt"),
        ("impot", "Impôt sur les sociétés"),
        ("rn", "Résultat net"),
        ("#", "Flux de trésorerie"),
        ("capex", "Investissements (capex)"),
        ("var_bfr", "Variation du BFR"),
        ("distributions", "Dividendes et rachats d'actions"),
        ("var_treso", "Variation de la trésorerie"),
        ("#", "Bilan"),
        ("tresorerie", "Trésorerie et placements"),
        ("actif_circ_expl", "Actif circulant d'exploitation"),
        ("immo_nettes", "Immobilisations nettes (hors goodwill)"),
        ("goodwill", "Goodwill"),
        ("autres_actifs", "Autres actifs non courants"),
        ("total_actif", "Total de l'actif"),
        ("passif_expl", "Passif d'exploitation courant"),
        ("dette", "Dette financière"),
        ("autres_passifs", "Autres passifs non courants"),
        ("capitaux_propres", "Capitaux propres"),
        ("total_passif", "Total du passif"),
        ("ecart", "Contrôle : actif - passif"),
        ("bfr", "Besoin en fonds de roulement (BFR)"),
    ], depart=5, largeur=2 + n, unite_col=None)

    dcf.disposer([
        ("#", "Flux de trésorerie disponibles"),
        ("ebit", "Résultat opérationnel (EBIT)"),
        ("impot_ebit", "Impôt sur l'EBIT"),
        ("nopat", "Résultat opérationnel après impôt"),
        ("da", "Dotations aux amortissements"),
        ("capex", "Investissements (capex)"),
        ("var_bfr", "Variation du BFR"),
        ("fcf", "Flux de trésorerie disponible"),
        ("",),
        ("poids", "Part de l'exercice prise en compte"),
        ("temps", "Durée d'actualisation (années)"),
        ("facteur", "Facteur d'actualisation"),
        ("fcf_act", "Flux actualisé"),
        ("",),
        ("#", "Paramètres"),
        ("wacc", "WACC"),
        ("g", "Croissance perpétuelle"),
        ("multiple", "Multiple de sortie VE/EBITDA"),
        ("fraction", "Fraction du premier exercice restant à courir"),
        ("temps_fin", "Durée jusqu'à la fin du plan (années)"),
        ("",),
        ("#", "Valeur d'entreprise et valeur par action"),
        ("methode", "Méthode de valeur terminale"),
        ("somme_fcf", "Somme des flux actualisés"),
        ("vt", "Valeur terminale"),
        ("vt_act", "Valeur terminale actualisée"),
        ("ve", "Valeur d'entreprise"),
        ("part_vt", "  dont valeur terminale"),
        ("passage", "Dette nette et autres éléments à déduire"),
        ("cp", "Valeur des capitaux propres"),
        ("actions", "Actions diluées (millions)"),
        ("action", "Valeur par action ($)"),
        ("cours", "Cours actuel ($)"),
        ("potentiel", "Écart avec le cours"),
        ("ve_ebitda", "VE / EBITDA ajusté LTM implicite"),
        ("mult_implicite", "Multiple de sortie implicite"),
        ("g_implicite", "Croissance perpétuelle implicite"),
    ], depart=5, largeur=2 + n, unite_col=None)

    lbo.disposer([
        ("#", "Prix d'acquisition (opération bouclée à la fin de l'exercice en cours)"),
        ("cours", "Cours de l'action ($)"),
        ("prime", "Prime d'acquisition"),
        ("prix_offre", "Prix d'offre par action ($)"),
        ("actions", "Actions diluées (millions)"),
        ("cp_acquis", "Prix payé pour les actions"),
        ("dette_refi", "Dette existante à refinancer"),
        ("treso_cloture", "Trésorerie de la société à la clôture"),
        ("autres", "Minoritaires et autres ajustements"),
        ("dette_nette", "Dette nette reprise"),
        ("ve_entree", "Valeur d'entreprise à l'entrée"),
        ("ebitda_ltm", "EBITDA ajusté LTM"),
        ("multiple_entree", "Multiple d'entrée (VE / EBITDA LTM)"),
        ("ebitda_n1", "EBITDA de l'exercice en cours (projeté)"),
        ("multiple_entree_n1", "Multiple d'entrée (VE / EBITDA projeté)"),
        ("",),
        ("#", "Financement de l'opération"),
        ("tete_fin", "Emplois"),
        ("fin1", "Rachat des actions"),
        ("fin2", "Refinancement de la dette existante"),
        ("fin3", "Frais de transaction"),
        ("fin4", "Frais de financement"),
        ("fin5", "Trésorerie minimale laissée dans la société"),
        ("fin_total", "Total"),
        ("fin_ecart", "Contrôle : ressources - emplois"),
        ("",),
        ("#", "Plan de financement après l'opération"),
        ("tete_plan", "Exercice"),
        ("ca", "Chiffre d'affaires"),
        ("ebitda", "EBITDA"),
        ("da", "Dotations aux amortissements"),
        ("ebit", "Résultat opérationnel (EBIT)"),
        ("interets", "Intérêts de la dette d'acquisition"),
        ("rai", "Résultat avant impôt"),
        ("impot", "Impôt sur les sociétés"),
        ("rn", "Résultat net"),
        ("capex", "Investissements (capex)"),
        ("var_bfr", "Variation du BFR"),
        ("fcf", "Trésorerie disponible pour rembourser la dette"),
        ("",),
        ("dette_debut", "Dette en début d'exercice"),
        ("amort", "Amortissement contractuel"),
        ("sweep", "Remboursement anticipé (cash sweep)"),
        ("dette_fin", "Dette en fin d'exercice"),
        ("treso_fin", "Trésorerie en fin d'exercice"),
        ("levier", "Dette / EBITDA"),
        ("couverture", "EBITDA / intérêts"),
        ("",),
        ("#", "Sortie à la fin du plan"),
        ("ebitda_sortie", "EBITDA de la dernière année"),
        ("multiple_sortie", "Multiple de sortie (VE / EBITDA)"),
        ("ve_sortie", "Valeur d'entreprise à la sortie"),
        ("passif_sortie", "Dette nette et autres éléments à déduire"),
        ("equity_sortie", "Valeur des capitaux propres à la sortie"),
        ("moic", "Multiple de la mise (MOIC)"),
        ("tri", "TRI du fonds"),
        ("",),
        ("#", "Prix maximum qu'un fonds peut payer pour atteindre son TRI"),
        ("pm_tri", "TRI visé"),
        ("pm_r", "Multiple de la mise requis"),
        ("pm_a", "EBITDA de sortie / EBITDA LTM"),
        ("pm_k", "Éléments de sortie indépendants du prix"),
        ("pm_c0", "Mise du fonds indépendante du prix"),
        ("pm_cp", "Prix maximum pour les actions"),
        ("pm_prix", "Prix maximum par action ($)"),
        ("pm_prime", "Prime correspondante sur le cours"),
    ], depart=4, largeur=2 + n, unite_col=None)

    # ------------------------------------------------------------- Hypothèses
    hy.titre("Hypothèses", "Cellules bleues sur fond jaune : à modifier. Tout le reste du classeur se recalcule. "
                           "Montants en millions de dollars.")
    S.entete(hy.ws, 3, {"A": "Hypothèse", "B": "Unité", "C": "Valeur", "D": "Justification de la valeur proposée"},
             gauche=("B", "D"))
    C = "C"

    def note(cle: str, col: str = "D") -> None:
        if cle in h.notes:
            hy.ecrire(f"{col}{hy.r(cle)}", h.notes[cle], "note")

    def saisie(cle: str, valeur, fmt: str) -> None:
        hy.ecrire(hy.a(cle, C), valeur, "hypothese", fmt)
        note(cle)

    saisie("date_valo", h.date_valo, S.FMT_DATE)
    saisie("cours", h.cours, S.FMT_PRIX)
    saisie("actions", h.actions, S.FMT_M)
    saisie("dilution", h.dilution, S.FMT_M)
    hy.ecrire(hy.a("actions_diluees", C), f"={hy.a('actions', C)}+{hy.a('dilution', C)}", fmt=S.FMT_M)
    hy.ecrire(hy.a("capitalisation", C), f"={hy.a('cours', C)}*{hy.a('actions_diluees', C)}", fmt=S.FMT_M)
    for cle in ("dette", "tresorerie", "minoritaires", "autres_ajustements"):
        saisie(cle, getattr(h, cle), S.FMT_M)
    hy.ecrire(hy.a("dette_nette", C), f"={hy.a('dette', C)}-{hy.a('tresorerie', C)}", fmt=S.FMT_M)
    hy.ecrire(hy.a("passage", C),
              f"={hy.a('dette_nette', C)}+{hy.a('minoritaires', C)}+{hy.a('autres_ajustements', C)}", fmt=S.FMT_M)
    hy.ecrire(hy.a("valeur_entreprise", C), f"={hy.a('capitalisation', C)}+{hy.a('passage', C)}",
              fmt=S.FMT_M, total=True)

    S.entete(hy.ws, hy.r("annees"), {"A": "Exercice", "B": "Unité", **dict(zip(PC, annees_p)),
                                     L(3 + n): "Justification de la valeur proposée"}, gauche=("B", L(3 + n)))
    for cle, fmt in (("croissance", S.FMT_PCT), ("marge_ebitda", S.FMT_PCT), ("da_pct", S.FMT_PCT),
                     ("capex_pct", S.FMT_PCT), ("bfr_pct", S.FMT_PCT), ("distributions", S.FMT_M)):
        for col, v in zip(PC, getattr(h, cle)):
            hy.ecrire(hy.a(cle, col), v, "hypothese", fmt)
        note(cle, L(3 + n))
    for cle in ("passif_expl_pct", "taux_is"):
        saisie(cle, getattr(h, cle), S.FMT_PCT)
    for cle in ("cout_dette", "rendement_treso", "taux_sans_risque", "prime_marche"):
        saisie(cle, getattr(h, cle), FMT_PCT2)
    saisie("beta_brut", h.beta_brut, S.FMT_NB)
    saisie("poids_blume", h.poids_blume, S.FMT_NB)
    hy.ecrire(hy.a("beta", C),
              f"={hy.a('poids_blume', C)}*{hy.a('beta_brut', C)}+(1-{hy.a('poids_blume', C)})", fmt=S.FMT_NB)
    saisie("prime_specifique", h.prime_specifique, FMT_PCT2)
    hy.ecrire(hy.a("cout_fonds_propres", C),
              f"={hy.a('taux_sans_risque', C)}+{hy.a('beta', C)}*{hy.a('prime_marche', C)}+{hy.a('prime_specifique', C)}",
              fmt=FMT_PCT2)
    hy.ecrire(f"D{hy.r('cout_fonds_propres')}", "MEDAF : taux sans risque + bêta x prime de marché + prime spécifique.", "note")
    saisie("poids_dette", h.poids_dette, S.FMT_PCT)
    hy.ecrire(hy.a("wacc", C),
              f"=(1-{hy.a('poids_dette', C)})*{hy.a('cout_fonds_propres', C)}"
              f"+{hy.a('poids_dette', C)}*{hy.a('cout_dette', C)}*(1-{hy.a('taux_is', C)})",
              fmt=FMT_PCT2, total=True)
    hy.ecrire(f"D{hy.r('wacc')}", "Fonds propres et dette après impôt, pondérés par leur poids dans le financement.", "note")
    saisie("croissance_perpetuelle", h.croissance_perpetuelle, FMT_PCT2)
    saisie("mi_annee", h.mi_annee, S.FMT_ENTIER)
    for cle, fmt in (("prime_acquisition", S.FMT_PCT), ("levier", S.FMT_X), ("taux_lbo", FMT_PCT2),
                     ("amort_pct", S.FMT_PCT), ("sweep_pct", S.FMT_PCT), ("treso_min", S.FMT_M),
                     ("frais_transaction", S.FMT_PCT), ("frais_financement", S.FMT_PCT),
                     ("ecart_multiple_sortie", S.FMT_X), ("tri_cible", S.FMT_PCT),
                     ("tri_cible_haut", S.FMT_PCT), ("pas_wacc", FMT_PCT2), ("pas_g", FMT_PCT2),
                     ("pas_multiple", S.FMT_X), ("pas_prime", S.FMT_PCT), ("plafond_multiple", S.FMT_X)):
        saisie(cle, getattr(h, cle), fmt)
    S.largeurs(hy.ws, 50, 13, 3 + n, {"B": 16})
    hy.ws.freeze_panes = "C4"

    # ------------------------------------------------------------- Historique
    depots = " ; ".join(soc.depots.values())
    hi.titre(f"{nom_court} : comptes publiés retraités",
             f"Millions de dollars. Source : SEC EDGAR, {depots}. Chiffres bleus : données publiées.")
    S.entete(hi.ws, 4, {"A": "", **dict(zip(HC, annees_h)), HL: "12 derniers mois",
                        HS: "Source (balise XBRL de la SEC, ou mode de calcul)"}, gauche=(HS,))
    for col, d in zip(HC, soc.exercices):
        hi.ecrire(hi.a("fin", col), d, "saisie", S.FMT_DATE)
    hi.ecrire(hi.a("fin", HL), soc.date_ltm, "saisie", S.FMT_DATE)
    aj = soc.ajustements
    src = soc.sources
    sources = {
        "ca": src.get("ca", ""), "marge_brute": src.get("marge_brute", ""), "ebit": src.get("ebit", ""),
        "da": src.get("da", ""), "ebitda_publie": "EBIT + D&A",
        "depreciations": "Dépréciations d'actifs (impairments) : charge sans décaissement, non récurrente",
        "ajust": aj.source_ebitda or "Aucun ajustement (fichier d'ajustements)",
        "ebitda_ajuste": "EBITDA publié + dépréciations + ajustements",
        "ebit_ajuste": "EBITDA ajusté - D&A", "interets": src.get("interets", ""),
        "produits_fin": src.get("produits_fin", ""), "rai": src.get("rai", ""),
        "impot": src.get("impot", ""), "rn": src.get("rn", ""),
        "ajust_rn": aj.source_resultat_net or "Aucun ajustement (fichier d'ajustements)",
        "rn_ajuste": "Résultat net + ajustements : sert au PER", "sbc": src.get("sbc", ""),
        "cfo": src.get("cfo", ""),
        "capex": (aj.source_capex if aj.capex else src.get("capex", "")),
        "rachats": src.get("rachats", ""), "dividendes": src.get("dividendes", ""),
        "tresorerie": src.get("caisse", "") + (" + " + src["placements"] if "placements" in src else ""),
        "actif_circ_expl": "AssetsCurrent - trésorerie et placements",
        "immo_nettes": " + ".join(x for x in (src.get("immo_corporelles"), src.get("immo_incorporelles")) if x),
        "goodwill": src.get("goodwill", ""),
        "autres_actifs": "Solde : total de l'actif publié - postes ci-dessus (droits d'usage, impôts différés...)",
        "passif_expl": "LiabilitiesCurrent - part courante de la dette financière",
        "dette": "Dette à long terme + part courante + emprunts à court terme (hors dettes de location)",
        "autres_passifs": "Solde : total du passif publié - autres postes (dettes de location, provisions...)",
        "capitaux_propres": "Capitaux propres, intérêts minoritaires inclus",
        "total_actif": "Somme ; égale à la balise Assets par construction",
        "total_passif": "Somme ; égale à LiabilitiesAndStockholdersEquity par construction",
    }
    for cle, texte in sources.items():
        hi.ecrire(hi.a(cle, HS), texte, "note")

    donnees = ("ca", "marge_brute", "ebit", "da", "depreciations", "ajust", "interets", "produits_fin",
               "rai", "impot", "rn", "sbc", "cfo", "capex", "rachats", "dividendes", "tresorerie",
               "actif_circ_expl", "immo_nettes", "goodwill", "autres_actifs", "passif_expl", "dette",
               "autres_passifs", "capitaux_propres")
    for cle in donnees:
        for col, v in zip(HC, soc.hist[cle]):
            if v is None and cle in ("rachats", "dividendes"):
                v = 0.0                      # poste absent des comptes : aucun versement
            if v is not None:
                hi.ecrire(hi.a(cle, col), v, "saisie", S.FMT_M)
    for col, d in zip(HC, soc.exercices):
        hi.ecrire(hi.a("ajust_rn", col), aj.resultat_net.get(d.isoformat(), 0.0), "saisie", S.FMT_M)
    for cle in ("ca", "marge_brute", "ebit", "da", "depreciations", "ajust", "rn", "ajust_rn"):
        if soc.ltm.get(cle) is not None:
            hi.ecrire(hi.a(cle, HL), soc.ltm[cle], "saisie", S.FMT_M)
    hi.ecrire(hi.a("tresorerie", HL), soc.bilan["tresorerie"], "saisie", S.FMT_M)
    hi.ecrire(hi.a("dette", HL), soc.bilan["dette"], "saisie", S.FMT_M)

    avec_marge_brute = soc.hist["marge_brute"][-1] is not None
    for i, col in enumerate(HC + [HL]):
        est_ltm = col == HL
        g = hi.a
        if i > 0:
            hi.ecrire(g("croissance", col), f"={g('ca', col)}/{g('ca', HC[i - 1] if not est_ltm else HD)}-1", fmt=S.FMT_PCT)
        if avec_marge_brute and (not est_ltm or soc.ltm.get("marge_brute") is not None):
            hi.ecrire(g("marge_brute_pct", col), f"={g('marge_brute', col)}/{g('ca', col)}", fmt=S.FMT_PCT)
        hi.ecrire(g("ebitda_publie", col), f"={g('ebit', col)}+{g('da', col)}", fmt=S.FMT_M)
        hi.ecrire(g("ebitda_ajuste", col), f"={g('ebitda_publie', col)}+{g('depreciations', col)}+{g('ajust', col)}",
                  fmt=S.FMT_M, total=True)
        hi.ecrire(g("marge_ebitda", col), f"={g('ebitda_ajuste', col)}/{g('ca', col)}", fmt=S.FMT_PCT)
        hi.ecrire(g("ebit_ajuste", col), f"={g('ebitda_ajuste', col)}-{g('da', col)}", fmt=S.FMT_M)
        hi.ecrire(g("rn_ajuste", col), f"={g('rn', col)}+{g('ajust_rn', col)}", fmt=S.FMT_M)
        hi.ecrire(g("da_pct", col), f"={g('da', col)}/{g('ca', col)}", fmt=S.FMT_PCT)
        if est_ltm:
            continue
        hi.ecrire(g("taux_effectif", col), f'=IF({g("rai", col)}>0,{g("impot", col)}/{g("rai", col)},"n.s.")', fmt=S.FMT_PCT)
        hi.ecrire(g("fcf", col), f"={g('cfo', col)}-{g('capex', col)}", fmt=S.FMT_M)
        hi.ecrire(g("capex_pct", col), f"={g('capex', col)}/{g('ca', col)}", fmt=S.FMT_PCT)
        hi.ecrire(g("total_actif", col), f"=SUM({g('tresorerie', col)}:{g('autres_actifs', col)})", fmt=S.FMT_M, total=True)
        hi.ecrire(g("total_passif", col), f"=SUM({g('passif_expl', col)}:{g('capitaux_propres', col)})", fmt=S.FMT_M, total=True)
        hi.ecrire(g("ecart", col), f"={g('total_actif', col)}-{g('total_passif', col)}", fmt=S.FMT_M)
        hi.ecrire(g("bfr", col), f"={g('actif_circ_expl', col)}-{g('passif_expl', col)}", fmt=S.FMT_M)
        hi.ecrire(g("bfr_pct", col), f"={g('bfr', col)}/{g('ca', col)}", fmt=S.FMT_PCT)
        hi.ecrire(g("passif_expl_pct", col), f"={g('passif_expl', col)}/{g('ca', col)}", fmt=S.FMT_PCT)
    hi.ecrire(f"A{hi.r('passif_expl_pct') + 2}",
              f"Colonne « 12 derniers mois » : flux = dernier exercice + cumul de l'exercice en cours - même cumul un an plus tôt ; "
              f"trésorerie et dette au dernier bilan publié ({soc.date_bilan.strftime('%d/%m/%Y')}).", "note")
    S.largeurs(hi.ws, 50, 13, 3 + nh, {"B": 3, HL: 17, HS: 70})
    hi.ws.freeze_panes = "C5"

    # ------------------------------------------------------------ Projections
    pr.titre(f"{nom_court} : projection des trois états financiers",
             "Millions de dollars. Société seule, sans opération : la dette reste constante, la trésorerie absorbe les flux.")
    S.entete(pr.ws, 4, {"A": "", PB: annees_h[-1], **dict(zip(PC, annees_p))})
    pr.ecrire(pr.a("fin", PB), f"={hi.x('fin', HD)}", "lien", S.FMT_DATE)
    liens_base = {"ca": "ca", "croissance": "croissance", "ebitda": "ebitda_ajuste", "da": "da",
                  "ebit": "ebit_ajuste", "interets": "interets", "produits_fin": "produits_fin",
                  "rai": "rai", "impot": "impot", "rn": "rn", "capex": "capex",
                  "tresorerie": "tresorerie", "actif_circ_expl": "actif_circ_expl",
                  "immo_nettes": "immo_nettes", "goodwill": "goodwill", "autres_actifs": "autres_actifs",
                  "passif_expl": "passif_expl", "dette": "dette", "autres_passifs": "autres_passifs",
                  "capitaux_propres": "capitaux_propres", "bfr": "bfr"}
    for cle, cle_hist in liens_base.items():
        pr.ecrire(pr.a(cle, PB), f"={hi.x(cle_hist, HD)}", "lien", S.FMT_PCT if cle == "croissance" else S.FMT_M)
    pr.ecrire(pr.a("marge", PB), f"={pr.a('ebitda', PB)}/{pr.a('ca', PB)}", fmt=S.FMT_PCT)
    g = pr.a
    for i, col in enumerate(PC):
        p = PB if i == 0 else PC[i - 1]
        pr.ecrire(g("fin", col), f"=EDATE({g('fin', p)},12)", fmt=S.FMT_DATE)
        pr.ecrire(g("ca", col), f"={g('ca', p)}*(1+{hy.x('croissance', col)})", fmt=S.FMT_M)
        pr.ecrire(g("croissance", col), f"={hy.x('croissance', col)}", "lien", S.FMT_PCT)
        pr.ecrire(g("ebitda", col), f"={g('ca', col)}*{hy.x('marge_ebitda', col)}", fmt=S.FMT_M, total=True)
        pr.ecrire(g("marge", col), f"={g('ebitda', col)}/{g('ca', col)}", fmt=S.FMT_PCT)
        pr.ecrire(g("da", col), f"={g('ca', col)}*{hy.x('da_pct', col)}", fmt=S.FMT_M)
        pr.ecrire(g("ebit", col), f"={g('ebitda', col)}-{g('da', col)}", fmt=S.FMT_M)
        pr.ecrire(g("interets", col), f"={g('dette', p)}*{hy.x('cout_dette', C)}", fmt=S.FMT_M)
        pr.ecrire(g("produits_fin", col), f"={g('tresorerie', p)}*{hy.x('rendement_treso', C)}", fmt=S.FMT_M)
        pr.ecrire(g("rai", col), f"={g('ebit', col)}-{g('interets', col)}+{g('produits_fin', col)}", fmt=S.FMT_M)
        pr.ecrire(g("impot", col), f"=MAX(0,{g('rai', col)})*{hy.x('taux_is', C)}", fmt=S.FMT_M)
        pr.ecrire(g("rn", col), f"={g('rai', col)}-{g('impot', col)}", fmt=S.FMT_M, total=True)
        pr.ecrire(g("capex", col), f"={g('ca', col)}*{hy.x('capex_pct', col)}", fmt=S.FMT_M)
        pr.ecrire(g("var_bfr", col), f"={g('bfr', col)}-{g('bfr', p)}", fmt=S.FMT_M)
        pr.ecrire(g("distributions", col), f"={hy.x('distributions', col)}", "lien", S.FMT_M)
        pr.ecrire(g("var_treso", col),
                  f"={g('rn', col)}+{g('da', col)}-{g('var_bfr', col)}-{g('capex', col)}-{g('distributions', col)}",
                  fmt=S.FMT_M, total=True)
        pr.ecrire(g("tresorerie", col), f"={g('tresorerie', p)}+{g('var_treso', col)}", fmt=S.FMT_M)
        pr.ecrire(g("actif_circ_expl", col), f"={g('bfr', col)}+{g('passif_expl', col)}", fmt=S.FMT_M)
        pr.ecrire(g("immo_nettes", col), f"={g('immo_nettes', p)}+{g('capex', col)}-{g('da', col)}", fmt=S.FMT_M)
        for constant in ("goodwill", "autres_actifs", "dette", "autres_passifs"):
            pr.ecrire(g(constant, col), f"={g(constant, p)}", fmt=S.FMT_M)
        pr.ecrire(g("passif_expl", col), f"={g('ca', col)}*{hy.x('passif_expl_pct', C)}", fmt=S.FMT_M)
        pr.ecrire(g("capitaux_propres", col),
                  f"={g('capitaux_propres', p)}+{g('rn', col)}-{g('distributions', col)}", fmt=S.FMT_M)
        pr.ecrire(g("bfr", col), f"={g('ca', col)}*{hy.x('bfr_pct', col)}", fmt=S.FMT_M)
    for col in [PB] + PC:
        pr.ecrire(g("total_actif", col), f"=SUM({g('tresorerie', col)}:{g('autres_actifs', col)})", fmt=S.FMT_M, total=True)
        pr.ecrire(g("total_passif", col), f"=SUM({g('passif_expl', col)}:{g('capitaux_propres', col)})", fmt=S.FMT_M, total=True)
        pr.ecrire(g("ecart", col), f"={g('total_actif', col)}-{g('total_passif', col)}", fmt=S.FMT_M)
    S.largeurs(pr.ws, 46, 13, 2 + n)
    pr.ws.freeze_panes = "B5"

    # -------------------------------------------------------------------- DCF
    dcf.titre(f"{nom_court} : valorisation par les flux actualisés (DCF)",
              "Millions de dollars. Deux valeurs terminales calculées côte à côte.")
    S.entete(dcf.ws, 4, {"A": "", "B": "", **dict(zip(PC, annees_p))})
    g = dcf.a
    for cle, fmt, ref in (("wacc", FMT_PCT2, hy.x("wacc", C)), ("g", FMT_PCT2, hy.x("croissance_perpetuelle", C)),
                          ("multiple", S.FMT_X, hy.x("multiple_sortie_dcf", C))):
        dcf.ecrire(g(cle, C), f"={ref}", "lien", fmt)
    dcf.ecrire(g("fraction", C), f"=MAX(0,MIN(1,({pr.x('fin', P1)}-{hy.x('date_valo', C)})/365))", fmt=S.FMT_NB)
    dcf.ecrire(g("temps_fin", C), f"={g('fraction', C)}+COUNT({g('fcf', P1)}:{g('fcf', PN)})-1", fmt=S.FMT_NB)
    for i, col in enumerate(PC):
        for cle in ("ebit", "da", "capex", "var_bfr"):
            dcf.ecrire(g(cle, col), f"={pr.x(cle, col).replace('$' + col, col)}", "lien", S.FMT_M)
        dcf.ecrire(g("impot_ebit", col), f"={g('ebit', col)}*{hy.x('taux_is', C)}", fmt=S.FMT_M)
        dcf.ecrire(g("nopat", col), f"={g('ebit', col)}-{g('impot_ebit', col)}", fmt=S.FMT_M)
        dcf.ecrire(g("fcf", col), f"={g('nopat', col)}+{g('da', col)}-{g('capex', col)}-{g('var_bfr', col)}",
                   fmt=S.FMT_M, total=True)
        fr, mi = g("fraction", C, True), hy.x("mi_annee", C)
        if i == 0:
            dcf.ecrire(g("poids", col), f"={fr}", fmt=S.FMT_NB)
            dcf.ecrire(g("temps", col), f"={fr}*(1-0.5*{mi})", fmt=S.FMT_NB)
        else:
            dcf.ecrire(g("poids", col), "=1", fmt=S.FMT_NB)
            dcf.ecrire(g("temps", col), f"={fr}+1-0.5*{mi}" if i == 1 else f"={g('temps', PC[i - 1])}+1", fmt=S.FMT_NB)
        dcf.ecrire(g("facteur", col), f"=1/(1+{g('wacc', C, True)})^{g('temps', col)}", fmt="0.000")
        dcf.ecrire(g("fcf_act", col), f"={g('fcf', col)}*{g('poids', col)}*{g('facteur', col)}", fmt=S.FMT_M)
    S.entete(dcf.ws, dcf.r("methode"), {"A": "Méthode de valeur terminale", "B": "", "C": "Croissance perp.",
                                         "D": "Multiple de sortie"})
    D = "D"
    w = g("wacc", C, True)
    for col in (C, D):
        dcf.ecrire(g("somme_fcf", col), f"=SUM({g('fcf_act', P1, True)}:{g('fcf_act', PN, True)})", fmt=S.FMT_M)
        dcf.ecrire(g("ve", col), f"={g('somme_fcf', col)}+{g('vt_act', col)}", fmt=S.FMT_M, total=True)
        dcf.ecrire(g("part_vt", col), f"={g('vt_act', col)}/{g('ve', col)}", fmt=S.FMT_PCT)
        dcf.ecrire(g("passage", col), f"={hy.x('passage', C)}", "lien", S.FMT_M)
        dcf.ecrire(g("cp", col), f"={g('ve', col)}-{g('passage', col)}", fmt=S.FMT_M, total=True)
        dcf.ecrire(g("actions", col), f"={hy.x('actions_diluees', C)}", "lien", S.FMT_M)
        dcf.ecrire(g("action", col), f"={g('cp', col)}/{g('actions', col)}", fmt=S.FMT_PRIX, gras=True)
        dcf.ecrire(g("cours", col), f"={hy.x('cours', C)}", "lien", S.FMT_PRIX)
        dcf.ecrire(g("potentiel", col), f"={g('action', col)}/{g('cours', col)}-1", fmt=S.FMT_PCT)
        dcf.ecrire(g("ve_ebitda", col), f"={g('ve', col)}/{hi.x('ebitda_ajuste', HL)}", fmt=S.FMT_X)
    dcf.ecrire(g("vt", C), f"={g('fcf', PN)}*(1+{g('g', C)})/({w}-{g('g', C)})", fmt=S.FMT_M)
    dcf.ecrire(g("vt_act", C), f"={g('vt', C)}*{g('facteur', PN)}", fmt=S.FMT_M)
    dcf.ecrire(g("vt", D), f"={pr.x('ebitda', PN)}*{g('multiple', C)}", fmt=S.FMT_M)
    dcf.ecrire(g("vt_act", D), f"={g('vt', D)}/(1+{w})^{g('temps_fin', C)}", fmt=S.FMT_M)
    dcf.ecrire(g("mult_implicite", C), f"={g('vt', C)}/{pr.x('ebitda', PN)}", fmt=S.FMT_X)
    dcf.ecrire(g("g_implicite", D), f"=({g('vt', D)}*{w}-{g('fcf', PN)})/({g('vt', D)}+{g('fcf', PN)})", fmt=FMT_PCT2)
    S.largeurs(dcf.ws, 46, 4, 2 + n, {**{c: 18 for c in PC}})
    dcf.ws.freeze_panes = "C5"

    # ------------------------------------------------------------ Comparables
    co.titre("Comparables boursiers",
             "Millions de dollars, agrégats sur 12 mois glissants (LTM). EBITDA et EBIT hors dépréciations d'actifs. "
             "« n.s. » : multiple non significatif (dénominateur négatif ou multiple au-delà du plafond).")
    cols = dict(zip(("nom", "ticker", "cours", "actions", "capi", "dette", "treso", "mino", "ve", "ca",
                     "ebitda", "ebit", "rn", "ve_ca", "ve_ebitda", "ve_ebit", "per", "date", "note"),
                    "ABCDEFGHIJKLMNOPQRS"))
    K = cols
    S.entete(co.ws, 4, {K["nom"]: "Société", K["ticker"]: "Ticker", K["cours"]: "Cours ($)",
                        K["actions"]: "Actions (M)", K["capi"]: "Capitalisation", K["dette"]: "Dette financière",
                        K["treso"]: "Trésorerie", K["mino"]: "Minoritaires", K["ve"]: "Valeur d'entreprise",
                        K["ca"]: "CA", K["ebitda"]: "EBITDA", K["ebit"]: "EBIT", K["rn"]: "Résultat net",
                        K["ve_ca"]: "VE / CA", K["ve_ebitda"]: "VE / EBITDA", K["ve_ebit"]: "VE / EBIT",
                        K["per"]: "PER", K["date"]: "LTM au", K["note"]: "Source et remarques"},
             gauche=(K["ticker"], K["note"]))
    pairs = res.comps.pairs
    premier, ligne = 5, 5
    plafond_ref = hy.x("plafond_multiple", C)

    def multiples(r: int) -> None:
        ve, capi = f"{K['ve']}{r}", f"{K['capi']}{r}"
        co.ecrire(f"{K['ve_ca']}{r}", f'=IF({K["ca"]}{r}>0,{ve}/{K["ca"]}{r},"n.s.")', fmt=S.FMT_X)
        for cle, num, den in (("ve_ebitda", ve, f"{K['ebitda']}{r}"), ("ve_ebit", ve, f"{K['ebit']}{r}"),
                              ("per", capi, f"{K['rn']}{r}")):
            co.ecrire(f"{K[cle]}{r}",
                      f'=IF({den}>0,IF({num}/{den}<={plafond_ref},{num}/{den},"n.s."),"n.s.")', fmt=S.FMT_X)

    for p in pairs:
        s = p.societe
        co.lig[f"pair_{s.ticker}"] = ligne
        co.ecrire(f"{K['nom']}{ligne}", s.nom.title())
        co.ecrire(f"{K['ticker']}{ligne}", s.ticker)
        for cle, v, fmt in (("cours", p.cours.cours, S.FMT_PRIX), ("actions", s.actions, S.FMT_M),
                            ("dette", s.bilan["dette"], S.FMT_M), ("treso", s.bilan["tresorerie"], S.FMT_M),
                            ("mino", s.bilan["minoritaires"], S.FMT_M), ("ca", s.ltm["ca"], S.FMT_M),
                            ("ebitda", s.ltm["ebitda_ajuste"], S.FMT_M), ("ebit", s.ltm["ebit_ajuste"], S.FMT_M),
                            ("rn", s.ltm["rn_ajuste"], S.FMT_M)):
            co.ecrire(f"{K[cle]}{ligne}", v, "saisie", fmt)
        co.ecrire(f"{K['capi']}{ligne}", f"={K['cours']}{ligne}*{K['actions']}{ligne}", fmt=S.FMT_M)
        co.ecrire(f"{K['ve']}{ligne}",
                  f"={K['capi']}{ligne}+{K['dette']}{ligne}-{K['treso']}{ligne}+{K['mino']}{ligne}", fmt=S.FMT_M)
        multiples(ligne)
        co.ecrire(f"{K['date']}{ligne}", s.date_ltm, "saisie", S.FMT_DATE)
        remarques = [f"{p.cours.source} ; {s.depots.get('trimestriel') or s.depots.get('annuel', '')}"]
        remarques += [a.replace(f"{s.ticker} : ", "") for a in s.alertes]
        co.ecrire(f"{K['note']}{ligne}", " | ".join(remarques), "note")
        ligne += 1
    dernier = ligne - 1
    ligne += 1
    for cle, libelle, formule in (("max", "Maximum", "MAX({p})"), ("q3", "3e quartile", "QUARTILE({p},3)"),
                                  ("mediane", "Médiane", "MEDIAN({p})"), ("q1", "1er quartile", "QUARTILE({p},1)"),
                                  ("min", "Minimum", "MIN({p})")):
        co.lig[cle] = ligne
        co.ecrire(f"A{ligne}", libelle, gras=(cle == "mediane"))
        for m in ("ve_ca", "ve_ebitda", "ve_ebit", "per"):
            plage = f"{K[m]}{premier}:{K[m]}{dernier}" if pairs else f"{K[m]}{premier}"
            corps = formule.format(p=plage)
            co.ecrire(f"{K[m]}{ligne}", f'=IF(COUNT({plage})=0,"n.s.",{corps})', fmt=S.FMT_X, gras=(cle == "mediane"))
        ligne += 1
    ligne += 1
    co.lig["cible"] = ligne
    co.ecrire(f"{K['nom']}{ligne}", f"{nom_court} (cible)", gras=True)
    co.ecrire(f"{K['ticker']}{ligne}", soc.ticker, gras=True)
    for cle, ref, fmt in (("cours", hy.x("cours", C), S.FMT_PRIX), ("actions", hy.x("actions_diluees", C), S.FMT_M),
                          ("capi", hy.x("capitalisation", C), S.FMT_M), ("dette", hy.x("dette", C), S.FMT_M),
                          ("treso", hy.x("tresorerie", C), S.FMT_M), ("mino", hy.x("minoritaires", C), S.FMT_M),
                          ("ve", hy.x("valeur_entreprise", C), S.FMT_M), ("ca", hi.x("ca", HL), S.FMT_M),
                          ("ebitda", hi.x("ebitda_ajuste", HL), S.FMT_M), ("ebit", hi.x("ebit_ajuste", HL), S.FMT_M),
                          ("rn", hi.x("rn_ajuste", HL), S.FMT_M), ("date", hi.x("fin", HL), S.FMT_DATE)):
        co.ecrire(f"{K[cle]}{ligne}", f"={ref}", "lien", fmt)
    multiples(ligne)
    co.ecrire(f"{K['note']}{ligne}", "Agrégats ajustés de l'onglet Historique (colonne 12 derniers mois).", "note")
    ligne += 2
    S.bandeau(co.ws, ligne, "Valeur de la cible si on lui applique les multiples des comparables", 11)
    ligne += 1
    S.entete(co.ws, ligne, {"A": "Multiple appliqué", "B": "", "C": "Agrégat LTM", "D": "1er quartile",
                            "E": "Médiane", "F": "3e quartile", "G": "VE (1er q.)", "H": "VE (médiane)",
                            "I": "VE (3e q.)", "J": "$/action (1er q.)", "K": "$/action (méd.)",
                            "L": "$/action (3e q.)"})
    ligne += 1
    rc = co.lig["cible"]
    for cle, libelle, agregat in (("ve_ebitda", "VE / EBITDA", f"{K['ebitda']}{rc}"),
                                  ("ve_ebit", "VE / EBIT", f"{K['ebit']}{rc}"), ("per", "PER", f"{K['rn']}{rc}")):
        co.lig[f"imp_{cle}"] = ligne
        co.ecrire(f"A{ligne}", libelle)
        co.ecrire(f"C{ligne}", f"={agregat}", fmt=S.FMT_M)
        for q, cm, cv, ca_ in (("q1", "D", "G", "J"), ("mediane", "E", "H", "K"), ("q3", "F", "I", "L")):
            co.ecrire(f"{cm}{ligne}", f"={K[cle]}{co.lig[q]}", fmt=S.FMT_X)
            if cle == "per":
                co.ecrire(f"{ca_}{ligne}", f'=IFERROR({cm}{ligne}*$C{ligne}/{hy.x("actions_diluees", C)},"n.s.")',
                          fmt=S.FMT_PRIX)
            else:
                co.ecrire(f"{cv}{ligne}", f'=IFERROR({cm}{ligne}*$C{ligne},"n.s.")', fmt=S.FMT_M)
                co.ecrire(f"{ca_}{ligne}",
                          f'=IFERROR(({cv}{ligne}-{hy.x("passage", C)})/{hy.x("actions_diluees", C)},"n.s.")',
                          fmt=S.FMT_PRIX)
        ligne += 1
    S.largeurs(co.ws, 30, 13, 18, {"B": 9, "S": 90})
    co.ws.freeze_panes = "C5"

    if res.comps.stats["ve_ebitda"]["mediane"] is not None and "multiple_sortie_dcf" not in res.surcharges:
        hy.ecrire(hy.a("multiple_sortie_dcf", C), f"={co.x('mediane', K['ve_ebitda'])}", "lien", S.FMT_X)
        S.fond_hypothese(hy.ws[hy.a("multiple_sortie_dcf", C)])
        note("multiple_sortie_dcf")
    else:
        saisie("multiple_sortie_dcf", h.multiple_sortie_dcf, S.FMT_X)

    # -------------------------------------------------------------------- LBO
    PL = PC[1:]                     # exercices du plan, après la clôture
    L1, LN = PL[0], PL[-1]
    lbo.titre(f"{nom_court} : rachat avec effet de levier (LBO)",
              "Millions de dollars. Opération bouclée à la fin de l'exercice en cours, revente à la fin du plan.")
    g = lbo.a
    for cle, ref, fmt in (("cours", hy.x("cours", C), S.FMT_PRIX), ("prime", hy.x("prime_acquisition", C), S.FMT_PCT),
                          ("actions", hy.x("actions_diluees", C), S.FMT_M), ("dette_refi", pr.x("dette", P1), S.FMT_M),
                          ("treso_cloture", pr.x("tresorerie", P1), S.FMT_M),
                          ("ebitda_ltm", hi.x("ebitda_ajuste", HL), S.FMT_M), ("ebitda_n1", pr.x("ebitda", P1), S.FMT_M)):
        lbo.ecrire(g(cle, C), f"={ref}", "lien", fmt)
    lbo.ecrire(g("autres", C), f"={hy.x('minoritaires', C)}+{hy.x('autres_ajustements', C)}", "lien", S.FMT_M)
    lbo.ecrire(g("prix_offre", C), f"={g('cours', C)}*(1+{g('prime', C)})", fmt=S.FMT_PRIX)
    lbo.ecrire(g("cp_acquis", C), f"={g('prix_offre', C)}*{g('actions', C)}", fmt=S.FMT_M)
    lbo.ecrire(g("dette_nette", C), f"={g('dette_refi', C)}-{g('treso_cloture', C)}+{g('autres', C)}", fmt=S.FMT_M)
    lbo.ecrire(g("ve_entree", C), f"={g('cp_acquis', C)}+{g('dette_nette', C)}", fmt=S.FMT_M, total=True)
    lbo.ecrire(g("multiple_entree", C), f"={g('ve_entree', C)}/{g('ebitda_ltm', C)}", fmt=S.FMT_X, gras=True)
    lbo.ecrire(g("multiple_entree_n1", C), f"={g('ve_entree', C)}/{g('ebitda_n1', C)}", fmt=S.FMT_X)

    E, G = "E", "G"                 # tableau des ressources, à droite des emplois
    S.entete(lbo.ws, lbo.r("tete_fin"), {"A": "Emplois", "C": "M$", E: "Ressources", "F": "", G: "M$"}, gauche=(E,))
    lbo.ecrire(g("fin1", C), f"={g('cp_acquis', C)}", fmt=S.FMT_M)
    lbo.ecrire(g("fin2", C), f"={g('dette_refi', C)}", fmt=S.FMT_M)
    lbo.ecrire(g("fin3", C), f"={hy.x('frais_transaction', C)}*{g('ve_entree', C)}", fmt=S.FMT_M)
    lbo.ecrire(g("fin4", C), f"={hy.x('frais_financement', C)}*{g('fin1', G)}", fmt=S.FMT_M)
    lbo.ecrire(g("fin5", C), f"={hy.x('treso_min', C)}", "lien", S.FMT_M)
    lbo.ecrire(g("fin_total", C), f"=SUM({g('fin1', C)}:{g('fin5', C)})", fmt=S.FMT_M, total=True)
    for cle, libelle in (("fin1", "Dette d'acquisition"), ("fin2", "Trésorerie de la société"),
                         ("fin3", "Fonds propres apportés par le fonds"), ("fin4", "  part des fonds propres"),
                         ("fin_total", "Total")):
        lbo.ecrire(g(cle, E), libelle)
    lbo.ecrire(g("fin1", G), f"={hy.x('levier', C)}*{g('ebitda_ltm', C)}", fmt=S.FMT_M)
    lbo.ecrire(g("fin2", G), f"={g('treso_cloture', C)}", fmt=S.FMT_M)
    lbo.ecrire(g("fin3", G), f"={g('fin_total', C)}-{g('fin1', G)}-{g('fin2', G)}", fmt=S.FMT_M, gras=True)
    lbo.ecrire(g("fin4", G), f"={g('fin3', G)}/{g('fin_total', G)}", fmt=S.FMT_PCT)
    lbo.ecrire(g("fin_total", G), f"=SUM({g('fin1', G)}:{g('fin3', G)})", fmt=S.FMT_M, total=True)
    lbo.ecrire(g("fin_ecart", C), f"={g('fin_total', G)}-{g('fin_total', C)}", fmt=S.FMT_M)
    dette0, equity0 = g("fin1", G, True), g("fin3", G, True)

    S.entete(lbo.ws, lbo.r("tete_plan"), {"A": "Exercice", "B": "", P1: "Clôture", **dict(zip(PL, annees_p[1:]))})
    for i, col in enumerate(PL):
        p = P1 if i == 0 else PL[i - 1]
        for cle in ("ca", "ebitda", "da", "ebit", "capex", "var_bfr"):
            lbo.ecrire(g(cle, col), f"={pr.x(cle, col).replace('$' + col, col)}", "lien", S.FMT_M)
        lbo.ecrire(g("dette_debut", col), f"={g('dette_fin', p)}", fmt=S.FMT_M)
        lbo.ecrire(g("interets", col), f"={g('dette_debut', col)}*{hy.x('taux_lbo', C)}", fmt=S.FMT_M)
        lbo.ecrire(g("rai", col), f"={g('ebit', col)}-{g('interets', col)}", fmt=S.FMT_M)
        lbo.ecrire(g("impot", col), f"=MAX(0,{g('rai', col)})*{hy.x('taux_is', C)}", fmt=S.FMT_M)
        lbo.ecrire(g("rn", col), f"={g('rai', col)}-{g('impot', col)}", fmt=S.FMT_M)
        lbo.ecrire(g("fcf", col), f"={g('rn', col)}+{g('da', col)}-{g('capex', col)}-{g('var_bfr', col)}",
                   fmt=S.FMT_M, total=True)
        lbo.ecrire(g("amort", col), f"=MIN({g('dette_debut', col)},{dette0}*{hy.x('amort_pct', C)})", fmt=S.FMT_M)
        lbo.ecrire(g("sweep", col),
                   f"=MAX(0,MIN({g('dette_debut', col)}-{g('amort', col)},"
                   f"({g('fcf', col)}-{g('amort', col)})*{hy.x('sweep_pct', C)}))", fmt=S.FMT_M)
        lbo.ecrire(g("dette_fin", col), f"={g('dette_debut', col)}-{g('amort', col)}-{g('sweep', col)}",
                   fmt=S.FMT_M, total=True)
        lbo.ecrire(g("treso_fin", col), f"={g('treso_fin', p)}+{g('fcf', col)}-{g('amort', col)}-{g('sweep', col)}",
                   fmt=S.FMT_M)
        lbo.ecrire(g("levier", col), f"={g('dette_fin', col)}/{g('ebitda', col)}", fmt=S.FMT_X)
        lbo.ecrire(g("couverture", col), f"={g('ebitda', col)}/{g('interets', col)}", fmt=S.FMT_X)
    lbo.ecrire(g("dette_fin", P1), f"={dette0}", fmt=S.FMT_M, total=True)
    lbo.ecrire(g("treso_fin", P1), f"={g('fin5', C)}", fmt=S.FMT_M)
    lbo.ecrire(g("levier", P1), f"={g('dette_fin', P1)}/{g('ebitda_ltm', C)}", fmt=S.FMT_X)

    duree = f"COUNT({g('fcf', L1, True)}:{g('fcf', LN, True)})"
    lbo.ecrire(g("ebitda_sortie", C), f"={g('ebitda', LN)}", fmt=S.FMT_M)
    lbo.ecrire(g("multiple_sortie", C), f"={g('multiple_entree', C)}+{hy.x('ecart_multiple_sortie', C)}", fmt=S.FMT_X)
    lbo.ecrire(g("ve_sortie", C), f"={g('ebitda_sortie', C)}*{g('multiple_sortie', C)}", fmt=S.FMT_M)
    lbo.ecrire(g("passif_sortie", C), f"={g('dette_fin', LN)}-{g('treso_fin', LN)}+{g('autres', C)}", fmt=S.FMT_M)
    lbo.ecrire(g("equity_sortie", C), f"={g('ve_sortie', C)}-{g('passif_sortie', C)}", fmt=S.FMT_M, total=True)
    lbo.ecrire(g("moic", C), f"={g('equity_sortie', C)}/{equity0}", fmt='0.00"x"', gras=True)
    lbo.ecrire(g("tri", C), f"={g('moic', C)}^(1/{duree})-1", fmt=S.FMT_PCT, gras=True)

    for col, cle_tri in ((C, "tri_cible"), (D, "tri_cible_haut")):
        lbo.ecrire(g("pm_tri", col), f"={hy.x(cle_tri, C)}", "lien", S.FMT_PCT)
        lbo.ecrire(g("pm_r", col), f"=(1+{g('pm_tri', col)})^{duree}", fmt='0.00"x"')
        lbo.ecrire(g("pm_a", col), f"={g('ebitda_sortie', C, True)}/{g('ebitda_ltm', C, True)}", fmt=S.FMT_NB)
        lbo.ecrire(g("pm_k", col),
                   f"={g('ebitda_sortie', C, True)}*{hy.x('ecart_multiple_sortie', C)}-{g('passif_sortie', C, True)}",
                   fmt=S.FMT_M)
        lbo.ecrire(g("pm_c0", col),
                   f"={g('fin2', C, True)}+{hy.x('frais_transaction', C)}*{g('dette_nette', C, True)}"
                   f"+{g('fin4', C, True)}+{g('fin5', C, True)}-{dette0}-{g('fin2', G, True)}", fmt=S.FMT_M)
        lbo.ecrire(g("pm_cp", col),
                   f"=({g('pm_r', col)}*{g('pm_c0', col)}-{g('pm_a', col)}*{g('dette_nette', C, True)}-{g('pm_k', col)})"
                   f"/({g('pm_a', col)}-{g('pm_r', col)}*(1+{hy.x('frais_transaction', C)}))", fmt=S.FMT_M)
        lbo.ecrire(g("pm_prix", col), f"={g('pm_cp', col)}/{g('actions', C, True)}", fmt=S.FMT_PRIX, gras=True)
        lbo.ecrire(g("pm_prime", col), f"={g('pm_prix', col)}/{g('cours', C, True)}-1", fmt=S.FMT_PCT)
    lbo.ecrire(f"A{lbo.r('pm_prime') + 2}",
               "La dette ne dépend que de l'EBITDA : la mise du fonds et la valeur de revente varient donc en ligne droite "
               "avec le prix payé, ce qui donne le prix maximum par une formule exacte, sans tâtonnement.", "note")
    S.largeurs(lbo.ws, 50, 4, 2 + n, {**{c: 15 for c in PC}, "E": 15, "F": 15, "G": 15})

    # ----------------------------------------------------------- Sensibilités
    se.titre("Tables de sensibilité",
             "Chaque case refait le calcul avec deux hypothèses déplacées. La case centrale reprend le cas de base.")
    VAL = ["C", "D", "E", "F", "G"]
    fcf_p, poids_p, temps_p = dcf.xp("fcf", P1, PN), dcf.xp("poids", P1, PN), dcf.xp("temps", P1, PN)
    passage, actions = hy.x("passage", C), hy.x("actions_diluees", C)

    def table(cle: str, depart: int, titre: str, coin: str, n_col: int = 5) -> int:
        se.lig[cle] = depart + 1
        S.bandeau(se.ws, depart, titre, 7)
        se.ecrire(f"B{depart + 1}", coin, "note")
        return depart + 1

    def entetes(tete: int, base_col: str, pas_col: str | None, base_lig: str, pas_lig: str,
                fmt_col: str, fmt_lig: str) -> None:
        for k, col in zip(CRANS, VAL):
            if pas_col is not None:
                se.ecrire(f"{col}{tete}", f"={base_col}{k:+d}*{pas_col}", fmt=fmt_col, gras=True)
            se.ecrire(f"B{tete + 3 + k}", f"={base_lig}{k:+d}*{pas_lig}", fmt=fmt_lig, gras=True, centre=True)

    t = table("t1", 4, "Valeur par action ($), DCF à croissance perpétuelle", "WACC \\ croissance perpétuelle")
    entetes(t, hy.x("croissance_perpetuelle", C), hy.x("pas_g", C), hy.x("wacc", C), hy.x("pas_wacc", C), FMT_PCT2, FMT_PCT2)
    for i in range(1, 6):
        for col in VAL:
            se.ecrire(f"{col}{t + i}",
                      f"=(SUMPRODUCT({fcf_p}*{poids_p}/(1+$B{t + i})^{temps_p})"
                      f"+{dcf.x('fcf', PN)}*(1+{col}${t})/($B{t + i}-{col}${t})/(1+$B{t + i})^{dcf.x('temps', PN)}"
                      f"-{passage})/{actions}", fmt=S.FMT_PRIX)

    t = table("t2", 12, "Valeur par action ($), DCF à multiple de sortie", "WACC \\ multiple de sortie")
    entetes(t, hy.x("multiple_sortie_dcf", C), hy.x("pas_multiple", C), hy.x("wacc", C), hy.x("pas_wacc", C), S.FMT_X, FMT_PCT2)
    for i in range(1, 6):
        for col in VAL:
            se.ecrire(f"{col}{t + i}",
                      f"=(SUMPRODUCT({fcf_p}*{poids_p}/(1+$B{t + i})^{temps_p})"
                      f"+{pr.x('ebitda', PN)}*{col}${t}/(1+$B{t + i})^{dcf.x('temps_fin', C)}"
                      f"-{passage})/{actions}", fmt=S.FMT_PRIX)

    t = table("t3", 20, "TRI du fonds selon le multiple et l'année de sortie", "Multiple de sortie \\ année de sortie")
    entetes(t, "", None, lbo.x("multiple_sortie", C), hy.x("pas_multiple", C), S.FMT_ENTIER, S.FMT_X)
    plan = lambda cle: lbo.xp(cle, L1, LN)     # noqa: E731
    for annee, col in zip(ANNEES_SORTIE, VAL):
        se.ecrire(f"{col}{t}", annee, "saisie", S.FMT_ENTIER, gras=True)
        for i in range(1, 6):
            se.ecrire(f"{col}{t + i}",
                      f'=IFERROR(((INDEX({plan("ebitda")},{col}${t})*$B{t + i}-INDEX({plan("dette_fin")},{col}${t})'
                      f'+INDEX({plan("treso_fin")},{col}${t})-{lbo.x("autres", C)})/{lbo.x("fin3", G)})'
                      f'^(1/{col}${t})-1,"n.s.")', fmt=S.FMT_PCT)

    t = table("t4", 28, "TRI du fonds selon la prime payée et le multiple de sortie", "Prime d'acquisition \\ multiple de sortie")
    entetes(t, lbo.x("multiple_sortie", C), hy.x("pas_multiple", C), hy.x("prime_acquisition", C), hy.x("pas_prime", C),
            S.FMT_X, S.FMT_PCT)
    duree_x = f"COUNT({lbo.xp('fcf', L1, LN)})"
    for i in range(1, 6):
        for col in VAL:
            se.ecrire(f"{col}{t + i}",
                      f'=IFERROR((({lbo.x("ebitda_sortie", C)}*{col}${t}-{lbo.x("passif_sortie", C)})'
                      f'/((1+{hy.x("frais_transaction", C)})*{hy.x("cours", C)}*(1+$B{t + i})*{actions}+{lbo.x("pm_c0", C)}))'
                      f'^(1/{duree_x})-1,"n.s.")', fmt=S.FMT_PCT)
    S.largeurs(se.ws, 4, 14, 7, {"B": 36})

    # --------------------------------------------------------------- Synthèse
    sy.titre(f"{nom_court} ({soc.ticker}) : valorisation M&A / LBO",
             f"Modèle généré par Talanton {__version__} le {genere_le.strftime('%d/%m/%Y')}. Millions de dollars, sauf valeurs par action. "
             "Document pédagogique : ni conseil en investissement, ni recommandation.")
    sy.ecrire("A3", f"Comptes : SEC EDGAR, {depots}. {h.notes.get('cours', '')}", "note")
    r = sy.disposer([
        ("#", "Marché"),
        ("cours", "Cours de l'action ($)"),
        ("capi", "Capitalisation boursière"),
        ("dette_nette", "Dette financière nette"),
        ("ve", "Valeur d'entreprise"),
        ("ve_ebitda", "VE / EBITDA ajusté des 12 derniers mois"),
        ("",),
        ("#", "Valeur par action selon chaque méthode ($)"),
        ("tete_ff", "Méthode"),
    ], depart=5, largeur=6, unite_col=None)
    for cle, ref, fmt in (("cours", hy.x("cours", C), S.FMT_PRIX), ("capi", hy.x("capitalisation", C), S.FMT_M),
                          ("dette_nette", hy.x("dette_nette", C), S.FMT_M), ("ve", hy.x("valeur_entreprise", C), S.FMT_M)):
        sy.ecrire(sy.a(cle, "B"), f"={ref}", "lien", fmt)
    sy.ecrire(sy.a("ve_ebitda", "B"), f"={sy.a('ve', 'B')}/{hi.x('ebitda_ajuste', HL)}", fmt=S.FMT_X)
    S.entete(sy.ws, sy.r("tete_ff"), {"A": "Méthode", "B": "Bas", "C": "Haut", "D": "Étendue", "E": "Milieu",
                                      "F": "Écart au cours"})
    r1, r2, r3, r4 = se.r("t1"), se.r("t2"), se.r("t3"), se.r("t4")
    coeur = lambda t: f"'{SE}'!$D${t + 2}:$F${t + 4}"     # noqa: E731
    lignes_ff = [
        ("Comparables : VE / EBITDA (1er au 3e quartile)", f"={co.x('imp_ve_ebitda', 'J')}", f"={co.x('imp_ve_ebitda', 'L')}"),
        ("Comparables : VE / EBIT (1er au 3e quartile)", f"={co.x('imp_ve_ebit', 'J')}", f"={co.x('imp_ve_ebit', 'L')}"),
        ("Comparables : PER (1er au 3e quartile)", f"={co.x('imp_per', 'J')}", f"={co.x('imp_per', 'L')}"),
        ("DCF : croissance perpétuelle (WACC et croissance à plus ou moins un pas)", f"=MIN({coeur(r1)})", f"=MAX({coeur(r1)})"),
        ("DCF : multiple de sortie (WACC et multiple à plus ou moins un pas)", f"=MIN({coeur(r2)})", f"=MAX({coeur(r2)})"),
        ("LBO : prix maximum d'un fonds (TRI visé haut, puis TRI visé)", f"={lbo.x('pm_prix', D)}", f"={lbo.x('pm_prix', C)}"),
        ("Cours actuel", f"={hy.x('cours', C)}", f"={hy.x('cours', C)}"),
    ]
    debut_ff = r
    for libelle, bas, haut in lignes_ff:
        sy.ecrire(f"A{r}", libelle)
        sy.ecrire(f"B{r}", bas, "lien", S.FMT_PRIX)
        sy.ecrire(f"C{r}", haut, "lien", S.FMT_PRIX)
        sy.ecrire(f"D{r}", f"=IFERROR(MAX(C{r}-B{r},{hy.x('cours', C)}*0.01),0)", fmt=S.FMT_PRIX)
        sy.ecrire(f"E{r}", f'=IFERROR((B{r}+C{r})/2,"n.s.")', fmt=S.FMT_PRIX)
        sy.ecrire(f"F{r}", f'=IFERROR(E{r}/{hy.x("cours", C)}-1,"n.s.")', fmt=S.FMT_PCT)
        r += 1
    fin_ff = r - 1
    sy.ecrire(f"A{r}", "Étendue : largeur de la barre du graphique (1 % du cours au minimum, pour rester visible).", "note")
    r = sy.disposer([
        ("",),
        ("#", "LBO : ce que gagne un fonds au prix d'offre retenu"),
        ("lbo_prime", "Prime d'acquisition"),
        ("lbo_prix", "Prix d'offre par action ($)"),
        ("lbo_multiple", "Multiple d'entrée (VE / EBITDA LTM)"),
        ("lbo_levier", "Dette d'acquisition / EBITDA LTM"),
        ("lbo_equity", "Part des fonds propres dans le financement"),
        ("lbo_moic", "Multiple de la mise (MOIC)"),
        ("lbo_tri", "TRI du fonds"),
        ("",),
        ("#", "Fiabilité du modèle"),
        ("statut", "Contrôles de cohérence"),
        ("attention", "Points d'attention à examiner"),
        ("python", "Rapprochement avec le moteur Python"),
    ], depart=r + 1, largeur=6, unite_col=None)
    for cle, ref, fmt in (("lbo_prime", lbo.x("prime", C), S.FMT_PCT), ("lbo_prix", lbo.x("prix_offre", C), S.FMT_PRIX),
                          ("lbo_multiple", lbo.x("multiple_entree", C), S.FMT_X), ("lbo_levier", hy.x("levier", C), S.FMT_X),
                          ("lbo_equity", lbo.x("fin4", G), S.FMT_PCT), ("lbo_moic", lbo.x("moic", C), '0.00"x"'),
                          ("lbo_tri", lbo.x("tri", C), S.FMT_PCT)):
        sy.ecrire(sy.a(cle, "B"), f"={ref}", "lien", fmt)

    graphique = BarChart()
    graphique.type, graphique.grouping, graphique.overlap = "bar", "stacked", 100
    graphique.title = "Valeur par action selon chaque méthode ($)"
    graphique.add_data(Reference(sy.ws, min_col=2, min_row=debut_ff, max_row=fin_ff), titles_from_data=False)
    graphique.add_data(Reference(sy.ws, min_col=4, min_row=debut_ff, max_row=fin_ff), titles_from_data=False)
    graphique.set_categories(Reference(sy.ws, min_col=1, min_row=debut_ff, max_row=fin_ff))
    graphique.series[0].graphicalProperties.noFill = True
    graphique.series[0].graphicalProperties.line.noFill = True
    graphique.series[1].graphicalProperties.solidFill = "2E75B6"
    graphique.legend = None
    graphique.y_axis.number_format = "0"
    graphique.y_axis.majorGridlines = None
    graphique.x_axis.scaling.orientation = "maxMin"     # première méthode en haut
    graphique.x_axis.delete = False
    graphique.y_axis.delete = False
    graphique.height, graphique.width = 9.5, 24
    sy.ws.add_chart(graphique, "H5")
    S.largeurs(sy.ws, 66, 14, 6, {"F": 17})

    # -------------------------------------------------------------- Contrôles
    ct.titre("Contrôles", "ERREUR : le modèle est incohérent, ne pas l'utiliser. ATTENTION : point de jugement à examiner. "
                          "OK : rien à signaler.")
    S.entete(ct.ws, 3, {"A": "Contrôle", "B": "Valeur", "C": "Seuil", "D": "Statut", "E": "Lecture"}, gauche=("E",))
    r = 4

    def controle(libelle: str, formule: str, seuil, test: str, niveau: str, lecture: str, fmt: str) -> None:
        nonlocal r
        ct.ecrire(f"A{r}", libelle)
        ct.ecrire(f"B{r}", formule, fmt=fmt)
        ct.ecrire(f"C{r}", seuil, "saisie", fmt)
        ct.ecrire(f"D{r}", f'=IF(B{r}{test}C{r},"OK","{niveau}")', gras=True, centre=True)
        ct.ecrire(f"E{r}", lecture, "note")
        r += 1

    S.bandeau(ct.ws, r, "Cohérence du modèle", 5)
    r += 1
    debut_statuts = r
    controle("Bilans historiques équilibrés (somme des écarts)",
             f"=SUMPRODUCT(ABS({hi.xp('ecart', HC[0], HD)}))", 0.5, "<", "ERREUR",
             "Actif = passif sur chaque exercice publié.", S.FMT_NB)
    controle("Bilans projetés équilibrés (somme des écarts)",
             f"=SUMPRODUCT(ABS({pr.xp('ecart', PB, PN)}))", 0.5, "<", "ERREUR",
             "Le bilan projeté doit rester équilibré quelles que soient les hypothèses.", S.FMT_NB)
    controle("LBO : ressources = emplois (écart)", f"=ABS({lbo.x('fin_ecart', C)})", 0.5, "<", "ERREUR",
             "Le financement doit couvrir exactement le prix et les frais.", S.FMT_NB)
    controle("WACC supérieur à la croissance perpétuelle (écart)",
             f"={hy.x('wacc', C)}-{hy.x('croissance_perpetuelle', C)}", 0.005, ">", "ERREUR",
             "Sinon la valeur terminale n'a pas de sens.", FMT_PCT2)
    controle("LBO : fonds propres apportés positifs", f"={lbo.x('fin3', G)}", 0, ">", "ERREUR",
             "Une mise négative signifie que la dette dépasse le prix payé.", S.FMT_M)
    S.bandeau(ct.ws, r, "Points de jugement", 5)
    r += 1
    controle("Poids de la valeur terminale, DCF à croissance perpétuelle", f"={dcf.x('part_vt', C)}", 0.8, "<", "ATTENTION",
             "Au-delà de 80 %, la valeur repose presque entièrement sur des hypothèses de long terme.", S.FMT_PCT)
    controle("Poids de la valeur terminale, DCF à multiple de sortie", f"={dcf.x('part_vt', D)}", 0.8, "<", "ATTENTION",
             "Même lecture.", S.FMT_PCT)
    controle("Nombre de comparables avec un VE / EBITDA significatif",
             f"=COUNT({co.nom!r}!${K['ve_ebitda']}${premier}:${K['ve_ebitda']}${max(dernier, premier)})", 4, ">=", "ATTENTION",
             "En dessous de quatre, la médiane est fragile.", S.FMT_ENTIER)
    controle("Trésorerie projetée la plus basse (société seule)", f"=MIN({pr.xp('tresorerie', P1, PN)})", 0, ">=", "ATTENTION",
             "Une trésorerie négative suppose un financement non modélisé.", S.FMT_M)
    controle("LBO : trésorerie la plus basse après l'opération", f"=MIN({lbo.xp('treso_fin', P1, LN)})", 0, ">=", "ATTENTION",
             "Une trésorerie négative signifie que la dette n'est pas supportable.", S.FMT_M)
    controle("LBO : dette / EBITDA à la clôture", f"={lbo.x('levier', P1)}", 6.5, "<=", "ATTENTION",
             "Au-delà de 6 à 7 fois l'EBITDA, le financement devient difficile à lever.", S.FMT_X)
    controle("LBO : couverture des intérêts la plus faible (EBITDA / intérêts)", f"=MIN({lbo.xp('couverture', L1, LN)})", 2, ">=",
             "ATTENTION", "En dessous de 2, la société peine à payer ses intérêts.", S.FMT_X)
    S.bandeau(ct.ws, r, "Alertes sur les données (relevées à la génération)", 5)
    r += 1
    alertes = list(soc.alertes)
    for p in pairs:
        alertes += p.societe.alertes
    beta_note = h.notes.get("beta_brut", "")
    if "R² = 0.0" in beta_note or "R² = 0.1" in beta_note or "indisponible" in beta_note:
        alertes.append("Bêta peu fiable : " + beta_note)
    for a in alertes:
        sujet = a.split(" : ")[0] if " : " in a[:40] else "Donnée"
        ct.ecrire(f"A{r}", f"À vérifier : {sujet}")
        ct.ecrire(f"D{r}", "ATTENTION", gras=True, centre=True)
        ct.ecrire(f"E{r}", a, "note")
        r += 1
    if not alertes:
        ct.ecrire(f"A{r}", "Aucune alerte.", "note")
        r += 1
    fin_statuts = r - 1
    plage_statuts = f"$D${debut_statuts}:$D${fin_statuts}"
    r += 1
    ct.lig["statut"] = r
    ct.ecrire(f"A{r}", "Statut d'ensemble", gras=True)
    ct.ecrire(f"B{r}", f'=IF(COUNTIF({plage_statuts},"ERREUR")>0,"ERREUR",'
                       f'IF(COUNTIF({plage_statuts},"ATTENTION")>0,"Cohérent, avec points d\'attention","Cohérent"))', gras=True)
    r += 1
    ct.lig["attention"] = r
    ct.ecrire(f"A{r}", "Nombre de points d'attention")
    ct.ecrire(f"B{r}", f'=COUNTIF({plage_statuts},"ATTENTION")', fmt=S.FMT_ENTIER)
    r += 2

    S.bandeau(ct.ws, r, "Rapprochement Python / Excel (le moteur Python a calculé ces chiffres sans Excel)", 5)
    r += 1
    S.entete(ct.ws, r, {"A": "Chiffre clé", "B": "Formule Excel", "C": "Moteur Python", "D": "Écart", "E": "Statut"},
             gauche=("E",))
    r += 1
    emplacements = {
        "proj.ca_fin": ("Chiffre d'affaires, dernière année projetée", pr, "ca", PN, S.FMT_M),
        "proj.ebitda_fin": ("EBITDA, dernière année projetée", pr, "ebitda", PN, S.FMT_M),
        "proj.rn_fin": ("Résultat net, dernière année projetée", pr, "rn", PN, S.FMT_M),
        "proj.tresorerie_fin": ("Trésorerie, dernière année projetée", pr, "tresorerie", PN, S.FMT_M),
        "proj.total_actif_fin": ("Total de l'actif, dernière année projetée", pr, "total_actif", PN, S.FMT_M),
        "dcf.wacc": ("WACC", hy, "wacc", C, "0.0000%"),
        "dcf.fcf_fin": ("Flux disponible, dernière année", dcf, "fcf", PN, S.FMT_M),
        "dcf.ve_gordon": ("Valeur d'entreprise, DCF à croissance perpétuelle", dcf, "ve", C, S.FMT_M),
        "dcf.ve_multiple": ("Valeur d'entreprise, DCF à multiple de sortie", dcf, "ve", D, S.FMT_M),
        "dcf.action_gordon": ("Valeur par action, DCF à croissance perpétuelle", dcf, "action", C, S.FMT_PRIX),
        "dcf.action_multiple": ("Valeur par action, DCF à multiple de sortie", dcf, "action", D, S.FMT_PRIX),
        "comps.mediane_ve_ebitda": ("Médiane VE / EBITDA des comparables", co, "mediane", K["ve_ebitda"], "0.000"),
        "comps.action_mediane_ve_ebitda": ("Valeur par action à la médiane VE / EBITDA", co, "imp_ve_ebitda", "K", S.FMT_PRIX),
        "lbo.ve_entree": ("LBO : valeur d'entreprise à l'entrée", lbo, "ve_entree", C, S.FMT_M),
        "lbo.equity_sponsor": ("LBO : fonds propres apportés", lbo, "fin3", G, S.FMT_M),
        "lbo.dette_fin": ("LBO : dette en fin de plan", lbo, "dette_fin", LN, S.FMT_M),
        "lbo.equity_sortie": ("LBO : capitaux propres à la sortie", lbo, "equity_sortie", C, S.FMT_M),
        "lbo.moic": ("LBO : multiple de la mise", lbo, "moic", C, "0.0000"),
        "lbo.tri": ("LBO : TRI", lbo, "tri", C, "0.0000%"),
        "lbo.prix_max_cible": ("LBO : prix maximum par action, TRI visé", lbo, "pm_prix", C, S.FMT_PRIX),
        "lbo.prix_max_haut": ("LBO : prix maximum par action, TRI visé haut", lbo, "pm_prix", D, S.FMT_PRIX),
    }
    points = res.points_de_controle()
    debut_py = r
    for cle, valeur in points.items():
        libelle, feuille, poste, col, fmt = emplacements[cle]
        registre[cle] = (feuille.nom, f"{col}{feuille.r(poste)}")
        ct.ecrire(f"A{r}", libelle)
        ct.ecrire(f"B{r}", f"={feuille.x(poste, col)}", "lien", fmt)
        ct.ecrire(f"C{r}", valeur, "saisie", fmt)
        ct.ecrire(f"D{r}", f"=B{r}-C{r}", fmt="0.000000")
        ct.ecrire(f"E{r}", f'=IF(ABS(D{r})<=0.000001*MAX(1,ABS(C{r})),"Identique","Modifié")', centre=True)
        r += 1
    ct.lig["python"] = r + 1
    ct.ecrire(f"A{r + 1}", "Rapprochement d'ensemble", gras=True)
    ct.ecrire(f"B{r + 1}", f'=IF(COUNTIF($E${debut_py}:$E${r - 1},"Modifié")=0,"Excel = Python sur {len(points)} chiffres clés",'
                           f'"Hypothèses modifiées depuis la génération")', gras=True)
    ct.ecrire(f"A{r + 3}", "« Modifié » est normal dès qu'une cellule bleue a été changée : la colonne Python garde les valeurs "
                           "du jour de la génération. Relancer Talanton pour refaire le rapprochement.", "note")
    S.largeurs(ct.ws, 62, 16, 4, {"E": 90})
    registre["controles.statut"] = (CT, f"B{ct.r('statut')}")
    registre["controles.python"] = (CT, f"B{ct.r('python')}")

    sy.ecrire(sy.a("statut", "B"), f"={ct.x('statut', 'B')}", "lien")
    sy.ecrire(sy.a("attention", "B"), f"={ct.x('attention', 'B')}", "lien", S.FMT_ENTIER)
    sy.ecrire(sy.a("python", "B"), f"={ct.x('python', 'B')}", "lien")

    for feuille in f.values():
        feuille.ws.page_setup.orientation = "landscape"
        feuille.ws.page_setup.fitToWidth = 1
        feuille.ws.page_setup.fitToHeight = 0
        feuille.ws.sheet_properties.pageSetUpPr.fitToPage = True
    wb.calculation.fullCalcOnLoad = True
    wb.properties.title = f"{nom_court} : modèle de valorisation Talanton"
    wb.properties.creator = f"Talanton {__version__}"
    return wb, registre
