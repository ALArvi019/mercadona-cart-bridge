# La integración de Home Assistant

Además del contenedor, el repositorio incluye una integración nativa en
`custom_components/mercadona/`. Hace lo mismo sin contenedor: habla con Mercadona,
empareja lo que se dicta, lee el buzón de voz y sirve el panel de la cocina.

Las dos comparten el mismo núcleo (`custom_components/mercadona/core/`), así que la
lógica no está duplicada.

## Qué aporta frente al contenedor

* **El carrito como lista de tareas**: `todo.mercadona_carrito` sale en la tarjeta de
  listas, en la app del móvil y en Assist. Se ve la compra sin abrir la app de Mercadona.
* **El panel sin token en la URL**: la autenticación es la de Home Assistant. Antes el
  `APP_API_TOKEN` viajaba en la dirección del iframe.
* **Funciona desde fuera de casa**: al servirse desde el mismo origen que Home
  Assistant, no hay bloqueo por mezclar HTTPS y HTTP.
* **La sesión entra en las copias de Home Assistant**: vive en `.storage`, no en un
  volumen de Docker aparte.

## Instalar

Mientras el repositorio siga siendo privado, se copia a mano:

```bash
scp -r custom_components/mercadona alex@homeassistant.local:~/portainer-stacks/homeassistant/custom_components/
```

Y se reinicia Home Assistant. Después: **Ajustes → Dispositivos y servicios → Añadir
integración → Mercadona**.

## Configurar

La pantalla de alta explica cómo conseguir el token, aquí está el porqué.

### El token de Mercadona

Mercadona **no permite iniciar sesión de forma automática**: su login exige un token de
reCAPTCHA Enterprise que solo se genera dentro de un navegador o de su app. No hay forma
de pedirlo desde Home Assistant.

Lo que sí se puede es coger prestada una sesión ya abierta. La integración pide un
`refresh_token`, que dura meses y **se renueva solo**, así que esto se hace una vez.

Desde el navegador, sin necesidad de root:

1. Inicia sesión en `tienda.mercadona.es`.
2. Herramientas de desarrollo (F12) → pestaña **Red**.
3. Cierra sesión y vuelve a entrar: aparecerá una petición a `api/auth/tokens/`.
4. En su respuesta, copia el valor de `refresh_token`.

Desde la app de Android, si el móvil tiene root, con `./tools/extract_token.sh`.

Detalles importantes:

* **El refresh token rota en cada renovación.** El nuevo se guarda en `.storage`, el
  valor que escribes en la configuración solo sirve para el primer arranque.
* Si la sesión se cae (cambio de contraseña, cierre de sesión en todos los
  dispositivos, meses sin uso), Home Assistant abre **una notificación de
  reautenticación** pidiendo un token nuevo. No hay que reinstalar nada.
* El token da **acceso completo a la cuenta**: trátalo como una contraseña.

### El buzón de voz (opcional)

Un altavoz Google no puede mandar texto libre a Home Assistant. Al decir *"Ok Google,
añade papel higiénico a la lista de la compra"*, lo único que hace es escribirlo en una
lista de Google Keep. La integración usa esa lista como buzón: la lee, mete el producto
en el carrito y borra la entrada.

Hace falta un *master token* de Google, que se saca con `python tools/keep_setup.py`
(ver [google-keep.md](google-keep.md)).

Después, la integración **muestra las listas que encuentra en esa cuenta**, con cuántos
elementos sin marcar tiene cada una, para elegir la correcta. Merece la pena mirar ese
número: al arrancar, lo que esté sin marcar en la lista elegida acabará en el carrito.

Si dejas los dos campos vacíos, el panel y las entidades funcionan igual, solo se queda
fuera la voz.

## Los iconos

Van dentro de la propia integración, en `custom_components/mercadona/brand/`, con
variantes para tema claro y oscuro.

Desde Home Assistant 2026.3 es así como se hace. El repositorio
[home-assistant/brands](https://github.com/home-assistant/brands) **ya no acepta iconos
de integraciones personalizadas**, y los locales tienen prioridad sobre los de su CDN.

```
brand/
  icon.png          icon@2x.png          256 y 512, tema claro
  dark_icon.png     dark_icon@2x.png     256 y 512, tema oscuro
  logo.png          logo@2x.png
  dark_logo.png     dark_logo@2x.png
```

## Qué crea

| Entidad | Para qué |
|---|---|
| `todo.mercadona_carrito` | El carrito como lista: ver, añadir, quitar |
| `sensor.total_del_carrito` | Lo que suma la compra |
| `sensor.productos_en_el_carrito` | Cuántos productos hay, con el detalle en atributos |
| `binary_sensor.sesion_de_mercadona` | Se enciende si la sesión deja de funcionar |

Y un panel **Compra** en la barra lateral.

### Marcar no compra

Marcar un producto en la lista lo **quita del carrito**: significa "ya no lo quiero".
Confirmar el pedido se sigue haciendo a mano en la app de Mercadona. La integración no
toca ningún endpoint de compra.

## Servicios

```yaml
- service: mercadona.anadir
  data:
    producto: "dos paquetes de arroz"   # entiende la cantidad en la frase

- service: mercadona.quitar
  data:
    producto: "mantequilla"

- service: mercadona.vaciar_carrito
```

## Avisos cuando duda

Cuando el emparejador no lo tiene claro, la integración **añade su mejor apuesta y
dispara un evento** en el bus, en lugar de decidir por ti cómo avisarte:

```yaml
automation:
  - alias: "Compra: aviso del puente"
    trigger:
      - platform: event
        event_type: mercadona_aviso
    action:
      - service: notify.mobile_app_TU_MOVIL
        data:
          title: "¿Es esto lo que querías?"
          message: >
            Por «{{ trigger.event.data.frase }}» he puesto
            {{ trigger.event.data.producto }}
            {%- if trigger.event.data.alternativa %},
            pero había otro casi igual: {{ trigger.event.data.alternativa }}
            {%- endif %}
          data:
            image: "{{ trigger.event.data.imagen }}"
            clickAction: "app://es.mercadona.tienda"
```

El evento lleva `tipo` (`ambiguo` o `no_encontrado`), `frase`, `producto`,
`producto_id`, `imagen`, `precio` y `alternativa`.

## Convivencia con el contenedor

Se pueden tener los dos a la vez mientras se prueba: hablan con la misma cuenta y el
mismo carrito. Lo que **no** conviene es dejar los dos leyendo el buzón de Keep, porque
se quitarían el trabajo el uno al otro. Con el buzón configurado en un solo sitio, el
otro sigue funcionando para todo lo demás.
