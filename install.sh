#!/bin/bash
# ================================================================
# SMS IoT Listener Services — Installer v1.1
# ================================================================

# Auto re-run with sudo if docker not accessible
if ! docker info >/dev/null 2>&1; then
    if [ "$EUID" -ne 0 ]; then
        echo "  Requesting sudo for Docker access..."
        exec sudo -H bash "$0" "$@"
    fi
fi

cd $HOME

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${BLUE}  ▸${NC} $1"; }
success() { echo -e "${GREEN}  ✓${NC} $1"; }
warn()    { echo -e "${YELLOW}  ⚠${NC} $1"; }
error()   { echo -e "${RED}  ✗ ERROR:${NC} $1"; exit 1; }
step()    { echo -e "\n${CYAN}${BOLD}══ $1 ══${NC}"; }

clear
echo -e "${CYAN}${BOLD}"
echo "  ╔═══════════════════════════════════════════════════╗"
echo "  ║      SMS IoT Listener Services Installer         ║"
echo "  ║      PTZ • Uploader • PTT (Push-to-Talk)         ║"
echo "  ╚═══════════════════════════════════════════════════╝"
echo -e "${NC}"

# Auto-detect IP
DEVICE_IP=$(ip route get 8.8.8.8 2>/dev/null | grep -oP 'src \K\S+' | head -1)
[ -z "$DEVICE_IP" ] && DEVICE_IP=$(hostname -I | awk '{print $1}')

# Use home of the real user (not root)
REAL_USER="${SUDO_USER:-$USER}"
REAL_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)
INSTALL_DIR="${REAL_HOME}/sms-listener"
MAIN_DIR="${REAL_HOME}/sms-iot"
REPO_URL="https://github.com/adnankhanodoo/sms-listener.git"

echo -e "  ${BOLD}Device IP:${NC}   ${GREEN}$DEVICE_IP${NC}"
echo -e "  ${BOLD}Install dir:${NC} $INSTALL_DIR"
echo ""

# Check main stack
if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -q smarthome-manager; then
    warn "Main SMS IoT stack not detected!"
    warn "Install it first: curl -fsSL https://raw.githubusercontent.com/adnankhanodoo/sms-iot-deploy/main/deploy.sh -o /tmp/deploy.sh && sudo bash /tmp/deploy.sh"
    echo ""
    read -r -p "  Continue anyway? [y/n]: " FORCE
    [[ "$FORCE" != "y" ]] && exit 0
fi

# Menu
echo -e "  ${BOLD}Which services to install?${NC}"
echo ""
echo -e "  ${CYAN}1)${NC} All 3 services  (PTZ + Uploader + PTT)"
echo -e "  ${CYAN}2)${NC} PTZ Service only  (camera pan/tilt/zoom)"
echo -e "  ${CYAN}3)${NC} Uploader only  (Frigate clip downloader)"
echo -e "  ${CYAN}4)${NC} PTT Server only  (push-to-talk audio)"
echo -e "  ${CYAN}5)${NC} Update existing installation"
echo ""
read -r -p "  Enter choice [1-5]: " CHOICE
echo ""

case $CHOICE in
    1) INSTALL_PTZ=y; INSTALL_UPLOADER=y; INSTALL_PTT=y ;;
    2) INSTALL_PTZ=y; INSTALL_UPLOADER=n; INSTALL_PTT=n ;;
    3) INSTALL_PTZ=n; INSTALL_UPLOADER=y; INSTALL_PTT=n ;;
    4) INSTALL_PTZ=n; INSTALL_UPLOADER=n; INSTALL_PTT=y ;;
    5) INSTALL_PTZ=y; INSTALL_UPLOADER=y; INSTALL_PTT=y ;;
    *) error "Invalid choice" ;;
esac

echo -e "  ${BOLD}Summary:${NC}"
[ "$INSTALL_PTZ" = "y" ]      && echo -e "    ${GREEN}✓${NC} PTZ Service  → https://$DEVICE_IP:5002"
[ "$INSTALL_UPLOADER" = "y" ] && echo -e "    ${GREEN}✓${NC} Uploader     → http://$DEVICE_IP:5001"
[ "$INSTALL_PTT" = "y" ]      && echo -e "    ${GREEN}✓${NC} PTT Server   → https://$DEVICE_IP:3000"
echo ""
read -r -p "  Proceed? [y/n]: " CONFIRM
[[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]] && echo "  Cancelled." && exit 0

# ── Step 1: Clone/Update ─────────────────────────────────
step "Step 1/4: Setting Up Files"

if [ -d "$INSTALL_DIR/.git" ]; then
    info "Updating from GitHub..."
    git -C $INSTALL_DIR fetch origin 2>/dev/null
    git -C $INSTALL_DIR reset --hard origin/main 2>/dev/null
    success "Files updated"
else
    info "Downloading from GitHub..."
    git clone $REPO_URL $INSTALL_DIR
    chown -R $REAL_USER:$REAL_USER $INSTALL_DIR 2>/dev/null || true
    success "Files downloaded to $INSTALL_DIR"
fi
cd $INSTALL_DIR

# ── Step 2: SSL Certs ────────────────────────────────────
step "Step 2/4: Setting Up SSL Certificates"
mkdir -p ssl-certs

if [ -f "$MAIN_DIR/ssl/frigate.crt" ]; then
    cp $MAIN_DIR/ssl/frigate.crt ssl-certs/fullchain.pem
    cp $MAIN_DIR/ssl/frigate.key ssl-certs/privkey.pem
    success "SSL certs copied from main installation"
elif [ ! -f ssl-certs/fullchain.pem ]; then
    info "Generating SSL certificate..."
    openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
        -keyout ssl-certs/privkey.pem -out ssl-certs/fullchain.pem \
        -subj "/CN=$DEVICE_IP" 2>/dev/null
    success "SSL certificate generated"
else
    success "SSL certificates already exist"
fi

# ── Step 3: Configure ────────────────────────────────────
step "Step 3/4: Configuring Services"
success "Services configured for $DEVICE_IP"

# ── Step 4: Build & Start ────────────────────────────────
step "Step 4/4: Building & Starting Services"

# Ensure network exists - but only create if main stack already created it
NETWORK="sms-iot_default"
if ! docker network ls --format "{{.Name}}" | grep -q "^${NETWORK}$"; then
    warn "Main stack network not found — start main stack first"
    warn "Run: curl -fsSL https://raw.githubusercontent.com/adnankhanodoo/sms-iot-deploy/main/deploy.sh -o /tmp/deploy.sh && sudo bash /tmp/deploy.sh"
    read -r -p "  Continue anyway? [y/n]: " NET_CONFIRM
    [[ "$NET_CONFIRM" != "y" ]] && exit 1
    docker network create $NETWORK 2>/dev/null || true
fi

# Build services
SERVICES=""
[ "$INSTALL_PTZ" = "y" ]      && SERVICES="$SERVICES ptz-service"
[ "$INSTALL_UPLOADER" = "y" ] && SERVICES="$SERVICES uploader-service"
[ "$INSTALL_PTT" = "y" ]      && SERVICES="$SERVICES ptt-server"

info "Building Docker images (first time takes 2-5 min)..."
for svc in $SERVICES; do
    echo -e "  ${CYAN}── Building: $svc ──${NC}"
    cd $INSTALL_DIR && docker compose build $svc
    echo ""
done

info "Starting services..."
cd $INSTALL_DIR && docker compose up -d $SERVICES 2>&1 | grep -v "^$"
success "All services started"

sleep 5

# ── Summary ──────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}"
echo "  ╔═══════════════════════════════════════════════════╗"
echo "  ║        Listener Services Ready! 🎉               ║"
echo "  ╚═══════════════════════════════════════════════════╝"
echo -e "${NC}"
echo -e "  ${BOLD}Service URLs:${NC}"
echo ""

[ "$INSTALL_PTZ" = "y" ] && echo -e "  ${CYAN}PTZ${NC}      🎥  https://$DEVICE_IP:5002/<cam>/ptz/MOVE_RIGHT"
[ "$INSTALL_UPLOADER" = "y" ] && echo -e "  ${CYAN}Uploader${NC} 📥  http://$DEVICE_IP:5001/download_clip"
[ "$INSTALL_PTT" = "y" ] && echo -e "  ${CYAN}PTT${NC}      🎙️  https://$DEVICE_IP:3000"
echo ""
echo -e "  ${BOLD}Run again:${NC}"
echo -e "    curl -fsSL https://raw.githubusercontent.com/adnankhanodoo/sms-listener/main/install.sh -o /tmp/sl.sh && sudo bash /tmp/sl.sh"
echo ""
