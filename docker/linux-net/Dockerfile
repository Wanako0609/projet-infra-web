# Image vérifiée : poste Linux complet (outils réseau, système, Python et client PostgreSQL)
FROM alpine:3.20

RUN apk add --no-cache \
      bash \
      sudo \
      shadow \
      iproute2 \
      iputils \
      iptables \
      tcpdump \
      curl \
      wget \
      bind-tools \
      netcat-openbsd \
      openssh-client \
      postgresql16-client \
      python3 \
      nano \
      vim

RUN mkdir -p /workspace
WORKDIR /workspace

CMD ["sleep", "infinity"]
