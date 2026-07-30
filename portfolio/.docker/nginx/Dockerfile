FROM nginx:latest

RUN apt-get update &&  \
    apt-get upgrade -y && \
    apt-get install -y \
    logrotate

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
RUN sed -i "s/__REQUEST_TIMEOUT__/${REQUEST_TIMEOUT}/g" /etc/nginx/nginx.conf /etc/nginx/conf.d/default.conf && \
    sed -i "s/__MAX_UPLOAD_MB__/${MAX_UPLOAD_MB}/g" /etc/nginx/nginx.conf && \
    ! grep -rn '__[A-Z_]*__' /etc/nginx/nginx.conf /etc/nginx/conf.d/default.conf

# Create 'messages' file used from 'logrotate'
RUN touch /var/log/messages

# Copy 'logrotate' config file
COPY logrotate/nginx /etc/logrotate.d/

EXPOSE 80 443
