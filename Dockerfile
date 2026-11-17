# Container für den Betrieb im Internet, z. B. auf Railway: Railway erkennt diese Datei im
# Repo und baut daraus automatisch. Lokal: docker build -t portfolio-optimierer . und
# docker run -p 8501:8501 portfolio-optimierer
FROM python:3.12-slim

# ACCOUNTS=on: Website mit Konten (Registrierung, Anmeldung, eigene Depots je Konto)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ACCOUNTS=on

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

# Beim Start zuerst die Datenbank-Migrationen (portfolio_optimizer/migrations.py), dann die App.
# Nicht als Pre-Deploy-Befehl von Railway: dort ist das Volume nicht eingehängt. Schlägt die
# Migration fehl, startet die App nicht, der Healthcheck schlägt fehl und Railway meldet das
# Deployment als fehlgeschlagen; die Daten bleiben auf dem alten Stand (Sicherung in /data/backups).
# Railway gibt den Port in $PORT vor, sonst gilt 8501. Die Shell-Form ist nötig, damit $PORT
# ersetzt wird. Ohne headless würde Streamlit versuchen, einen Browser zu öffnen.
EXPOSE 8501
CMD ["sh", "-c", "python -m portfolio_optimizer.migrations && exec streamlit run app.py --server.port=${PORT:-8501} --server.address=0.0.0.0 --server.headless=true"]
