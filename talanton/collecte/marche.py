"""Données de marché : dernier cours, historique mensuel, bêta, taux sans risque.

Source en ligne : Yahoo Finance via la bibliothèque yfinance (gratuite, sans
garantie de qualité institutionnelle, à réserver à un usage personnel).
Tout passe par un cache local, relu tel quel en mode hors ligne.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .edgar import ErreurCollecte

INDICE_REFERENCE = "^GSPC"      # S&P 500, pour le bêta
TAUX_10_ANS = "^TNX"            # rendement du Treasury 10 ans, en %


@dataclass(frozen=True)
class Cours:
    ticker: str
    date: date
    cours: float
    devise: str
    source: str


def _nom_fichier(ticker: str) -> str:
    return ticker.replace("^", "_")


def regression_beta(titre: list[tuple[date, float]], indice: list[tuple[date, float]]
                    ) -> tuple[float, int, float]:
    """Bêta = pente de la régression des rendements mensuels du titre sur ceux de l'indice.

    Renvoie (bêta, nombre de rendements, R²). Ne garde que les mois communs.
    """
    prix_indice = dict(indice)
    communs = [(d, p, prix_indice[d]) for d, p in sorted(titre) if d in prix_indice]
    if len(communs) < 13:
        raise ErreurCollecte("Historique trop court pour estimer un bêta (12 rendements minimum).")
    rt = [communs[i][1] / communs[i - 1][1] - 1 for i in range(1, len(communs))]
    ri = [communs[i][2] / communs[i - 1][2] - 1 for i in range(1, len(communs))]
    n = len(rt)
    mt, mi = sum(rt) / n, sum(ri) / n
    cov = sum((a - mt) * (b - mi) for a, b in zip(rt, ri))
    var_i = sum((b - mi) ** 2 for b in ri)
    var_t = sum((a - mt) ** 2 for a in rt)
    beta = cov / var_i
    r2 = (cov * cov) / (var_i * var_t) if var_t else 0.0
    return beta, n, r2


class ClientMarche:
    def __init__(self, cache: Path, hors_ligne: bool = False):
        self.cache = Path(cache) / "marche"
        self.hors_ligne = hors_ligne

    # -- cache --------------------------------------------------------------
    def _cours_en_cache(self) -> dict:
        fichier = self.cache / "cours.json"
        return json.loads(fichier.read_text(encoding="utf-8")) if fichier.exists() else {}

    def _ecrire_cours(self, ticker: str, c: Cours) -> None:
        tous = self._cours_en_cache()
        tous[ticker] = {"date": c.date.isoformat(), "cours": c.cours, "devise": c.devise,
                        "source": c.source}
        self.cache.mkdir(parents=True, exist_ok=True)
        (self.cache / "cours.json").write_text(json.dumps(tous, indent=1, ensure_ascii=False),
                                               encoding="utf-8")

    # -- dernier cours ------------------------------------------------------
    def dernier_cours(self, ticker: str) -> Cours:
        if not self.hors_ligne:
            try:
                c = self._telecharger_cours(ticker)
                self._ecrire_cours(ticker, c)
                return c
            except ImportError as exc:
                raise ErreurCollecte(
                    "Cours en ligne : installe yfinance (`pip install yfinance`) "
                    "ou relance avec --hors-ligne sur un cache existant."
                ) from exc
        ligne = self._cours_en_cache().get(ticker)
        if ligne is None:
            raise ErreurCollecte(f"Aucun cours en cache pour {ticker}.")
        return Cours(ticker, date.fromisoformat(ligne["date"]), float(ligne["cours"]),
                     ligne["devise"], ligne["source"])

    def _telecharger_cours(self, ticker: str) -> Cours:
        import yfinance as yf

        histo = yf.Ticker(ticker).history(period="5d", interval="1d", auto_adjust=False)
        histo = histo.dropna(subset=["Close"])
        if histo.empty:
            raise ErreurCollecte(f"Aucun cours renvoyé par Yahoo Finance pour {ticker}.")
        jour = histo.index[-1].date()
        devise = "%" if ticker == TAUX_10_ANS else "USD"
        return Cours(ticker, jour, float(histo["Close"].iloc[-1]), devise,
                     f"Yahoo Finance, clôture du {jour.isoformat()}")

    # -- historique mensuel et bêta ----------------------------------------
    def mensuel(self, ticker: str) -> list[tuple[date, float]]:
        fichier = self.cache / f"mensuel_{_nom_fichier(ticker)}.csv"
        if not self.hors_ligne:
            try:
                serie = self._telecharger_mensuel(ticker)
            except ImportError as exc:
                raise ErreurCollecte("Historique en ligne : installe yfinance.") from exc
            self.cache.mkdir(parents=True, exist_ok=True)
            with fichier.open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["date", "cloture_ajustee"])
                w.writerows((d.isoformat(), f"{p:.4f}") for d, p in serie)
            return serie
        if not fichier.exists():
            raise ErreurCollecte(f"Aucun historique mensuel en cache pour {ticker}.")
        with fichier.open(encoding="utf-8") as f:
            return [(date.fromisoformat(r["date"]), float(r["cloture_ajustee"]))
                    for r in csv.DictReader(f)]

    def _telecharger_mensuel(self, ticker: str) -> list[tuple[date, float]]:
        import yfinance as yf

        histo = yf.Ticker(ticker).history(period="5y", interval="1mo", auto_adjust=True)
        histo = histo.dropna(subset=["Close"])
        aujourd_hui = date.today()
        serie = []
        for horodatage, prix in histo["Close"].items():
            d = horodatage.date().replace(day=1)
            if (d.year, d.month) == (aujourd_hui.year, aujourd_hui.month):
                continue  # mois en cours : incomplet
            serie.append((d, float(prix)))
        return serie

    def beta(self, ticker: str, indice: str = INDICE_REFERENCE) -> tuple[float, int, float]:
        return regression_beta(self.mensuel(ticker), self.mensuel(indice))

    def taux_sans_risque(self) -> Cours:
        """Rendement du Treasury 10 ans, exprimé en fraction (0,0486 pour 4,86 %)."""
        c = self.dernier_cours(TAUX_10_ANS)
        return Cours(c.ticker, c.date, c.cours / 100.0, "fraction", c.source)
