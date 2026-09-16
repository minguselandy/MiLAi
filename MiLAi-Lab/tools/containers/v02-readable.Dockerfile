FROM pgvector/pgvector@sha256:00ba258a66dac104fd5171074a0084462a64a1369d8513f3d0a634e2f24d15bc
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 jq \
    && ln -s /usr/bin/python3 /usr/local/bin/python \
    && rm -rf /var/lib/apt/lists/*
COPY v02_read_file.py /usr/local/bin/milai-read
RUN chmod 0555 /usr/local/bin/milai-read
