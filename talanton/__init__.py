"""Talanton : d'un ticker à un modèle de valorisation M&A / LBO dans Excel.

Chaîne de traitement :
    collecte      -> comptes publiés (SEC EDGAR) et cours de bourse
    retraitement  -> états financiers au format banque, LTM, ajustements
    modele        -> hypothèses par défaut et projections des trois états
    valorisation  -> DCF, comparables boursiers, LBO
    excel         -> classeur avec formules vivantes
    controles     -> vérifications et rapprochement Python / Excel
"""

__version__ = "0.1.0"
