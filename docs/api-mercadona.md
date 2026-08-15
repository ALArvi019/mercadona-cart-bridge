# API de Mercadona (no oficial)

Mapa de la API privada de `tienda.mercadona.es`, obtenido en agosto de 2026 a partir de la
app Android (`es.mercadona.tienda`) y verificado contra el servidor real. **No es una API
pública ni documentada: puede cambiar sin aviso.**

Base: `https://tienda.mercadona.es/api`
Backend: Django REST Framework (responde a `OPTIONS` indicando métodos permitidos).

## Autenticación

Bearer JWT en la cabecera `Authorization`.

| Token | Duración observada | Notas |
|---|---|---|
| `access_token` | ~6 semanas | Se usa en todas las llamadas |
| `refresh_token` | ~5 meses | **Rota en cada renovación**: hay que persistir el nuevo |

### Renovar

```
POST /api/auth/tokens/
{"refresh_token": "<token>"}
→ 200 {"access_token": "...", "refresh_token": "...", "customer_id": "<uuid>"}
```

No requiere captcha. El login con contraseña (`{username, password, recaptcha_token}`)
sí exige un token de reCAPTCHA Enterprise que solo se puede generar en un navegador o en
la app, por eso este proyecto **no implementa login**: parte de un `refresh_token`
extraído una vez (ver [obtener-token.md](obtener-token.md)) y lo va renovando solo.

**El token anterior sigue valiendo después de rotar.** Comprobado en agosto de 2026:
tras renovar y obtener un `refresh_token` nuevo, reutilizar el viejo devuelve 200 y
entrega otra pareja de tokens. Es lo que permite que el contenedor y la integración de
Home Assistant convivan partiendo del mismo token. No conviene apoyarse en ello a
largo plazo: es comportamiento observado, no documentado, y puede cambiar.

### Cabeceras

```
Authorization: Bearer <access_token>
Accept: application/json
Accept-Language: es
Content-Type: application/json
X-Customer-Device-Id: <uuid>
```

## Cliente

```
GET /api/customers/<uuid>/
→ {id, uuid, email, name, current_postal_code, cart_id, ...}
```

El `warehouse` (p. ej. `mad1`) no viene aquí, se guarda en el cliente y se pasa como
`?wh=<warehouse>` en las llamadas de catálogo. Determina qué productos existen.

## Carrito

`OPTIONS` → `Allow: GET, PUT, HEAD, OPTIONS`

### Leer

```
GET /api/customers/<uuid>/cart/
→ {
    "id": "<cart uuid>",
    "version": 113,
    "lines": [{"quantity": 1.0, "sources": ["+CT"], "version": 113, "product": {...}}],
    "open_order_id": null,
    "summary": {...},
    "products_count": 10
  }
```

### Escribir

**No hay endpoint para añadir una línea suelta.** El carrito se reemplaza entero:

```
PUT /api/customers/<uuid>/cart/
{
  "version": 113,
  "lines": [{"product_id": "14122", "quantity": 1.0, "sources": ["+CT"]}]
}
→ 200 con el carrito ya actualizado y "version" incrementada
```

Consecuencias de diseño, importantes:

* Es un *read-modify-write*. Hay que leer el carrito, modificar la lista y volver a
  escribirla completa. Si alguien toca el carrito desde la app entre ambos pasos, se
  pisan los cambios: por eso el cliente serializa las escrituras y reintenta releyendo.
* `version` implementa control de concurrencia optimista. Enviar una versión antigua
  puede rechazarse, el cliente relee y reintenta.
* Omitir una línea la **borra**. Un cuerpo mal construido vacía el carrito, así que el
  cliente nunca escribe una lista vacía sin que se lo pidan explícitamente.
* `sources` es telemetría de Mercadona (`+CT` = añadido desde el carrito). Se conserva
  el valor original de cada línea y se usa `+CT` para las nuevas.

### IDs de producto

Son cadenas, no enteros, y algunos llevan sufijo decimal para variantes de formato
(p. ej. `23086.2` = barra de pan rebanada). Tratarlos siempre como `str`.

## Productos habituales

```
GET /api/customers/<uuid>/recommendations/myregulars/
→ [ {"product": {...}, ...}, ... ]
```

Devuelve una lista plana (no paginada) con lo que la app muestra en "Mis habituales",
en esta cuenta, 78 productos. Es la fuente del panel de la tablet y la primera fuente
del emparejador de voz. Solo lectura.

## Pedidos

```
GET /api/customers/<uuid>/orders/                      # historial
GET /api/customers/<uuid>/orders/<order_id>/           # detalle con líneas
```

Se usa como segunda fuente del emparejador: lo que ya se ha comprado antes gana sobre
un resultado cualquiera del catálogo.

## Catálogo (sin autenticación)

```
GET /api/categories/?lang=es&wh=<warehouse>            # árbol de 26 categorías raíz
GET /api/categories/<id>/?lang=es&wh=<warehouse>       # subcategorías con sus productos
GET /api/products/<id>/?lang=es&wh=<warehouse>         # detalle de producto
```

Los productos vienen anidados en `categories[].products[]` al pedir una categoría raíz.
Campos útiles: `id`, `display_name`, `packaging`, `thumbnail`, `published`, `status`,
`price_instructions.unit_price`.

**Con sesión iniciada, el parámetro `wh` sobra.** Pedir la misma categoría con
`wh=mad1` y sin `wh`, mandando el `Authorization`, devuelve exactamente los mismos
productos, precios y disponibilidad: el servidor resuelve el almacén a partir de la
cuenta. Por eso la integración no obliga a averiguar el código del almacén. Sin
autenticar sí hace falta, o se sirve un catálogo genérico.

La app usa Algolia para buscar, pero sus credenciales rotan y hay que rascarlas del
bundle. Este proyecto no las usa: descarga el catálogo del almacén una vez al día y
busca en local. Menos frágil y permite emparejamiento difuso sin depender de terceros.

## Otros endpoints vistos en la app

No los usa este proyecto, quedan anotados por si hicieran falta:

```
GET/POST /api/customers/<uuid>/shopping-lists/          # listas propias de Mercadona
POST     /api/customers/<uuid>/shopping-lists/create-with-product/
         /api/customers/<uuid>/checkouts/...            # todo el flujo de compra
POST     /api/customers/<uuid>/orders/<id>/repeat/      # repetir un pedido
PUT      /api/postal-codes/actions/change-pc/
```

**Este proyecto no toca ningún endpoint de `checkouts/`.** Añadir al carrito no compra
nada, la compra se sigue confirmando a mano desde la app.
