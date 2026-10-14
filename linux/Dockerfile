# Sceneuse Linux sandbox: Xvfb + AT-SPI + GTK fixture + sceneused.
# Capture/PipeWire is out of scope here; screen_recording stays false.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:99 \
    XDG_RUNTIME_DIR=/tmp/runtime \
    SCENEUSE_SOCK=/tmp/runtime/sceneuse.sock \
    PYTHONUNBUFFERED=1 \
    GTK_MODULES=gail:atk-bridge \
    GNOME_ACCESSIBILITY=1 \
    QT_ACCESSIBILITY=1 \
    NO_AT_BRIDGE=0

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-gi \
    gir1.2-atspi-2.0 \
    gir1.2-gtk-3.0 \
    at-spi2-core \
    dbus-x11 \
    xvfb \
    xdotool \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY linux/entrypoint.sh /usr/local/bin/sceneuse-linux-entry
RUN chmod +x /usr/local/bin/sceneuse-linux-entry

# Repo is bind-mounted at runtime for fast iteration.
VOLUME ["/app"]
EXPOSE 8765

ENTRYPOINT ["/usr/local/bin/sceneuse-linux-entry"]
CMD ["daemon"]
