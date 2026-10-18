"""Routes de l'application, regroupées par sujet."""
from . import comptes, factures, reglages

BLUEPRINTS = [comptes.bp, reglages.bp, factures.bp]
