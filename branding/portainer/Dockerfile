# Arbore Container - Portainer CE 2.21.5 customized branding
# Build: docker build -t arbore_container:1.0.0 .
# This image only injects a runtime branding script into /public/index.html
# It does NOT modify the Portainer binary or replace the logo

# ---- Stage 1: prepare modified /public ----
FROM alpine:3.20 AS builder

# Copy original /public from Portainer image
COPY --from=portainer/portainer-ce:2.21.5 /public /public

# Copy our injected branding script
COPY arbore-branding.js /public/arbore-branding.js

# Modify index.html:
#  1) replace <title>...</title> with "Arbore Container"
#  2) inject <script src="arbore-branding.js"></script> right before </head>
#     (use a relative path so it works under any base href)
RUN set -eu; \
    sed -i 's|<title>[^<]*</title>|<title>Arbore Container</title>|' /public/index.html; \
    sed -i 's|</head>|<script src="arbore-branding.js"></script></head>|' /public/index.html; \
    grep -q 'arbore-branding.js' /public/index.html || (echo "ERROR: branding script not injected" >&2; exit 1)

# ---- Stage 2: final image ----
FROM portainer/portainer-ce:2.21.5

LABEL maintainer="Arbore"
LABEL org.opencontainers.image.title="Arbore Container"
LABEL org.opencontainers.image.version="1.0.0"
LABEL org.opencontainers.image.description="Arbore Container based on Portainer CE 2.21.5 (offline branded build)"

# Replace /public with our branded version
COPY --from=builder /public /public
