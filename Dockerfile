# --- Stage 1: fetch the duplicacy CLI binary (only used by the optional poller) ---
# The exporter runs fine without it; the binary just enables POLLER_ENABLED mode.
FROM alpine:3.21 AS duplicacy

ARG DUPLICACY_VERSION=3.2.5
ARG TARGETARCH

RUN apk add --no-cache ca-certificates wget && \
    case "${TARGETARCH}" in \
        amd64) DUP_ARCH="x64" ;; \
        arm64) DUP_ARCH="arm64" ;; \
        *) echo "unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac && \
    wget -O /usr/local/bin/duplicacy \
        "https://github.com/gilbertchen/duplicacy/releases/download/v${DUPLICACY_VERSION}/duplicacy_linux_${DUP_ARCH}_${DUPLICACY_VERSION}" && \
    chmod +x /usr/local/bin/duplicacy

# --- Stage 2: the exporter image ---
FROM python:3.14-alpine

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# duplicacy CLI for the optional storage poller (POLLER_ENABLED=true)
COPY --from=duplicacy /usr/local/bin/duplicacy /usr/local/bin/duplicacy

COPY duplicacy_exporter.py .

EXPOSE 9750

ENTRYPOINT ["python", "-u", "duplicacy_exporter.py"]
