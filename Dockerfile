FROM alpine:3.19
#
# Include dist
COPY . /opt/wordpot/
#
# Install packages
RUN apk -U --no-cache add \
		build-base \
		git \
		libcap \
		py3-click \
		py3-flask \
		py3-itsdangerous \
		py3-jinja2 \
		py3-markupsafe \
		py3-pip \
		py3-ua-parser \
		py3-werkzeug \
		py3-yaml \
		python3 \
		python3-dev && \
#	     
# Install wordpot from GitHub and setup
    mkdir -p /opt && \
    cd /opt/wordpot && \
    mkdir -p /opt/wordpot/logs /opt/wordpot/logs/payloads && \
    pip3 install --break-system-packages -r requirements.txt && \
    setcap cap_net_bind_service=+ep $(readlink -f $(type -P python3)) && \
#
# Setup user, groups and configs
    addgroup -g 2000 wordpot && \
    adduser -S -H -s /bin/ash -u 2000 -D -g 2000 wordpot && \
    chown wordpot:wordpot -R /opt/wordpot && \
#
# Clean up
    apk del --purge build-base \
		git \
		python3-dev && \
    rm -rf /root/* /var/cache/apk/* /opt/wordpot/.git
#
# Start wordpot
STOPSIGNAL SIGINT
USER wordpot:wordpot
WORKDIR /opt/wordpot
ENV WORDPOT_LOG_DIR=/opt/wordpot/logs \
    WORDPOT_PAYLOAD_DIR=/opt/wordpot/logs/payloads
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 CMD python3 healthcheck.py
CMD ["gunicorn", "--config", "gunicorn.conf.py", "wordpot:app"]
