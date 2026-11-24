# Image vérifiée : vrai bureau Linux XFCE (KasmVNC sur :3000) + Wireshark + outils réseau/système
FROM lscr.io/linuxserver/webtop:alpine-xfce

RUN apk add --no-cache \
      wireshark \
      sudo \
      postgresql16-client \
      iputils \
      iproute2 \
      iptables \
      netcat-openbsd \
      tcpdump \
      bind-tools \
      curl \
      python3 \
      nano

# Autorise l'utilisateur graphique (abc) à utiliser sudo dans le conteneur isolé
RUN mkdir -p /etc/sudoers.d \
 && echo "abc ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/abc \
 && chmod 0440 /etc/sudoers.d/abc \
 && mkdir -p /workspace
