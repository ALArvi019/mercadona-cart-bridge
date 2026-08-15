FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
# El nucleo es compartido con la integracion de Home Assistant y vive en
# custom_components/. En el repo, app/core es un enlace a esa carpeta; aqui se
# copia el contenido real en su lugar.
COPY custom_components/mercadona/core ./app/core

# El estado (sesión renovada, catálogo, base de datos) vive en un volumen: si se
# pierde, hay que volver a extraer el token del móvil.
VOLUME ["/data"]
EXPOSE 8099

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8099/health',timeout=5).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8099"]
