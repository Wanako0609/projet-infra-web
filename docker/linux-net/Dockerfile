# Image vérifiée : poste Linux minimal avec outils réseau et client PostgreSQL
FROM alpine:3.20

RUN apk add --no-cache \
      bash \
      iproute2 \
      iputils \
      tcpdump \
      curl \
      bind-tools \
      netcat-openbsd \
      postgresql16-client \
      nano

RUN mkdir -p /workspace
WORKDIR /workspace

CMD ["sleep", "infinity"]
