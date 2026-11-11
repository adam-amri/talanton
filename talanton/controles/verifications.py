"""Contrôles de cohérence faits par Python, avant même d'écrire le classeur."""

from __future__ import annotations

from ..moteur import Resultat

TOLERANCE = 1e-6


def verifier(res: Resultat) -> list[tuple[str, str]]:
    """Renvoie la liste des anomalies : (niveau, message). Niveau : ERREUR ou ATTENTION."""
    anomalies: list[tuple[str, str]] = []
    soc, h, p, d, lbo = res.cible, res.hyp, res.proj, res.dcf, res.lbo

    for fin, actif, passif in zip(soc.exercices, soc.hist["total_actif"], soc.hist["total_passif"]):
        if abs(actif - passif) > 0.5:
            anomalies.append(("ERREUR", f"Bilan publié déséquilibré au {fin} : {actif - passif:+.1f} M$."))
    for fin, actif, passif in zip(p.fins, p.total_actif, p.total_passif):
        if abs(actif - passif) > TOLERANCE * max(1.0, actif):
            anomalies.append(("ERREUR", f"Bilan projeté déséquilibré au {fin} : {actif - passif:+.4f} M$."))
    ressources = lbo.nouvelle_dette + lbo.treso_cloture + lbo.equity_sponsor
    if abs(ressources - lbo.total_emplois) > TOLERANCE * lbo.total_emplois:
        anomalies.append(("ERREUR", "LBO : les ressources ne couvrent pas exactement les emplois."))
    if h.wacc - h.croissance_perpetuelle <= 0.005:
        anomalies.append(("ERREUR", "Le WACC doit dépasser la croissance perpétuelle d'au moins 0,5 point."))
    if lbo.equity_sponsor <= 0:
        anomalies.append(("ERREUR", "LBO : la dette dépasse le prix payé, les fonds propres sont négatifs."))

    for nom, part in (("croissance perpétuelle", d.part_vt_gordon), ("multiple de sortie", d.part_vt_multiple)):
        if part >= 0.8:
            anomalies.append(("ATTENTION", f"DCF à {nom} : la valeur terminale pèse {part:.0%} de la valeur."))
    n_pairs = len(res.comps.valeurs("ve_ebitda"))
    if n_pairs < 4:
        anomalies.append(("ATTENTION", f"Seulement {n_pairs} comparable(s) avec un VE / EBITDA significatif."))
    if min(p.tresorerie) < 0:
        anomalies.append(("ATTENTION", "La trésorerie projetée devient négative."))
    if min(lbo.treso_fin) < 0:
        anomalies.append(("ATTENTION", "LBO : la trésorerie devient négative, la dette n'est pas supportable."))
    for a in soc.alertes:
        anomalies.append(("ATTENTION", a))
    for pair in res.comps.pairs:
        for a in pair.societe.alertes:
            anomalies.append(("ATTENTION", a))
    return anomalies
