# El puente de voz: por qué Google Keep

## Por qué no hay una forma más directa

Un Google Home **no puede enviar texto libre a un servidor propio**. Se comprobaron las
tres vías posibles:

* El editor de scripts de Google Home (`assistant.event.OkGoogle`) solo admite **frases
  fijas** y solo puede actuar sobre dispositivos. No hay acción de webhook ni forma de
  capturar lo que se dijo.
* La integración nativa de Home Assistant con Google expone **entidades**, no dictado.
* IFTTT sí da texto libre, pero es de pago y añade una dependencia de terceros más.

Cuando dices *"Ok Google, añade papel higiénico a la lista de la compra"*, Google escribe
ese texto en una lista de **Google Keep**. Ése es el único sitio donde queda accesible.

## Cómo se usa aquí

Keep es un **buzón**, no la lista. El servicio sondea la lista cada pocos segundos y, por
cada elemento:

1. Lo empareja con un producto real del catálogo.
2. Lo añade al **carrito de Mercadona**.
3. **Lo borra de Keep.**

La lista de Keep está siempre vacía. La lista de verdad es el carrito de la app, que es
donde ya la mirabais. Si el alta falla o el producto es ambiguo, la frase aparece como
pendiente en el panel de la cocina en lugar de perderse.

## Configuración

### 1. Que Assistant escriba en Keep

En la app de Google Home o en los ajustes del Asistente: **Ajustes → Notas y listas →
Google Keep**. Comprueba luego, desde el móvil, que decir "añade X a la lista de la
compra" crea el elemento en una nota de Keep, y apunta el título exacto de esa nota
(suele ser "Lista de la compra").

### 2. Cuenta dedicada (recomendado)

El servicio necesita un *master token* de Google, que da acceso amplio a la cuenta. Para
no poner el de la cuenta principal en la Raspberry:

1. Crea una cuenta de Google nueva.
2. Comparte con ella la lista de Keep (en Keep: **Colaborador → añadir**).
3. Usa esa cuenta en la configuración del servicio.

Si en su lugar prefieres usar la cuenta principal, funciona igual, pero el token del
`.env` pasa a ser una credencial muy sensible.

### 3. Obtener el master token

```bash
python tools/keep_token.py
```

El script pide el correo y un `oauth_token` que se saca así:

1. Abre en una ventana de incógnito `https://accounts.google.com/EmbeddedSetup`
2. Inicia sesión con la cuenta que vas a usar.
3. Cuando la página se quede en blanco o pida aceptar, abre DevTools →
   **Aplicación → Cookies** → busca la cookie **`oauth_token`** (empieza por `oauth2_4/`).
4. Pega ese valor en el script.

Devuelve un token que empieza por `aas_et/`. Ése es el que va al `.env`:

```dotenv
GKEEP_EMAIL=lacuenta@gmail.com
GKEEP_MASTER_TOKEN=aas_et/...
GKEEP_LIST_NAME=Lista de la compra
```

El master token no caduca por tiempo, pero se invalida si cambias la contraseña de esa
cuenta o revocas el acceso desde la sección de seguridad de Google.

**No lo uses desde dos sitios a la vez.** Si otro programa se autentica con el mismo
master token mientras Home Assistant lo está usando, Google empieza a devolver
`BadAuthentication` a uno de los dos. Pasó al probar con un script mientras la
integración corría: el buzón de Home Assistant siguió bien y el script fue el
rechazado, pero conviene no tentar a la suerte.

## Qué se ve en los logs

```
voz: 'papel higiénico'
añadido Papel higiénico Suave Bosque Verde x1.0 (catalog, 0.67)
```

Si Keep falla (token caducado, sin red), el poller espacia los reintentos y lo registra,
pero **el panel y el resto del servicio siguen funcionando**.

## Alternativa sin Keep

El servicio expone `POST /api/voice` con `{"text": "papel higiénico"}`. Cualquier cosa
capaz de hacer una petición HTTP sirve como fuente de voz: un `rest_command` de Home
Assistant disparado por Assist, un botón, IFTTT o un Voice PE. Keep es solo el adaptador
que hace falta para que funcione desde los Google Home que ya tenéis.
