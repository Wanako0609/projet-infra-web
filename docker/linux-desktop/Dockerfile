# Image vérifiée : bureau Linux Ubuntu XFCE (KasmVNC sur :3000) + apt + Wireshark + outils réseau
FROM lscr.io/linuxserver/webtop:ubuntu-xfce

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
 && echo "wireshark-common wireshark-common/install-setuid boolean true" | debconf-set-selections \
 && apt-get install -y --no-install-recommends \
      wireshark \
      sudo \
      postgresql-client \
      iputils-ping \
      iproute2 \
      iptables \
      netcat-openbsd \
      tcpdump \
      dnsutils \
      curl \
      python3 \
      nano \
 && rm -rf /var/lib/apt/lists/*

# Autorise l'utilisateur graphique (abc) à utiliser sudo et à capturer dans Wireshark
RUN mkdir -p /etc/sudoers.d \
 && echo "abc ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/abc \
 && chmod 0440 /etc/sudoers.d/abc \
 && (usermod -aG wireshark abc || true) \
 && mkdir -p /workspace
