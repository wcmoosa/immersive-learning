FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies install from a vendored wheelhouse (see README) with no network
# access. This keeps `docker compose up` fully offline and immune to DNS/PyPI
# hiccups during a live demo (plan KTD2 offline posture, "demo cannot stall").
# The app itself runs from /app (WORKDIR), so it need not be pip-installed —
# installing the dependency wheels directly avoids needing a build backend.
COPY wheelhouse ./wheelhouse
RUN pip install --no-index --no-cache-dir ./wheelhouse/*.whl

COPY pyproject.toml ./
COPY app ./app
COPY content ./content

COPY docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh

EXPOSE 8100

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
