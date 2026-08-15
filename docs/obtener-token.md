# Obtener el token de Mercadona

El servicio no hace login. No puede: el login con contraseña exige un token de reCAPTCHA
Enterprise que solo se genera dentro de un navegador o de la app oficial. Lo que sí se
puede es **coger prestada una sesión ya iniciada** y renovarla indefinidamente, porque el
`refresh_token` dura meses y se renueva sin captcha.

Solo hay que hacer esto una vez. A partir de ahí el servicio se mantiene solo.

## Opción A, desde la app Android (recomendada, requiere root)

La app guarda la sesión en claro en sus `shared_prefs`, bajo la clave `userJson`.

```bash
adb devices                     # el móvil debe aparecer como 'device'
./tools/extract_token.sh        # vuelca el refresh token y el almacén
```

El script deja los valores por pantalla para que los copies al `.env`, y no los escribe
en ningún fichero del repo.

Si prefieres hacerlo a mano:

```bash
adb shell "su -c 'cat /data/data/es.mercadona.tienda/shared_prefs/es.mercadona.tienda_preferences.xml'"
```

Dentro del XML, la clave `userJson` contiene un JSON con `auth.refresh_token`,
`auth.customer_id`, `postalCode` y `warehouse`.

## Opción B, desde el navegador (sin root)

1. Entra en `https://tienda.mercadona.es` y haz login.
2. Abre las DevTools → pestaña **Red**.
3. Recarga y busca la petición a `api/auth/tokens/` (o cualquiera con `Authorization`).
4. De la respuesta de `auth/tokens/` copia `refresh_token`.

Si no la ves porque la sesión ya estaba iniciada, haz logout y login otra vez.

## Rellenar la configuración

```dotenv
MERCADONA_REFRESH_TOKEN=<el token>
MERCADONA_POSTAL_CODE=28001
MERCADONA_WAREHOUSE=mad1
```

El `warehouse` decide qué catálogo y qué disponibilidad se ven. Sale del mismo `userJson`,
desde el navegador, mira el parámetro `wh=` de cualquier petición a `/api/categories/`.

## Cómo se mantiene viva la sesión

* El `access_token` dura unas 6 semanas, el servicio lo renueva cuando le queda menos de
  un día.
* **El `refresh_token` rota en cada renovación.** El nuevo se guarda en
  `/data/session.json` (el volumen del contenedor). El valor del `.env` solo se usa en el
  primer arranque, cuando todavía no hay sesión guardada.
* Por eso **no borres el volumen** `mercadona-data`: si lo pierdes, el token del `.env`
  estará caducado y habrá que repetir la extracción.

## Cuando deje de funcionar

`GET /health` devuelve `session_error` y el panel muestra un aviso rojo. Pasa si:

* Se cambia la contraseña de la cuenta de Mercadona.
* Se cierra sesión en todos los dispositivos.
* Pasan meses sin que el servicio arranque y caduca el refresh token.

La solución es siempre la misma: repetir la extracción y reiniciar el contenedor.
