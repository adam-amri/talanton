"""Mise des comptes publiés au format banque.

À partir des faits bruts de la SEC, construit pour une société :
  - l'historique annuel (compte de résultat, flux, bilan simplifié) ;
  - les douze derniers mois (LTM) ;
  - le dernier bilan publié (trésorerie, dette, minoritaires) ;
  - le nombre d'actions.
Tous les montants sont en millions de dollars.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from . import balises as B
from .ajustements import Ajustements
from .faits import Faits

MILLION = 1e6
ECART_BALISES_CA = 0.01      # au-delà de 1 % d'écart entre deux balises de CA : alerte

POSTES_FLUX = ("ca", "marge_brute", "ebit", "da", "depreciations", "ajust", "ebitda_publie",
               "ebitda_ajuste", "ebit_ajuste", "interets", "produits_fin", "rai", "impot", "rn",
               "sbc", "cfo", "capex", "rachats", "dividendes")
POSTES_BILAN = ("tresorerie", "actif_circ_expl", "immo_nettes", "goodwill", "autres_actifs",
                "total_actif", "passif_expl", "dette", "autres_passifs", "capitaux_propres",
                "total_passif", "bfr", "minoritaires")
POSTES_LTM = ("ca", "marge_brute", "ebit", "da", "depreciations", "ajust", "ebitda_publie",
              "ebitda_ajuste", "ebit_ajuste", "rn", "ajust_rn", "rn_ajuste")


class ErreurRetraitement(RuntimeError):
    pass


@dataclass
class Societe:
    ticker: str
    nom: str
    cik: int
    exercices: list[date]                       # fins d'exercice, ordre chronologique
    hist: dict[str, list[float | None]]         # un chiffre par exercice
    date_ltm: date                              # fin de la période LTM
    ltm: dict[str, float | None]
    date_bilan: date                            # date du dernier bilan publié
    bilan: dict[str, float]                     # tresorerie, dette, minoritaires à cette date
    distributions_cumul: float                  # rachats + dividendes depuis la dernière clôture
    actions: float                              # en millions
    source_actions: str
    sources: dict[str, str] = field(default_factory=dict)    # poste -> balise(s) utilisée(s)
    ajustements: Ajustements = field(default_factory=Ajustements)
    depots: dict[str, str] = field(default_factory=dict)     # dernier 10-K / 10-Q utilisés
    alertes: list[str] = field(default_factory=list)

    @property
    def dernier(self) -> dict[str, float | None]:
        """Chiffres du dernier exercice clos."""
        return {k: v[-1] for k, v in self.hist.items()}


def _m(valeur: float | None) -> float | None:
    return None if valeur is None else valeur / MILLION


class _Constructeur:
    def __init__(self, ticker: str, brut: dict, n_exercices: int, ajustements: Ajustements | None,
                 bilan_detaille: bool = True):
        self.ticker = ticker
        self.bilan_detaille = bilan_detaille
        self.f = Faits(brut)
        self.aj = ajustements or Ajustements()
        self.sources: dict[str, str] = {}
        self.alertes: list[str] = []
        tous = self.f.exercices(B.REPERES)
        if not tous:
            raise ErreurRetraitement(f"{ticker} : aucun exercice annuel (10-K) trouvé.")
        self.exercices = tous[-n_exercices:]
        self.debut_dernier, self.fin_dernier = self.exercices[-1]
        self.trimestre = self.f.dernier_trimestre(B.REPERES, self.fin_dernier)

    # -- flux annuels -------------------------------------------------------
    def _premier_annuel(self, candidates: tuple[str, ...], fin: date):
        for b in candidates:
            fait = self.f.annuel(b, fin)
            if fait is not None:
                return fait
        return None

    def flux_annuel(self, poste: str, fin: date) -> float | None:
        fait = self._premier_annuel(B.FLUX[poste], fin)
        if fait is not None:
            if fin == self.fin_dernier:
                self.sources[poste] = fait.balise
            return _m(fait.valeur)
        return None

    def da_annuel(self, fin: date) -> float | None:
        v = self.flux_annuel("da", fin)
        if v is not None:
            return v
        parts = [self.f.annuel(b, fin) for b in B.DA_COMPOSANTES]
        if all(p is not None for p in parts):
            self.sources["da"] = " + ".join(B.DA_COMPOSANTES)
            return _m(sum(p.valeur for p in parts))
        return None

    def capex_annuel(self, fin: date) -> float | None:
        force = self.aj.capex.get(fin.isoformat())
        if force is not None:
            self.sources["capex"] = "ajustement analyste"
            return force
        v = self.flux_annuel("capex", fin)
        if v is not None:
            return v
        parts = [self.f.annuel(b, fin) for b in B.CAPEX_PARTIELLES]
        parts = [p for p in parts if p is not None]
        if parts:
            if fin == self.fin_dernier:
                self.sources["capex"] = " + ".join(p.balise for p in parts) + " (partiel)"
                self.alertes.append(
                    "Capex : aucune balise de total, seule une ligne partielle est disponible "
                    f"({', '.join(p.balise for p in parts)}). Renseigner le total dans le fichier "
                    "d'ajustements.")
            return _m(sum(p.valeur for p in parts))
        return None

    def depreciations_annuel(self, fin: date) -> float:
        agregees = [self.f.annuel(b, fin) for b in B.DEPRECIATIONS_AGREGEES]
        detail = [self.f.annuel(b, fin) for b in B.DEPRECIATIONS_DETAIL]
        a = max((x.valeur for x in agregees if x is not None), default=0.0)
        d = sum(x.valeur for x in detail if x is not None)
        return _m(max(a, d))

    # -- LTM ----------------------------------------------------------------
    def _ltm_balise(self, balise: str) -> float | None:
        a = self.f.annuel(balise, self.fin_dernier)
        if a is None:
            return None
        if self.trimestre is None:
            return a.valeur
        c = self.f.cumul(balise, self.fin_dernier + timedelta(days=1), self.trimestre)
        p = self.f.cumul_precedent(balise, self.debut_dernier, self.trimestre)
        if c is None or p is None:
            return None
        return a.valeur + c.valeur - p.valeur

    def flux_ltm(self, poste: str) -> float | None:
        for b in B.FLUX[poste]:
            v = self._ltm_balise(b)
            if v is not None:
                return _m(v)
        return None

    def da_ltm(self) -> float | None:
        v = self.flux_ltm("da")
        if v is not None:
            return v
        parts = [self._ltm_balise(b) for b in B.DA_COMPOSANTES]
        return _m(sum(parts)) if all(p is not None for p in parts) else None

    def _ltm_depreciation(self, balise: str) -> float:
        a = self.f.annuel(balise, self.fin_dernier)
        if self.trimestre is None:
            return a.valeur if a else 0.0
        c = self.f.cumul(balise, self.fin_dernier + timedelta(days=1), self.trimestre)
        p = self.f.cumul_precedent(balise, self.debut_dernier, self.trimestre)
        if a is not None and a.valeur and (c is None or p is None):
            self.alertes.append(
                f"Dépréciation d'actifs ({balise}) : cumul trimestriel manquant, "
                "le montant LTM réintégré est à vérifier.")
        return (a.valeur if a else 0.0) + (c.valeur if c else 0.0) - (p.valeur if p else 0.0)

    def depreciations_ltm(self) -> float:
        a = max((self._ltm_depreciation(b) for b in B.DEPRECIATIONS_AGREGEES), default=0.0)
        d = sum(self._ltm_depreciation(b) for b in B.DEPRECIATIONS_DETAIL)
        return _m(max(a, d, 0.0))

    # -- bilan --------------------------------------------------------------
    def _premier_instant(self, candidates: tuple[str, ...], d: date):
        for b in candidates:
            fait = self.f.instant(b, d)
            if fait is not None:
                return fait
        return None

    def _inst(self, poste: str, d: date) -> float | None:
        fait = self._premier_instant(B.BILAN[poste], d)
        if fait is not None and d == self.fin_dernier:
            self.sources[poste] = fait.balise
        return None if fait is None else fait.valeur

    def tresorerie(self, d: date) -> float | None:
        caisse = self._inst("caisse", d)
        if caisse is None:
            return None
        return _m(caisse + (self._inst("placements", d) or 0.0))

    def dette(self, d: date) -> tuple[float, float]:
        """Renvoie (dette financière totale, part classée en passif courant)."""
        lt = self._inst("dette_lt", d)
        ct_fait = self._premier_instant(B.BILAN["dette_ct"], d)
        ct = ct_fait.valeur if ct_fait else None
        complements = 0.0
        if ct_fait is None or ct_fait.balise != "DebtCurrent":
            for b in B.DETTE_CT_COMPLEMENTS:
                fait = self.f.instant(b, d)
                if fait is not None:
                    complements += fait.valeur
        if lt is None and ct is None and not complements:
            secours = self._inst("dette_totale_secours", d)
            return _m(secours or 0.0), 0.0
        courant = (ct or 0.0) + complements
        return _m((lt or 0.0) + courant), _m(courant)

    def minoritaires(self, d: date) -> float:
        total = 0.0
        for b in B.MINORITAIRES:
            fait = self.f.instant(b, d)
            if fait is not None:
                total += fait.valeur
        return _m(total)

    def bilan_complet(self, d: date) -> dict[str, float]:
        requis = {p: self._inst(p, d) for p in ("actif_courant", "total_actif", "passif_courant")}
        manquants = [p for p, v in requis.items() if v is None]
        treso = self.tresorerie(d)
        if manquants or treso is None:
            raise ErreurRetraitement(
                f"{self.ticker} : bilan incomplet au {d} ({', '.join(manquants) or 'trésorerie'}). "
                "Les banques, assureurs et foncières ne sont pas couverts par cette version.")
        dette, dette_courante = self.dette(d)
        mino = self.minoritaires(d)
        cp_total = self._inst("cp_total", d)
        if cp_total is None:
            cp_groupe = self._inst("cp_groupe", d)
            if cp_groupe is None:
                raise ErreurRetraitement(f"{self.ticker} : capitaux propres introuvables au {d}.")
            cp_total = cp_groupe + mino * MILLION
        total_actif = _m(requis["total_actif"])
        total_passif = _m(self._inst("total_passif", d)) or total_actif
        actif_circ = _m(requis["actif_courant"]) - treso
        immo = _m((self._inst("immo_corporelles", d) or 0.0) + (self._inst("immo_incorporelles", d) or 0.0))
        goodwill = _m(self._inst("goodwill", d) or 0.0)
        passif_expl = _m(requis["passif_courant"]) - dette_courante
        cp = _m(cp_total)
        return {
            "tresorerie": treso, "actif_circ_expl": actif_circ, "immo_nettes": immo,
            "goodwill": goodwill,
            "autres_actifs": total_actif - treso - actif_circ - immo - goodwill,
            "total_actif": total_actif, "passif_expl": passif_expl, "dette": dette,
            "autres_passifs": total_passif - passif_expl - dette - cp,
            "capitaux_propres": cp, "total_passif": total_passif,
            "bfr": actif_circ - passif_expl, "minoritaires": mino,
        }

    # -- actions ------------------------------------------------------------
    def actions(self) -> tuple[float, str]:
        couverture = self.f.liste(B.ACTIONS_COUVERTURE, "dei")
        if couverture:
            dernier = max(couverture, key=lambda f: (f.fin, f.depose))
            return _m(dernier.valeur), (f"actions en circulation au {dernier.fin.isoformat()} "
                                        f"(page de garde du {dernier.formulaire})")
        annuel = self.f.annuel(B.ACTIONS_DILUEES, self.fin_dernier)
        if annuel is None:
            raise ErreurRetraitement(f"{self.ticker} : nombre d'actions introuvable.")
        valeur = annuel.valeur
        if self.trimestre is not None:
            c = self.f.cumul(B.ACTIONS_DILUEES, self.fin_dernier + timedelta(days=1), self.trimestre)
            # garde-fou : certaines sociétés publient ce chiffre en milliers dans leurs 10-Q
            if c is not None and 0.5 <= c.valeur / annuel.valeur <= 2.0:
                valeur = c.valeur
        self.alertes.append(
            f"{self.ticker} : nombre d'actions estimé par la moyenne pondérée diluée "
            "(pas de chiffre de page de garde, souvent plusieurs classes d'actions). À vérifier.")
        return _m(valeur), "moyenne pondérée diluée de la dernière période publiée"

    # -- contrôle des balises de chiffre d'affaires ---------------------------
    def verifier_balises_ca(self) -> None:
        valeurs = [(b, self.f.annuel(b, self.fin_dernier)) for b in B.FLUX["ca"]]
        presentes = [(b, f.valeur) for b, f in valeurs if f is not None]
        if len(presentes) >= 2:
            (b1, v1), (b2, v2) = presentes[0], presentes[1]
            if v1 and abs(v2 - v1) / abs(v1) > ECART_BALISES_CA:
                self.alertes.append(
                    f"{self.ticker} : deux balises de chiffre d'affaires divergent "
                    f"({b1} = {v1 / MILLION:,.1f} ; {b2} = {v2 / MILLION:,.1f}). "
                    f"Talanton retient {b1}.")

    # -- assemblage ---------------------------------------------------------
    def construire(self) -> Societe:
        fins = [fin for _, fin in self.exercices]
        hist: dict[str, list[float | None]] = {p: [] for p in POSTES_FLUX + POSTES_BILAN}
        for fin in fins:
            ligne = {p: self.flux_annuel(p, fin) for p in
                     ("ca", "marge_brute", "ebit", "interets", "produits_fin", "rai", "impot", "rn",
                      "sbc", "cfo", "rachats", "dividendes")}
            ligne["da"] = self.da_annuel(fin)
            ligne["capex"] = self.capex_annuel(fin)
            ligne["depreciations"] = self.depreciations_annuel(fin)
            ligne["ajust"] = self.aj.ebitda.get(fin.isoformat(), 0.0)
            for requis in ("ca", "ebit", "da"):
                if ligne[requis] is None:
                    raise ErreurRetraitement(
                        f"{self.ticker} : poste « {requis} » introuvable pour l'exercice clos le {fin}.")
            ligne["ebitda_publie"] = ligne["ebit"] + ligne["da"]
            ligne["ebitda_ajuste"] = ligne["ebitda_publie"] + ligne["depreciations"] + ligne["ajust"]
            ligne["ebit_ajuste"] = ligne["ebitda_ajuste"] - ligne["da"]
            for p in POSTES_FLUX:
                hist[p].append(ligne[p])
            b = self.bilan_complet(fin) if self.bilan_detaille else {p: None for p in POSTES_BILAN}
            for p in POSTES_BILAN:
                hist[p].append(b[p])
        self.verifier_balises_ca()

        # LTM
        ltm: dict[str, float | None] = {p: self.flux_ltm(p) for p in ("ca", "marge_brute", "ebit", "rn")}
        ltm["da"] = self.da_ltm()
        ltm["depreciations"] = self.depreciations_ltm()
        ltm["ajust"] = self.aj.ebitda.get("LTM", 0.0)
        for requis in ("ca", "ebit", "da"):
            if ltm[requis] is None:
                self.alertes.append(
                    f"{self.ticker} : LTM indisponible pour « {requis} », repli sur le dernier exercice.")
                ltm[requis] = hist[requis][-1]
        if ltm["rn"] is None:
            ltm["rn"] = hist["rn"][-1]
        ltm["ebitda_publie"] = ltm["ebit"] + ltm["da"]
        ltm["ebitda_ajuste"] = ltm["ebitda_publie"] + ltm["depreciations"] + ltm["ajust"]
        ltm["ebit_ajuste"] = ltm["ebitda_ajuste"] - ltm["da"]
        ltm["ajust_rn"] = self.aj.resultat_net.get("LTM", 0.0)
        ltm["rn_ajuste"] = ltm["rn"] + ltm["ajust_rn"]

        # dernier bilan publié
        date_bilan = self.trimestre or self.fin_dernier
        treso = self.tresorerie(date_bilan)
        if treso is None:
            raise ErreurRetraitement(f"{self.ticker} : trésorerie introuvable au {date_bilan}.")
        dette, _ = self.dette(date_bilan)
        bilan = {"tresorerie": treso, "dette": dette, "minoritaires": self.minoritaires(date_bilan)}

        distributions = 0.0
        if self.trimestre is not None:
            for poste in ("rachats", "dividendes"):
                for b in B.FLUX[poste]:
                    c = self.f.cumul(b, self.fin_dernier + timedelta(days=1), self.trimestre)
                    if c is not None:
                        distributions += _m(c.valeur)
                        break

        actions, source_actions = self.actions()
        depots = {}
        for b in B.FLUX["ca"]:
            a = self.f.annuel(b, self.fin_dernier)
            if a is not None:
                depots["annuel"] = f"10-K déposé le {a.depose.isoformat()} (n° {a.depot})"
                if self.trimestre is not None:
                    c = self.f.cumul(b, self.fin_dernier + timedelta(days=1), self.trimestre)
                    if c is not None:
                        depots["trimestriel"] = f"10-Q déposé le {c.depose.isoformat()} (n° {c.depot})"
                break

        return Societe(
            ticker=self.ticker, nom=self.f.nom, cik=self.f.cik, exercices=fins, hist=hist,
            date_ltm=date_bilan, ltm=ltm, date_bilan=date_bilan, bilan=bilan,
            distributions_cumul=distributions, actions=actions, source_actions=source_actions,
            sources=self.sources, ajustements=self.aj, depots=depots, alertes=self.alertes,
        )


def construire_societe(ticker: str, brut: dict, n_exercices: int = 5,
                       ajustements: Ajustements | None = None,
                       bilan_detaille: bool = True) -> Societe:
    """Point d'entrée : faits bruts SEC -> société au format banque.

    `bilan_detaille=False` pour un comparable : seuls le LTM, la dette, la
    trésorerie et le nombre d'actions servent, le bilan complet est inutile.
    """
    return _Constructeur(ticker, brut, n_exercices, ajustements, bilan_detaille).construire()
