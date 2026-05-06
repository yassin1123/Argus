FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 libffi-dev shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# Celery fork workers need explicit path; otherwise `from db...` fails in tasks.
ENV PYTHONPATH=/app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the DeBERTa NLI cross-encoder so cold container starts don't
# spend ~30s pulling the ~440MB model on every boot. The download is ignored
# at runtime by services that don't need NLI; only nli_worker activates it
# via the `cross-encoder/nli-deberta-v3-base` model id.
RUN python -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/nli-deberta-v3-base')"

# Pre-download the spaCy English small model (~50MB) for the lexical-overlap
# entity extractor (Week 2 / Day 2). Lives in the main worker; nli_worker
# inherits it because both services share this image, but only the main
# worker imports core.nli.entity_extractor.
RUN python -m spacy download en_core_web_sm

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
