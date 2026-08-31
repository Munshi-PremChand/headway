# HEADWAY on Cloud Run.
#
# Three things have to be in the image and none of them are Python:
#   * a JRE, because the publish gate is MobilityData's gtfs-validator jar and
#     the whole point is that it is somebody else's binary;
#   * poppler, because a PDF has to become pixels before a vision model can
#     read it;
#   * the validator jar itself, fetched at build time and checked against the
#     sha256 the code pins. A silently different validator would invalidate
#     every ERROR=0 this service reports.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        default-jre-headless \
        poppler-utils \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt "uvicorn[standard]>=0.30" \
    && python -c "import fastapi, uvicorn, google.adk; print('deps ok')"

# The jar is gitignored (binaries do not belong in the tree), so fetch it here
# and FAIL THE BUILD if it is not the exact binary the code gates on.
ARG VALIDATOR_VERSION=8.0.1
ARG VALIDATOR_SHA256=19293ddd9b6f954f216d4f12054bd8a3232921751c4484339e339764a91000e2
RUN mkdir -p vendor && curl -fsSL -o vendor/gtfs-validator-${VALIDATOR_VERSION}-cli.jar \
      "https://github.com/MobilityData/gtfs-validator/releases/download/v${VALIDATOR_VERSION}/gtfs-validator-${VALIDATOR_VERSION}-cli.jar" \
    && echo "${VALIDATOR_SHA256}  vendor/gtfs-validator-${VALIDATOR_VERSION}-cli.jar" | sha256sum -c -

COPY headway/ ./headway/
COPY scripts/ ./scripts/
COPY web/ ./web/
COPY fixtures/ ./fixtures/
COPY Makefile README.md LICENSE ./

# Cloud Run sends SIGTERM and expects a fast, clean exit; uvicorn handles it.
ENV PORT=8080
EXPOSE 8080
CMD exec uvicorn web.app:app --host 0.0.0.0 --port ${PORT} --workers 1 --timeout-keep-alive 75
