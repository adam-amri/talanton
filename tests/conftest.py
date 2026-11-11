"""Jeu de données des tests : comptes réels enregistrés dans exemples/cache.

Les fichiers de exemples/cache/sec reprennent la structure exacte de l'API
companyfacts de la SEC (extrait réduit aux balises utiles). Aucun test n'a
besoin du réseau.
"""

from pathlib import Path

import pytest

from talanton.collecte import ClientEdgar, ClientMarche
from talanton.moteur import calculer, collecter

RACINE = Path(__file__).resolve().parents[1]
CACHE = RACINE / "exemples" / "cache"
AJUSTEMENTS = RACINE / "exemples" / "retraitements" / "MAT.toml"
PAIRS = ["HAS", "FNKO", "JAKK", "YETI", "GOLF"]


@pytest.fixture(scope="session")
def edgar() -> ClientEdgar:
    return ClientEdgar(CACHE, hors_ligne=True)


@pytest.fixture(scope="session")
def marche() -> ClientMarche:
    return ClientMarche(CACHE, hors_ligne=True)


@pytest.fixture(scope="session")
def donnees():
    return collecter("MAT", PAIRS, CACHE, True, AJUSTEMENTS, journal=lambda *a: None)


@pytest.fixture(scope="session")
def resultat(donnees):
    return calculer(*donnees)
