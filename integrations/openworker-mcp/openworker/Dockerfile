ARG OPENWORKER_BASE=milai-openworker-base:afa555cfccdb05c0-local-lock
FROM ${OPENWORKER_BASE}

LABEL io.milai.dg10.base-image-id="sha256:afa555cfccdb05c0e8a4a0b1ad84f364496d8721d45c9dbd796a7afbe5e7f05d" \
      io.milai.dg10.boundary="LOCAL_SYNTHETIC_ONLY_NO_REDISTRIBUTION" \
      io.milai.dg10.candidate="candidate.1"

COPY --chown=0:0 --chmod=0555 src/milai_openworker_mcp/relay.py /usr/local/bin/milai-mcp-relay
COPY --chown=0:0 --chmod=0444 openworker/opencode.json /openworker/image/config/opencode.json
COPY --chown=0:0 --chmod=0444 openworker/milai-task-metadata.js /openworker/image/plugins/milai-task-metadata.js

RUN install -d -o 0 -g 0 -m 0555 /run/milai-mcp \
    && test "$(sha256sum /usr/local/bin/milai-mcp-relay | cut -d' ' -f1)" != "" \
    && test "$(sha256sum /openworker/image/plugins/milai-task-metadata.js | cut -d' ' -f1)" != "" \
    && ! grep -E 'MILAI_AGENT_.*TOKEN|MILAI_BASE_URL|DATABASE_URL|POSTGRES' \
       /openworker/image/config/opencode.json
