# Pinned, like every other base image in this stack, and for a specific reason rather than
# tidiness: `dependabot.yml` tracks this build context on the stated assumption that it has
# "its own pinned base". A floating `:latest` gives Dependabot nothing to version-bump, so
# two builds months apart can pull different nginx majors -- in the one component that
# terminates TLS and parses every inbound request -- with no PR, no diff, and no review.
# Debian-based, not `-alpine`: the next line is `apt-get`, and alpine has `apk`.
FROM nginx:1.31

RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

# No logrotate, and it is worth saying why it is absent rather than leaving the next reader to
# re-add it. This image used to install it and copy a `/etc/logrotate.d/nginx` that rotated
# `/var/log/nginx/*.log` daily. Two measured facts made that both dead and dangerous:
#
#   docker run --rm nginx:1.29 ls -l /var/log/nginx
#     access.log -> /dev/stdout
#     error.log  -> /dev/stderr
#   docker run --rm nginx:1.29 sh -c 'command -v cron || command -v crond'
#     (absent)
#
# So there is no scheduler to invoke logrotate -- it could never have run -- and the files it
# was aimed at are the official image's symlinks to stdout/stderr. Rotation is Docker's job
# (`--log-opt max-size`/`max-file`, or whatever the host's log driver is configured with).
# Dangerous because the config carried `create 644 www-data root`: had a scheduler ever been
# added, the first rotation would have replaced those symlinks with ordinary files and silently
# cut nginx's logs off from `docker logs` -- an observability outage with no error anywhere.

COPY nginx.conf /etc/nginx/nginx.conf
COPY conf.d/default.conf /etc/nginx/conf.d/default.conf

# Bakes the api service's actual port into nginx.conf's upstream block at build time --
# see nginx.conf's own comment on __API_PORT__ for why this is a plain sed substitution
# rather than nginx's runtime envsubst-templates mechanism.
ARG API_PORT=8000
RUN sed -i "s/__API_PORT__/${API_PORT}/" /etc/nginx/nginx.conf

# Same one-source-of-truth mechanism, two more values that MUST match the app's:
#
#   REQUEST_TIMEOUT -- must be >= gunicorn's --timeout. If nginx gives up first the
#   client gets a 504 while the worker keeps burning CPU on a request nobody is waiting
#   for; if gunicorn gives up first the worker is SIGKILLed mid-parse and the client gets
#   a bare 502 with no indication that it was a timeout. Neither failure names itself,
#   which is why these are wired from one value instead of set independently.
#
#   MAX_UPLOAD_MB -- must match app/config.py's max_upload_size_mb. nginx enforces this
#   first (client_max_body_size), so if it is the smaller of the two the app's own limit
#   is dead code and raising MAX_UPLOAD_SIZE_MB appears to do nothing: every upload over
#   nginx's figure gets a 413 from nginx that looks exactly like the app's own 413.
ARG REQUEST_TIMEOUT=600
ARG MAX_UPLOAD_MB=20

# Edge rate limiting. These are NOT wired to the app's RATE_LIMIT_* settings and must not be:
# `app/rate_limit.py` is a per-API-key fairness budget, this is a per-IP flood shield, and setting
# them from one value would make the edge shed legitimate traffic the app would have allowed. See
# nginx.conf's own comment block.
#
# Defaults are deliberately an order of magnitude above the app's: general 20r/s + burst 40 is
# ~1200/min from one address against an app budget of 60/min per key, so several keys behind one
# corporate NAT are unaffected while a flood still stops here. Uploads are 30r/m + burst 10 against
# the app's 10/min per key, for the same reason.
#
# Raising these is safe; lowering them below the app's own budget is the failure mode -- the edge
# would 429 a caller who still had app budget left, and the app's `X-RateLimit-Remaining` would say
# so, which is unreproducible from the client's side.
ARG EDGE_RATE_GENERAL=20
ARG EDGE_BURST_GENERAL=40
ARG EDGE_RATE_UPLOAD=30
ARG EDGE_BURST_UPLOAD=10

RUN sed -i "s/__REQUEST_TIMEOUT__/${REQUEST_TIMEOUT}/g" /etc/nginx/nginx.conf /etc/nginx/conf.d/default.conf && \
    sed -i "s/__MAX_UPLOAD_MB__/${MAX_UPLOAD_MB}/g" /etc/nginx/nginx.conf && \
    sed -i "s/__EDGE_RATE_GENERAL__/${EDGE_RATE_GENERAL}/g;s/__EDGE_RATE_UPLOAD__/${EDGE_RATE_UPLOAD}/g" /etc/nginx/nginx.conf && \
    sed -i "s/__EDGE_BURST_GENERAL__/${EDGE_BURST_GENERAL}/g;s/__EDGE_BURST_UPLOAD__/${EDGE_BURST_UPLOAD}/g" /etc/nginx/conf.d/default.conf && \
    ! grep -rn '__[A-Z_]*__' /etc/nginx/nginx.conf /etc/nginx/conf.d/default.conf

# No `nginx -t` here, and it is worth saying why rather than leaving it to be re-added. It was
# added and immediately removed: the `upstream portfolio_api` block resolves `api:__API_PORT__` at
# config-parse time, and `api` is a compose service name with no DNS during `docker build`, so the
# test fails with `host not found in upstream "api:8000"` -- a build failure that names a
# non-problem. Validate the config against a resolvable stand-in instead:
#
#   docker run --rm -v "$PWD":/src:ro --add-host api:127.0.0.1 nginx:1.31 sh -c '...; nginx -t'
#
# and note that nginx aborts on the first `[emerg]`, so an unresolvable upstream means
# `conf.d/default.conf` is never parsed at all -- `include conf.d/*.conf` is the last line of
# nginx.conf. A "test failed" on the upstream is therefore not evidence that anything else is
# valid, which is exactly how a broken `limit_req` would have shipped.

EXPOSE 80 443
