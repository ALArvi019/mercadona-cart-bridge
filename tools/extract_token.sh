#!/usr/bin/env bash
# Extrae la sesión de Mercadona de un móvil Android rooteado con la app instalada.
# Los valores se muestran por pantalla y no se escriben en ningún fichero del repo.
set -euo pipefail

PKG=es.mercadona.tienda
PREFS="/data/data/$PKG/shared_prefs/${PKG}_preferences.xml"

command -v adb >/dev/null || { echo "adb no está instalado"; exit 1; }

if ! adb get-state >/dev/null 2>&1; then
  echo "No hay ningún dispositivo conectado (adb devices)."; exit 1
fi

if ! adb shell 'su -c id' 2>/dev/null | grep -q 'uid=0'; then
  echo "El dispositivo no da root por adb (hace falta su)."; exit 1
fi

if ! adb shell "su -c 'test -f $PREFS && echo ok'" 2>/dev/null | grep -q ok; then
  echo "No encuentro las preferencias de la app. ¿Está instalada y con sesión iniciada?"; exit 1
fi

adb shell "su -c 'cat $PREFS'" 2>/dev/null | python3 -c '
import sys, re, html, json

raw = sys.stdin.read()
m = re.search(r"name=\"userJson\">(.*?)</string>", raw, re.S)
if not m:
    sys.exit("No hay sesión guardada: abre la app e inicia sesión.")

d = json.loads(html.unescape(m.group(1)))
auth = d.get("auth", {})
if not auth.get("refresh_token"):
    sys.exit("La sesión no tiene refresh token: cierra sesión y vuelve a entrar en la app.")

print()
print("Copia esto a tu .env:")
print()
print(f"MERCADONA_REFRESH_TOKEN={auth[\"refresh_token\"]}")
print(f"MERCADONA_POSTAL_CODE={d.get(\"postalCode\", \"\")}")
print(f"MERCADONA_WAREHOUSE={d.get(\"warehouse\", \"\")}")
print()
print(f"(cuenta: {d.get(\"user\", {}).get(\"email\", \"?\")})")
print()
print("Trata este token como una contraseña: da acceso completo a la cuenta.")
'
