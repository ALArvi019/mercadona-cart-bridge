#!/usr/bin/env python3
"""Obtiene el master token de Google necesario para leer la lista de Keep.

Solo hay que ejecutarlo una vez. Instrucciones completas en docs/google-keep.md.
"""
from __future__ import annotations

import getpass
import sys
import uuid

try:
    import gpsoauth
except ImportError:
    sys.exit("Falta gpsoauth. Instálalo con: pip install gpsoauth")


def main() -> None:
    print(__doc__)
    print("Pasos para conseguir el oauth_token:")
    print("  1. En una ventana de incógnito, abre:")
    print("     https://accounts.google.com/EmbeddedSetup")
    print("  2. Inicia sesión con la cuenta que va a leer la lista.")
    print("  3. DevTools → Aplicación → Cookies → copia la cookie 'oauth_token'")
    print("     (empieza por 'oauth2_4/').\n")

    email = input("Correo de la cuenta: ").strip()
    if not email:
        sys.exit("Hace falta el correo.")

    oauth_token = getpass.getpass("oauth_token (no se muestra al escribir): ").strip()
    if not oauth_token:
        sys.exit("Hace falta el oauth_token.")

    # El android_id identifica el 'dispositivo'; vale cualquiera estable.
    android_id = uuid.uuid4().hex[:16]

    result = gpsoauth.exchange_token(email, oauth_token, android_id)
    token = result.get("Token")
    if not token:
        sys.exit(f"Google no devolvió token: {result}")

    print("\nAñade esto a tu .env:\n")
    print(f"GKEEP_EMAIL={email}")
    print(f"GKEEP_MASTER_TOKEN={token}")
    print("\nTrátalo como una contraseña: da acceso amplio a esa cuenta de Google.")


if __name__ == "__main__":
    main()
