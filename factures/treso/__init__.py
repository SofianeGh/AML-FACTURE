"""Trésorerie de l'association : relevés bancaires, classement par mandat, compte de résultat.

Reprise en Python de l'application AML Trésorerie (Java + PostgreSQL, dépôt AILANE-AMAR/AML-TRESO),
dans la même base SQLite que le reste de l'application. Les transactions peuvent être reliées aux
notes de frais et aux factures de l'onglet « Devis et factures ».
"""
from .stockage import Tresorerie

__all__ = ["Tresorerie"]
