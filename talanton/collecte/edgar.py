"""Comptes publiés par les sociétés cotées aux États-Unis (API EDGAR de la SEC).

Deux appels suffisent par société :
  1. la table ticker -> CIK (identifiant SEC) ;
  2. « companyfacts » : tous les chiffres balisés (XBRL) de tous ses dépôts.

L'API est gratuite et sans clé, mais la SEC exige un en-tête User-Agent qui
identifie l'appelant (nom + e-mail) et limite le débit à 10 requêtes/seconde.
Chaque réponse est gardée dans un cache local : on ne retélécharge pas un
fichier de moins de 24 heures, et le mode hors ligne ne lit que le cache.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

URL_TICKERS = "https://www.sec.gov/files/company_tickers.json"
URL_FAITS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
DUREE_CACHE_S = 24 * 3600


class ErreurCollecte(RuntimeError):
    """Donnée introuvable ou source injoignable."""


class ClientEdgar:
    def __init__(self, cache: Path, hors_ligne: bool = False, contact: str | None = None,
                 pause_s: float = 0.2):
        self.cache = Path(cache) / "sec"
        self.hors_ligne = hors_ligne
        self.contact = contact or os.environ.get("TALANTON_CONTACT")
        self.pause_s = pause_s

    # -- accès bas niveau ---------------------------------------------------
    def _lire(self, url: str, fichier: Path) -> dict:
        frais = fichier.exists() and (time.time() - fichier.stat().st_mtime) < DUREE_CACHE_S
        if fichier.exists() and (self.hors_ligne or frais):
            return json.loads(fichier.read_text(encoding="utf-8"))
        if self.hors_ligne:
            raise ErreurCollecte(
                f"Mode hors ligne : {fichier} est absent du cache. "
                "Relance sans --hors-ligne pour le télécharger."
            )
        if not self.contact:
            raise ErreurCollecte(
                "La SEC exige de s'identifier. Définis la variable d'environnement "
                'TALANTON_CONTACT, par exemple : TALANTON_CONTACT="Prénom Nom prenom.nom@exemple.com"'
            )
        import requests  # importé ici : inutile en mode hors ligne

        time.sleep(self.pause_s)
        reponse = requests.get(url, headers={"User-Agent": self.contact}, timeout=60)
        if reponse.status_code == 404:
            raise ErreurCollecte(f"Introuvable chez la SEC : {url}")
        reponse.raise_for_status()
        donnees = reponse.json()
        fichier.parent.mkdir(parents=True, exist_ok=True)
        fichier.write_text(json.dumps(donnees), encoding="utf-8")
        return donnees

    # -- interface ----------------------------------------------------------
    def cik(self, ticker: str) -> tuple[int, str]:
        """Renvoie (CIK, raison sociale) pour un ticker américain."""
        table = self._lire(URL_TICKERS, self.cache / "company_tickers.json")
        for ligne in table.values():
            if ligne["ticker"].upper() == ticker.upper():
                return int(ligne["cik_str"]), ligne["title"]
        raise ErreurCollecte(
            f"Ticker inconnu de la SEC : {ticker}. Talanton v0.1 ne couvre que les "
            "sociétés qui déposent leurs comptes aux États-Unis (10-K / 10-Q)."
        )

    def faits(self, ticker: str) -> dict:
        """Renvoie le document « companyfacts » brut de la société."""
        cik, _ = self.cik(ticker)
        fichier = self.cache / "companyfacts" / f"CIK{cik:010d}.json"
        return self._lire(URL_FAITS.format(cik=cik), fichier)
