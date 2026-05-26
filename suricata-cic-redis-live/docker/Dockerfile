FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    iproute2 \
    jq \
    libcap-ng0 \
    libevent-2.1-7 \
    libevent-pthreads-2.1-7 \
    libhiredis0.14 \
    libjansson4 \
    liblz4-1 \
    libmagic1 \
    libnet1 \
    libpcap0.8 \
    libpcre2-8-0 \
    libyaml-0-2 \
    python3 \
    redis-tools \
    zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY runtime/bin/suricata /opt/suricata-cic/bin/suricata
COPY runtime/etc/suricata /etc/suricata
COPY runtime/rules /var/lib/suricata/rules
COPY docker/entrypoint.sh /usr/local/bin/suricata-cic-entrypoint

RUN chmod +x /opt/suricata-cic/bin/suricata /usr/local/bin/suricata-cic-entrypoint \
    && mkdir -p /var/log/suricata /var/run/suricata

ENTRYPOINT ["/usr/local/bin/suricata-cic-entrypoint"]
