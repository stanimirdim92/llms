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

# Create 'messages' file used from 'logrotate'
RUN touch /var/log/messages

# Copy 'logrotate' config file
COPY logrotate/nginx /etc/logrotate.d/

EXPOSE 80 443
