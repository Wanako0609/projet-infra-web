# Image vérifiée : poste Linux Debian avec apt, outils réseau, système, Python et client PostgreSQL
FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
      bash \
      sudo \
      iproute2 \
      iputils-ping \
      iptables \
      tcpdump \
      curl \
      wget \
      dnsutils \
      netcat-openbsd \
      openssh-client \
      postgresql-client \
      python3 \
      nano \
      vim \
      ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /workspace
WORKDIR /workspace

CMD ["sleep", "infinity"]
