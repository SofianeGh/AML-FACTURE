"""Routes de l'application, regroupées par sujet."""
from . import comptes, devis, factures, ndf, reglages, treso

BLUEPRINTS = [comptes.bp, reglages.bp, factures.bp, devis.bp, ndf.bp, treso.bp]
