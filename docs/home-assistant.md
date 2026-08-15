# El panel en Home Assistant

El servicio sirve su propia web táctil. En Home Assistant se añade como panel lateral,
así que en la tablet de la cocina aparece como una pestaña más.

## Panel lateral

> **`panel_iframe` ya no existe.** Se eliminó de Home Assistant (estaba obsoleto desde
> 2024.4). Si lo pones en `configuration.yaml`, el arranque falla con
> *"Integration 'panel_iframe' not found"* y la ruta devuelve 404. Lo que lo sustituye es
> un panel de tipo **página web**.

Desde la interfaz, que es lo más rápido:

**Ajustes → Paneles de control → Añadir panel → Página web**, y rellena:

* Título: `Compra`
* Icono: `mdi:cart`
* URL: `http://homeassistant.local:8099/?token=EL_TOKEN_DE_APP_API_TOKEN`
* Mostrar en la barra lateral: sí

Cambia la IP por la de la Raspberry y el token por el `APP_API_TOKEN` del `.env`.

Un panel de página web es, por dentro, un panel normal con una única tarjeta `iframe` a
pantalla completa. Si prefieres montarlo a mano en un panel existente:

```yaml
type: iframe
url: "http://homeassistant.local:8099/?token=EL_TOKEN"
aspect_ratio: 100%
```

> Si accedes a Home Assistant por HTTPS (por ejemplo por el dominio de DuckDNS), el
> navegador bloqueará un iframe que apunte a HTTP. Dentro de casa, entrando a HA por su
> IP en HTTP, funciona. Para que funcione también desde fuera, publica el servicio por el
> mismo proxy inverso que HA y usa la URL HTTPS aquí.

## Estado del servicio en Home Assistant

Útil para enterarte de que la sesión de Mercadona ha caducado sin tener que mirar el
panel. Esto sí funciona dentro de un *package* (`packages/mercadona_compra.yaml`), a
diferencia del panel:

```yaml
rest:
  - resource: "http://homeassistant.local:8099/health"
    scan_interval: 300
    sensor:
      - name: "Puente Mercadona"
        value_template: "{{ 'ok' if value_json.ok else 'error' }}"
        json_attributes:
          - session_error
          - catalog_size
          - regulars
```

Y una automatización que avise cuando haya que renovar el token:

```yaml
automation:
  - alias: "Aviso: sesión de Mercadona caducada"
    trigger:
      - platform: state
        entity_id: sensor.puente_mercadona
        to: "error"
        for: "00:10:00"
    action:
      - service: notify.mobile_app_movil
        data:
          title: "Lista de la compra"
          message: >
            El puente con Mercadona ha perdido la sesión:
            {{ state_attr('sensor.puente_mercadona', 'session_error') }}
```

## Avisos cuando el puente duda

El servicio siempre añade su mejor apuesta, pero avisa cuando la elección no está
clara: si el segundo candidato quedaba a menos de `AMBIGUITY_GAP` del primero, si la
confianza no llega a `CONFIDENT_SCORE`, si no encuentra nada o si el alta falla.

Para no tener que guardar un token de Home Assistant en el servicio, el aviso va a un
**webhook**, que HA expone sin autenticación para la red local.

En el package:

```yaml
automation:
  - alias: "Compra: aviso del puente de Mercadona"
    id: mercadona_bridge_alert
    mode: queued
    max: 10
    trigger:
      - platform: webhook
        webhook_id: "UN_ID_LARGO_Y_ALEATORIO"   # trátalo como una contraseña
        allowed_methods: [POST]
        local_only: true
    variables:
      titulo: "{{ trigger.json.titulo | default('Lista de la compra') }}"
      mensaje: "{{ trigger.json.mensaje | default('') }}"
      tipo: "{{ trigger.json.tipo | default('ambiguo') }}"
    action:
      - repeat:
          for_each:
            - notify.mobile_app_TU_MOVIL
          sequence:
            - service: "{{ repeat.item }}"
              data:
                title: "{{ titulo }}"
                message: "{{ mensaje }}"
                data:
                  tag: "mercadona-{{ tipo }}"
                  clickAction: "/compra"     # abre el panel de un toque
      - service: tts.speak
        continue_on_error: true
        target:
          entity_id: tts.TU_MOTOR_DE_VOZ
        data:
          media_player_entity_id: media_player.TU_ALTAVOZ
          message: "{{ mensaje }}"
```

Y en el `.env` del servicio:

```dotenv
HA_WEBHOOK_URL=http://homeassistant.local:8123/api/webhook/UN_ID_LARGO_Y_ALEATORIO
```

Déjalo vacío para no recibir avisos. El `webhook_id` es la única protección del
endpoint, así que conviene que sea largo y aleatorio, `local_only: true` impide además
que se pueda disparar desde fuera de casa.

El servicio manda `tipo` (`ambiguo`, `no_encontrado`, `fallo`), `titulo`, `mensaje`, y
según el caso `frase`, `producto` y `alternativa`, por si quieres afinar el mensaje o
mandar cada tipo a un sitio distinto.

## Añadir por voz desde Assist

Si algún día quieres añadir también desde el micro de la tablet o un Voice PE, sin pasar
por Google:

```yaml
# packages/mercadona_compra.yaml
rest_command:
  compra_anadir:
    url: "http://homeassistant.local:8099/api/voice?token=EL_TOKEN"
    method: POST
    content_type: "application/json"
    payload: '{"text": "{{ producto }}"}'
```

```yaml
# custom_sentences/es/compra.yaml
language: "es"
intents:
  AnadirALaCompra:
    data:
      - sentences:
          - "añade {producto} a la (lista|compra)"
          - "apunta {producto}"
lists:
  producto:
    wildcard: true
```

```yaml
# packages/mercadona_compra.yaml
intent_script:
  AnadirALaCompra:
    action:
      - service: rest_command.compra_anadir
        data:
          producto: "{{ producto }}"
    speech:
      text: "Apuntado"
```

## Tablet siempre despierta

Para que el panel se vea sin tocar nada, en la tablet va bien Fully Kiosk Browser
apuntando directamente a la URL del servicio con el token. El panel ya se refresca solo
cada 20 segundos y cuando la pantalla vuelve a estar visible.
