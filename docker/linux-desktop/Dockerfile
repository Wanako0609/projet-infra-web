# Image vérifiée : poste Linux graphique à la demande (KasmVNC sur :3000 + Wireshark)
FROM lscr.io/linuxserver/wireshark:latest

RUN apk add --no-cache \
      postgresql16-client \
      iputils \
      iproute2 \
      netcat-openbsd \
      tcpdump \
      curl

RUN mkdir -p /workspace
