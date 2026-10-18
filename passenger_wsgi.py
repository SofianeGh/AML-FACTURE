"""Point d'entrée pour les hébergements cPanel / Plesk « Python App » (Phusion Passenger)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from factures import create_app  # noqa: E402

application = create_app()
