# Despliegue en la Raspberry (Portainer)

La imagen se construye en la propia Raspberry: `python:3.12-slim` tiene arm64 y las
dependencias son ruedas precompiladas, así que tarda un par de minutos y no hace falta
registro ni build multiarquitectura.

## Opción A, stack de Portainer desde el repositorio

En Portainer: **Stacks → Add stack → Repository**.

* Repository URL: `https://github.com/ALArvi019/mercadona-cart-bridge`
* Compose path: `docker-compose.yml`
* Como el repositorio es privado, marca **Authentication** y usa un token de acceso
  personal de GitHub con permiso de lectura.

En **Environment variables** añade las del `.env` (Portainer las inyecta en el
contenedor, así que no hace falta subir el fichero):

```
MERCADONA_REFRESH_TOKEN, MERCADONA_POSTAL_CODE, MERCADONA_WAREHOUSE,
GKEEP_EMAIL, GKEEP_MASTER_TOKEN, GKEEP_LIST_NAME, APP_API_TOKEN, TZ=Europe/Madrid
```

Al usar variables de Portainer hay que quitar el `env_file: [.env]` del compose, o
Portainer fallará porque ese fichero no existe en el repositorio (y no debe existir).

## Opción B, por SSH, como los demás stacks

```bash
ssh alex@homeassistant.local
mkdir -p ~/portainer-stacks/mercadona-cart-bridge
cd ~/portainer-stacks/mercadona-cart-bridge

git clone https://github.com/ALArvi019/mercadona-cart-bridge.git .
cp .env.example .env
nano .env                 # pega aquí el token de Mercadona y el de Keep
chmod 600 .env

docker compose up -d --build
docker compose logs -f
```

Luego, en Portainer, el stack aparece bajo **Containers** y se puede adoptar desde
**Stacks → Add stack → Use existing** apuntando a ese directorio.

## Comprobar que ha arrancado bien

```bash
curl -s http://homeassistant.local:8099/health
# {"ok":true,"session_error":"","catalog_size":4300,"regulars":78}
```

El primer arranque tarda un par de minutos en tener `catalog_size` distinto de cero:
está descargando el catálogo del almacén. El panel funciona desde el primer momento.

## Copia de seguridad

El volumen `mercadona-data` guarda la sesión renovada, el catálogo y los alias
aprendidos. Lo único irremplazable es `session.json`: sin él hay que volver a extraer el
token del móvil.

Para que entre en el `backup-rclone` que ya corre cada 24 h, añade el volumen a su
configuración, o vuelca el fichero a la carpeta que ya se respalda:

```bash
docker run --rm -v mercadona-data:/data -v ~/backups:/out alpine \
  cp /data/session.json /out/mercadona-session.json
```

## Actualizar

```bash
cd ~/portainer-stacks/mercadona-cart-bridge
git pull
docker compose up -d --build
```

El volumen se conserva, así que la sesión y lo aprendido siguen ahí.
