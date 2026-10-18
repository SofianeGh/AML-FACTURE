FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    DATA_DIR=/data

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# utilisateur sans privilèges ; /data contient la base (comptes, réglages) et la clé secrète
RUN useradd --system --uid 1000 aml \
    && mkdir -p /data && chown aml /data
USER aml
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/connexion')"

CMD ["python", "-m", "factures"]
