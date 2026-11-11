"""Moteur de calcul : identités comptables et financières qui doivent toujours tenir."""

import copy
from datetime import date

import pytest

from talanton.modele import appliquer_surcharges, edate, projeter
from talanton.valorisation import calculer_dcf, calculer_lbo, quartile, tri_lbo
from talanton.valorisation.dcf import ve_gordon
from talanton.valorisation.lbo import DUREE


def test_bilan_projete_equilibre(resultat):
    p = resultat.proj
    for actif, passif in zip(p.total_actif, p.total_passif):
        assert actif == pytest.approx(passif, rel=1e-12)


def test_la_tresorerie_suit_les_flux(resultat):
    p, h = resultat.proj, resultat.hyp
    treso = resultat.cible.dernier["tresorerie"]
    for t in range(h.n):
        flux = p.rn[t] + p.da[t] - p.var_bfr[t] - p.capex[t] - h.distributions[t]
        assert p.var_treso[t] == pytest.approx(flux)
        treso += flux
        assert p.tresorerie[t] == pytest.approx(treso)


def test_premiere_annee_cale_sur_les_douze_derniers_mois(resultat):
    cible, p = resultat.cible, resultat.proj
    assert p.ca[0] == pytest.approx(cible.ltm["ca"])
    assert p.ebitda[0] == pytest.approx(cible.ltm["ebitda_ajuste"])


def test_wacc(resultat):
    h = resultat.hyp
    ke = h.taux_sans_risque + (0.67 * h.beta_brut + 0.33) * h.prime_marche
    attendu = (1 - h.poids_dette) * ke + h.poids_dette * h.cout_dette * 0.75
    assert h.wacc == pytest.approx(attendu)


def test_dcf_recalcule_a_la_main(resultat):
    h, p, d = resultat.hyp, resultat.proj, resultat.dcf
    assert d.fraction == pytest.approx((date(2026, 12, 31) - date(2026, 9, 30)).days / 365)
    fcf = [(p.ebit[t] * (1 - h.taux_is) + p.da[t] - p.capex[t] - p.var_bfr[t]) for t in range(h.n)]
    f, w, g = d.fraction, h.wacc, h.croissance_perpetuelle
    valeur = fcf[0] * f / (1 + w) ** (f / 2)
    valeur += sum(fcf[k] / (1 + w) ** (f + k - 0.5) for k in range(1, h.n))
    valeur += fcf[-1] * (1 + g) / (w - g) / (1 + w) ** (f + h.n - 1.5)
    assert d.ve_gordon == pytest.approx(valeur)
    assert d.action_gordon == pytest.approx((valeur - h.dette + h.tresorerie) / h.actions)
    assert ve_gordon(d.fcf, d.poids, d.temps, w, g) == pytest.approx(d.ve_gordon)


def test_dcf_sans_proratisation_ni_milieu_d_annee(resultat):
    h = copy.deepcopy(resultat.hyp)
    h.date_valo, h.mi_annee = date(2025, 12, 31), 0
    p = projeter(resultat.cible, h)
    d = calculer_dcf(p, h)
    assert d.temps == pytest.approx([1, 2, 3, 4, 5, 6])
    assert d.poids == [1.0] * 6


def test_lbo_ressources_egales_emplois(resultat):
    lbo = resultat.lbo
    assert lbo.nouvelle_dette + lbo.treso_cloture + lbo.equity_sponsor == pytest.approx(lbo.total_emplois)
    assert lbo.nouvelle_dette == pytest.approx(5.0 * resultat.cible.ltm["ebitda_ajuste"])


def test_lbo_la_dette_baisse_de_la_tresorerie_disponible(resultat):
    lbo, h = resultat.lbo, resultat.hyp
    dette = lbo.nouvelle_dette
    for k in range(DUREE):
        assert lbo.interets[k] == pytest.approx(dette * h.taux_lbo)
        assert lbo.amortissement[k] + lbo.sweep[k] == pytest.approx(lbo.fcf[k])   # sweep à 100 %
        dette -= lbo.fcf[k]
        assert lbo.dette_fin[k] == pytest.approx(dette)
        assert lbo.treso_fin[k] == pytest.approx(h.treso_min)


def test_lbo_tri_solution_de_la_valeur_actuelle_nette(resultat):
    lbo = resultat.lbo
    van = -lbo.equity_sponsor + lbo.equity_sortie / (1 + lbo.tri) ** DUREE
    assert van == pytest.approx(0.0, abs=1e-6)
    assert lbo.moic == pytest.approx((1 + lbo.tri) ** DUREE)


@pytest.mark.parametrize("ecart", [0.0, -1.0, 1.5])
def test_lbo_prix_maximum_aller_retour(resultat, ecart):
    """Racheter au prix maximum calculé doit donner exactement le TRI visé."""
    h = copy.deepcopy(resultat.hyp)
    h.ecart_multiple_sortie = ecart
    proj = projeter(resultat.cible, h)
    for cible_tri, prix in calculer_lbo(resultat.cible, proj, h).prix_max.items():
        h2 = copy.deepcopy(h)
        h2.prime_acquisition = prix / h.cours - 1
        assert calculer_lbo(resultat.cible, proj, h2).tri == pytest.approx(cible_tri, abs=1e-10)


def test_sensibilites_case_centrale_egale_cas_de_base(resultat):
    s, d, lbo = resultat.sensi, resultat.dcf, resultat.lbo
    assert s.dcf_gordon[2][2] == pytest.approx(d.action_gordon)
    assert s.dcf_multiple[2][2] == pytest.approx(d.action_multiple)
    assert s.lbo_sortie[2][2] == pytest.approx(lbo.tri)
    assert s.lbo_prime[2][2] == pytest.approx(lbo.tri)
    # plus on paie cher, moins le fonds gagne ; plus on revend cher, plus il gagne
    assert s.lbo_prime[0][2] > s.lbo_prime[4][2]
    assert s.lbo_prime[2][0] < s.lbo_prime[2][4]


def test_tri_lbo_coherent_avec_un_recalcul_complet(resultat):
    h = copy.deepcopy(resultat.hyp)
    h.prime_acquisition = 0.40
    complet = calculer_lbo(resultat.cible, resultat.proj, h)
    rapide = tri_lbo(resultat.cible, resultat.proj, resultat.hyp, resultat.lbo, prime=0.40,
                     multiple_sortie=complet.multiple_sortie)
    assert rapide == pytest.approx(complet.tri)


def test_quartiles_comme_excel():
    assert quartile([1, 2, 3, 4, 5], 0.25) == 2
    assert quartile([1, 2, 3, 4], 0.25) == 1.75
    assert quartile([4, 1, 3, 2], 0.5) == 2.5
    assert quartile([], 0.5) is None


def test_multiples_non_significatifs_ecartes(resultat):
    comps = resultat.comps
    funko = next(p for p in comps.pairs if p.societe.ticker == "FNKO")
    assert funko.multiple("per", comps.plafond) is None           # PER supérieur au plafond
    ve = 57.111136 * 7.125 + (178.657 + 17.207 + 1.5) - 41.605 + 0.352
    ebitda = (-45.543 + 27.458 + 51.517) + (59.097 + 45.567 - 44.319)
    assert funko.multiple("ve_ebitda", comps.plafond) == pytest.approx(ve / ebitda)
    assert len(comps.valeurs("ve_ebitda")) == 5 and len(comps.valeurs("per")) == 4


def test_football_field_bornes_ordonnees(resultat):
    for libelle, bas, haut in resultat.football:
        assert bas is not None and haut is not None and bas <= haut, libelle


def test_edate():
    assert edate(date(2025, 12, 31), 12) == date(2026, 12, 31)
    assert edate(date(2024, 2, 29), 12) == date(2025, 2, 28)


def test_surcharges_d_hypotheses(resultat, tmp_path):
    fichier = tmp_path / "hyp.toml"
    fichier.write_text('prime_acquisition = 0.4\nmarge_ebitda = 0.13\ncroissance = [0.03, 0.03, 0.03, 0.02, 0.02, 0.02]\n')
    h = copy.deepcopy(resultat.hyp)
    assert appliquer_surcharges(h, fichier) == ["prime_acquisition", "marge_ebitda", "croissance"]
    assert h.prime_acquisition == 0.4 and h.marge_ebitda == [0.13] * 6 and h.croissance[3] == 0.02
    fichier.write_text("inconnue = 1\n")
    with pytest.raises(ValueError):
        appliquer_surcharges(h, fichier)
