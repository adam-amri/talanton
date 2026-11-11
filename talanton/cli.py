"""Ligne de commande : `talanton run TICKER --pairs A,B,C`."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from .collecte import ErreurCollecte
from .controles import rapprocher, recalculer, verifier
from .excel import construire_classeur
from .moteur import calculer, collecter
from .retraitement import ErreurRetraitement


def _analyser(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="talanton",
        description="D'un ticker à un modèle de valorisation M&A / LBO dans Excel.")
    sous = parser.add_subparsers(dest="commande", required=True)
    run = sous.add_parser("run", help="construit le modèle d'une société cotée aux États-Unis")
    run.add_argument("ticker", help="ticker de la société cible, par exemple MAT")
    run.add_argument("--pairs", default="", help="tickers des comparables, séparés par des virgules")
    run.add_argument("--cache", type=Path, default=Path("donnees_cache"),
                     help="dossier où sont gardées les données téléchargées (défaut : donnees_cache)")
    run.add_argument("--hors-ligne", action="store_true", help="n'utilise que le cache, sans accès réseau")
    run.add_argument("--ajustements", type=Path,
                     help="fichier TOML d'ajustements d'analyste (défaut : retraitements/TICKER.toml s'il existe)")
    run.add_argument("--hypotheses", type=Path, help="fichier TOML qui remplace des hypothèses par défaut")
    run.add_argument("--sortie", type=Path, default=Path("sorties"), help="dossier du classeur produit")
    run.add_argument("--sans-recalcul", action="store_true",
                     help="n'appelle pas LibreOffice (Excel calculera les formules à l'ouverture)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _analyser(argv)
    ticker = args.ticker.upper()
    pairs = [t.strip().upper() for t in args.pairs.split(",") if t.strip()]
    ajustements = args.ajustements
    if ajustements is None:
        candidat = Path("retraitements") / f"{ticker}.toml"
        ajustements = candidat if candidat.exists() else None

    try:
        donnees = collecter(ticker, pairs, args.cache, args.hors_ligne, ajustements)
        res = calculer(*donnees, fichier_hypotheses=args.hypotheses)
    except (ErreurCollecte, ErreurRetraitement, ValueError) as exc:
        print(f"\nArrêt : {exc}", file=sys.stderr)
        return 1

    anomalies = verifier(res)
    wb, registre = construire_classeur(res, date.today())
    args.sortie.mkdir(parents=True, exist_ok=True)
    fichier = args.sortie / f"{ticker}_modele.xlsx"
    wb.save(fichier)

    h, d, lbo = res.hyp, res.dcf, res.lbo
    mediane = res.comps.implicite.get("ve_ebitda", {}).get("mediane")
    print(f"\n{res.cible.nom} ({ticker}), cours {h.cours:.2f} $, valeur d'entreprise {h.valeur_entreprise:,.0f} M$")
    print(f"  DCF, croissance perpétuelle : {d.action_gordon:6.2f} $ par action (WACC {h.wacc:.2%})")
    print(f"  DCF, multiple de sortie     : {d.action_multiple:6.2f} $ par action")
    if mediane is not None:
        print(f"  Comparables, VE/EBITDA médian : {mediane:6.2f} $ par action")
    print(f"  LBO à {h.prime_acquisition:.0%} de prime : TRI {lbo.tri:.1%}, multiple de la mise {lbo.moic:.2f}x")
    print(f"  Prix maximum d'un fonds visant {h.tri_cible:.0%} de TRI : {lbo.prix_max[h.tri_cible]:.2f} $ par action")

    erreurs = [m for niveau, m in anomalies if niveau == "ERREUR"]
    for niveau, message in anomalies:
        print(f"  [{niveau}] {message}")

    code = 1 if erreurs else 0
    if args.sans_recalcul:
        print("\nFormules non recalculées : Excel les calculera à l'ouverture.")
    elif recalculer(fichier):
        rap = rapprocher(fichier, registre, res.points_de_controle())
        if rap.conforme:
            print(f"\nRapprochement : {rap.n_formules} formules recalculées sans erreur, "
                  f"Excel = Python sur {len(res.points_de_controle())} chiffres clés.")
        else:
            code = 1
            print("\nRapprochement en échec :", file=sys.stderr)
            for cle, (excel, python) in rap.ecarts.items():
                print(f"  {cle} : Excel {excel} / Python {python}", file=sys.stderr)
            for cellule in rap.erreurs_formules[:20] + rap.cellules_vides[:20]:
                print(f"  formule en erreur ou vide : {cellule}", file=sys.stderr)
    else:
        print("\nLibreOffice introuvable : rapprochement Python / Excel non effectué en ligne de commande. "
              "L'onglet Contrôles le fait à l'ouverture du classeur.")
    print(f"Classeur : {fichier}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
