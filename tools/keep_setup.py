#!/usr/bin/env python3
"""Configura el buzón de voz de Google Keep de principio a fin.

Pide las credenciales, obtiene el master token, comprueba que puede leer la lista y
lo escribe en el .env indicado. El token nunca se imprime por pantalla: acaba en el
fichero de configuración y nada más.

  python tools/keep_setup.py --env-file .env
  python tools/keep_setup.py --ssh alex@homeassistant.local \
      --env-file ~/portainer-stacks/mercadona-cart-bridge/.env

Instrucciones completas en docs/google-keep.md.
"""
from __future__ import annotations

import argparse
import getpass
import os
import re
import subprocess
import sys
import uuid

try:
    import gpsoauth
except ImportError:
    sys.exit("Falta gpsoauth. Instálalo con: pip install gpsoauth")


def update_env(text: str, values: dict[str, str]) -> str:
    """Reemplaza (o añade) las claves indicadas en el contenido de un .env."""
    for key, value in values.items():
        line = f"{key}={value}"
        pattern = re.compile(rf"^{re.escape(key)}=.*$", re.M)
        text = pattern.sub(lambda _m: line, text) if pattern.search(text) else text.rstrip("\n") + f"\n{line}\n"
    return text


def read_target(ssh: str | None, path: str) -> str:
    if ssh:
        r = subprocess.run(["ssh", ssh, f"cat {path}"], capture_output=True, text=True)
        if r.returncode:
            sys.exit(f"No se pudo leer {path} en {ssh}: {r.stderr.strip()}")
        return r.stdout
    try:
        return open(path).read()
    except FileNotFoundError:
        sys.exit(f"No existe {path}. Copia .env.example a .env primero.")


def write_target(ssh: str | None, path: str, content: str) -> None:
    if ssh:
        r = subprocess.run(["ssh", ssh, f"cat > {path} && chmod 600 {path}"],
                           input=content, capture_output=True, text=True)
        if r.returncode:
            sys.exit(f"No se pudo escribir {path} en {ssh}: {r.stderr.strip()}")
    else:
        with open(path, "w") as f:
            f.write(content)
        os.chmod(path, 0o600)


def main() -> None:
    ap = argparse.ArgumentParser(description="Configura Google Keep como buzón de voz")
    ap.add_argument("--env-file", default=".env", help="ruta del .env a actualizar")
    ap.add_argument("--ssh", help="host remoto (usuario@ip) donde está el .env")
    ap.add_argument("--list-name", help="título exacto de la lista de Keep")
    ap.add_argument("--email", help="correo de la cuenta (si no, se pregunta)")
    args = ap.parse_args()

    # Sin terminal interactiva (por ejemplo lanzado desde otra herramienta) hay que
    # pasar los datos por argumento y entorno, o esto moriría con un EOFError.
    interactive = sys.stdin.isatty()

    if not args.email and not interactive:
        sys.exit("Sin terminal interactiva: pasa --email y la variable OAUTH_TOKEN.\n"
                 "  OAUTH_TOKEN='oauth2_4/...' python tools/keep_setup.py --email tu@correo "
                 "--list-name 'Lista de la compra' [--ssh usuario@host --env-file RUTA]")

    if interactive and not args.email:
        print("Para conseguir el oauth_token:")
        print("  1. Ventana de incógnito → https://accounts.google.com/EmbeddedSetup")
        print("  2. Inicia sesión con la cuenta que recibe la lista.")
        print("  3. DevTools → Aplicación → Cookies → copia la cookie 'oauth_token'")
        print("     (empieza por 'oauth2_4/').\n")

    email = (args.email or input("Correo de la cuenta: ")).strip()
    if not email:
        sys.exit("Hace falta el correo.")

    oauth_token = os.environ.get("OAUTH_TOKEN", "").strip()
    if not oauth_token:
        if not interactive:
            sys.exit("Falta la variable de entorno OAUTH_TOKEN.")
        oauth_token = getpass.getpass("oauth_token (no se muestra): ").strip()
    if not oauth_token:
        sys.exit("Hace falta el oauth_token.")

    print("\nPidiendo el master token a Google…")
    result = gpsoauth.exchange_token(email, oauth_token, uuid.uuid4().hex[:16])
    master_token = result.get("Token")
    if not master_token:
        sys.exit(f"Google no devolvió token. Respuesta: {result.get('Error', result)}\n"
                 "Suele pasar si el oauth_token ya se había usado: repite el paso 1 en "
                 "una ventana de incógnito nueva.")
    print("Master token obtenido.")

    # Comprobar que se puede leer de verdad, y de paso enseñar las listas que hay.
    list_name = args.list_name
    try:
        import gkeepapi
        keep = gkeepapi.Keep()
        keep.authenticate(email, master_token)
        keep.sync()
        notes = [n for n in keep.all() if not n.trashed and getattr(n, "items", None) is not None]
        print(f"\nSesión de Keep correcta. Listas encontradas ({len(notes)}):")
        for n in notes:
            print(f"  - {n.title!r} ({len(n.items)} elementos)")
        if not list_name and interactive:
            list_name = input("\nTítulo exacto de la lista que rellena el Asistente: ").strip()
    except Exception as e:
        print(f"\nAviso: no se pudo verificar la lista ({e}).")
        print("Se guardará el token igualmente.")
        if not list_name and interactive:
            list_name = input("Título exacto de la lista: ").strip()

    values = {"GKEEP_EMAIL": email, "GKEEP_MASTER_TOKEN": master_token}
    if list_name:
        values["GKEEP_LIST_NAME"] = list_name

    target = f"{args.ssh}:{args.env_file}" if args.ssh else args.env_file
    content = update_env(read_target(args.ssh, args.env_file), values)
    write_target(args.ssh, args.env_file, content)

    print(f"\nListo. Credenciales escritas en {target} (permisos 600).")
    print("Ahora reinicia el servicio:")
    if args.ssh:
        print(f"  ssh {args.ssh} 'cd ~/portainer-stacks/mercadona-cart-bridge && docker compose up -d'")
    else:
        print("  docker compose up -d")


if __name__ == "__main__":
    main()
