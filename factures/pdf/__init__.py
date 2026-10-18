"""PDF générés pour chaque facture : récapitulatif par catégorie, bilan final, bilan des ventes."""
from .bilan_final import generer_bilan
from .bilan_ventes import generer_ventes
from .commun import CATEGORIES, DOCUMENTS, NOM_BILAN, NOM_VENTES
from .recap import generer_recap

__all__ = ["CATEGORIES", "DOCUMENTS", "NOM_BILAN", "NOM_VENTES", "generer_bilan", "generer_recap", "generer_ventes"]
