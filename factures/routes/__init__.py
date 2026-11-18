"""Routes de l'application, regroupées par sujet."""
from . import comptes, devis, factures, ndf, reglages

BLUEPRINTS = [comptes.bp, reglages.bp, factures.bp, devis.bp, ndf.bp]
