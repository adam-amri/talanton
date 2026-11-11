"""Collecte et retraitement : les bons chiffres, malgré les pièges des données publiées."""

from datetime import date

import pytest

from talanton.collecte import ClientEdgar, ErreurCollecte
from talanton.collecte.marche import regression_beta
from talanton.retraitement import charger_ajustements, construire_societe
from talanton.retraitement.faits import Faits

from .conftest import AJUSTEMENTS


def pair(edgar, ticker):
    return construire_societe(ticker, edgar.faits(ticker), 1, None, bilan_detaille=False)


def test_exercices_et_dernier_trimestre(donnees):
    cible = donnees[0]
    assert [d.year for d in cible.exercices] == [2021, 2022, 2023, 2024, 2025]
    assert cible.date_bilan == date(2026, 9, 30)
    assert cible.actions == pytest.approx(285.5)


def test_ltm_est_exercice_plus_cumul_moins_cumul_precedent(donnees):
    ltm = donnees[0].ltm
    assert ltm["ca"] == pytest.approx(5347.623 + 3794.187 - 3581.163)
    assert ltm["ebit"] == pytest.approx(546.424 + 384.458 - 405.368)
    assert ltm["da"] == pytest.approx(167.985 + 143.286 - 125.954)


def test_bilans_publies_equilibres(donnees):
    h = donnees[0].hist
    for actif, passif in zip(h["total_actif"], h["total_passif"]):
        assert actif == pytest.approx(passif)
    # les deux postes « solde » restent positifs et plausibles
    assert all(v > 0 for v in h["autres_actifs"] + h["autres_passifs"])


def test_ajustements_d_analyste(donnees):
    cible = donnees[0]
    assert cible.hist["capex"][-1] == pytest.approx(181.992)       # total reconstitué, pas la ligne partielle
    assert cible.ltm["ajust"] == pytest.approx(-88.0)
    assert cible.ltm["ebitda_ajuste"] == pytest.approx(cible.ltm["ebitda_publie"] - 88.0)


def test_sans_ajustement_le_capex_partiel_est_signale(edgar):
    brute = construire_societe("MAT", edgar.faits("MAT"), 5, None)
    assert brute.hist["capex"][-1] == pytest.approx(110.618)
    assert any("Capex" in a for a in brute.alertes)


def test_hasbro_deux_balises_de_chiffre_d_affaires(edgar):
    has = pair(edgar, "HAS")
    assert has.ltm["ca"] == pytest.approx(4701.3 + 3735.1 - 3255.4)    # et non 5 365,9
    assert any("divergent" in a for a in has.alertes)


def test_hasbro_depreciation_de_goodwill_neutralisee_sur_douze_mois(edgar):
    has = pair(edgar, "HAS")
    # 1 021,9 M$ dépréciés au premier semestre 2025 : hors de la fenêtre LTM
    assert has.ltm["depreciations"] == pytest.approx(0.0)
    assert has.ltm["ebit"] == pytest.approx(11.1 + 1040.1 + 286.4)


def test_jakks_actions_en_milliers_dans_le_10q(edgar):
    jakk = pair(edgar, "JAKK")
    assert jakk.actions == pytest.approx(11.519192)                    # page de garde, pas 0,011869


def test_funko_sans_page_de_garde(edgar):
    fnko = pair(edgar, "FNKO")
    assert fnko.actions == pytest.approx(57.111136)
    assert any("actions" in a for a in fnko.alertes)


def test_dette_financiere_toutes_composantes(edgar):
    golf = pair(edgar, "GOLF")
    assert golf.bilan["dette"] == pytest.approx(854.393 + 0.653 + 21.521)
    assert golf.bilan["minoritaires"] == pytest.approx(2.299 + 1.162)
    assert pair(edgar, "JAKK").bilan["dette"] == 0.0


def test_yeti_exercice_de_53_semaines_et_semestre(edgar):
    yeti = pair(edgar, "YETI")
    assert yeti.exercices[-1] == date(2026, 1, 3)
    assert yeti.date_ltm == date(2026, 7, 4)
    assert yeti.ltm["ca"] == pytest.approx(1868.494 + 864.282 - 797.020)


def test_un_trimestre_seul_n_est_pas_un_cumul(edgar):
    faits = Faits(edgar.faits("JAKK"))
    # ProfitLoss 2026 : seul le troisième trimestre est publié, pas le cumul sur neuf mois
    assert faits.cumul("ProfitLoss", date(2026, 1, 1), date(2026, 9, 30)) is None
    assert faits.cumul("NetIncomeLoss", date(2026, 1, 1), date(2026, 9, 30)).valeur == 31482000


def test_la_derniere_publication_l_emporte():
    brut = {"cik": 1, "entityName": "Test", "facts": {"us-gaap": {"Revenues": {"units": {"USD": [
        {"start": "2024-01-01", "end": "2024-12-31", "val": 100, "accn": "a", "form": "10-K", "filed": "2025-02-01"},
        {"start": "2024-01-01", "end": "2024-12-31", "val": 104, "accn": "b", "form": "10-K", "filed": "2026-02-01"},
        {"start": "2024-10-01", "end": "2024-12-31", "val": 30, "accn": "a", "form": "10-K", "filed": "2025-02-01"},
    ]}}}}}
    assert Faits(brut).annuel("Revenues", date(2024, 12, 31)).valeur == 104     # chiffre retraité


def test_hors_ligne_sans_cache(tmp_path):
    with pytest.raises(ErreurCollecte):
        ClientEdgar(tmp_path, hors_ligne=True).faits("MAT")


def test_ticker_inconnu(edgar):
    with pytest.raises(ErreurCollecte):
        edgar.cik("XXXX")


def test_beta_sur_serie_construite():
    indice = [(date(2024, m, 1), 100 * 1.01 ** m * (1 + 0.02 * (-1) ** m)) for m in range(1, 13)]
    indice += [(date(2025, m, 1), 113 * 1.01 ** m * (1 + 0.02 * (-1) ** m)) for m in range(1, 13)]
    titre = [indice[0]]
    for (_, p0), (d, p1) in zip(indice, indice[1:]):
        titre.append((d, titre[-1][1] * (1 + 1.5 * (p1 / p0 - 1))))
    beta, n, r2 = regression_beta(titre, indice)
    assert (round(beta, 6), n, round(r2, 6)) == (1.5, 23, 1.0)


def test_beta_de_mattel(marche):
    beta, n, r2 = marche.beta("MAT")
    assert n == 58 and 0.4 < beta < 0.8 and r2 < 0.2


def test_fichier_d_ajustements():
    aj = charger_ajustements(AJUSTEMENTS)
    assert len(aj.capex) == 5 and aj.ebitda == {"LTM": -88.0} and "stockanalysis" in aj.source_capex


# --- chemins « en ligne », avec un réseau simulé (aucun appel réel) -----------------

def test_telechargement_sec_identifie_et_mis_en_cache(tmp_path, monkeypatch):
    appels = []

    class Reponse:
        status_code = 200

        def __init__(self, url):
            self.url = url

        def raise_for_status(self):
            pass

        def json(self):
            if "company_tickers" in self.url:
                return {"0": {"cik_str": 63276, "ticker": "MAT", "title": "MATTEL INC /DE/"}}
            return {"cik": 63276, "entityName": "MATTEL INC /DE/", "facts": {}}

    def faux_get(url, headers, timeout):
        appels.append((url, headers["User-Agent"]))
        return Reponse(url)

    monkeypatch.setattr("requests.get", faux_get)
    client = ClientEdgar(tmp_path, contact="Test Talanton test@exemple.com", pause_s=0)
    assert client.faits("mat")["cik"] == 63276
    assert [u for u, _ in appels] == ["https://www.sec.gov/files/company_tickers.json",
                                      "https://data.sec.gov/api/xbrl/companyfacts/CIK0000063276.json"]
    assert all(agent == "Test Talanton test@exemple.com" for _, agent in appels)
    client.faits("MAT")
    assert len(appels) == 2                                     # second appel servi par le cache


def test_la_sec_exige_de_s_identifier(tmp_path, monkeypatch):
    monkeypatch.delenv("TALANTON_CONTACT", raising=False)
    with pytest.raises(ErreurCollecte, match="TALANTON_CONTACT"):
        ClientEdgar(tmp_path).faits("MAT")


def test_cours_en_ligne_avec_yfinance_simule(tmp_path, monkeypatch):
    import sys
    import types

    pd = pytest.importorskip("pandas")
    from talanton.collecte import ClientMarche

    aujourd_hui = date.today().replace(day=1)

    class FauxTicker:
        def __init__(self, ticker):
            self.ticker = ticker

        def history(self, period, interval, auto_adjust):
            if interval == "1d":
                return pd.DataFrame({"Close": [15.35, float("nan"), 15.59]},
                                    index=pd.to_datetime(["2026-11-06", "2026-11-07", "2026-11-09"]))
            mois = pd.to_datetime(["2026-08-01", "2026-09-01", "2026-10-01", aujourd_hui.isoformat()])
            return pd.DataFrame({"Close": [14.95, 12.66, 15.42, 99.0]}, index=mois)

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=FauxTicker))
    client = ClientMarche(tmp_path)
    cours = client.dernier_cours("MAT")
    assert (cours.cours, cours.date) == (15.59, date(2026, 11, 9))
    serie = client.mensuel("MAT")
    assert [p for _, p in serie] == [14.95, 12.66, 15.42]       # le mois en cours, incomplet, est écarté
    relu = ClientMarche(tmp_path, hors_ligne=True)              # ce qui a été téléchargé se relit hors ligne
    assert relu.dernier_cours("MAT").cours == 15.59 and relu.mensuel("MAT") == serie
