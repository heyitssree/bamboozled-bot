#!/bin/bash
# install.sh - runs as root through SSM State Manager every 30 minutes. Idempotent: a second run changes nothing.
# Arguments: prefix env region port logGroup bucket eniParam. BAMBOOZLED_ROOT (tests only) prefixes every path it writes.
set -euo pipefail
PREFIX="$1"; ENVN="$2"; REGION="$3"; PORT="$4"; LOGG="$5"; BUCKET="$6"; ENIP="$7"
R="${BAMBOOZLED_ROOT:-}"
export AWS_DEFAULT_REGION="$REGION"
ssm() { aws ssm get-parameter --name "$1" --query Parameter.Value --output text 2>/dev/null || echo "${2:-}"; }
write_if_changed() {   # write_if_changed <path> [mode]; content on stdin; sets CHANGED=1 when the file differs
  local tmp; tmp="$(mktemp)"; cat > "$tmp"
  if ! cmp -s "$tmp" "$1" 2>/dev/null; then install -m "${2:-644}" "$tmp" "$1"; CHANGED=1; fi
  rm -f "$tmp"
}

# 1. Host contract: fail loudly and change nothing if a requirement is missing.
for need in docker aws systemctl curl; do command -v "$need" >/dev/null || { echo "host lacks $need"; exit 1; }; done

TOKEN=$(curl -sX PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 60')
IID=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/instance-id)

# 2. Dedicated ingress interface: attach our own ENI (own security group, own address) if this host does not have it yet.
ENI=$(ssm "$ENIP")
ATTACHED=$(aws ec2 describe-network-interfaces --network-interface-ids "$ENI" --query 'NetworkInterfaces[0].Attachment.InstanceId' --output text || true)
if [ "$ATTACHED" != "$IID" ]; then
  aws ec2 attach-network-interface --network-interface-id "$ENI" --instance-id "$IID" --device-index 1 || echo "could not attach $ENI (instance type too small for a second interface?)"
fi
# Replies to traffic that arrived on the second interface must leave by it, or the address translation drops them.
# The default route (and every other application) keeps using the primary interface.
if command -v ip >/dev/null && [ "$(aws ec2 describe-network-interfaces --network-interface-ids "$ENI" --query 'NetworkInterfaces[0].Attachment.InstanceId' --output text || true)" = "$IID" ]; then
  read -r ENI_IP MAC < <(aws ec2 describe-network-interfaces --network-interface-ids "$ENI" --query 'NetworkInterfaces[0].[PrivateIpAddress,MacAddress]' --output text)
  DEV=$(ip -o link | awk -v m="$MAC" 'tolower($0) ~ tolower(m) {sub(":","",$2); print $2}' | head -1)
  CIDR=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" "http://169.254.169.254/latest/meta-data/network/interfaces/macs/$MAC/subnet-ipv4-cidr-block" || true)
  if [ -n "$DEV" ] && [ -n "$CIDR" ]; then
    GW=$(awk -F'[./]' '{printf "%s.%s.%s.%d", $1,$2,$3,$4+1}' <<<"$CIDR")
    ip addr show dev "$DEV" | grep -q "$ENI_IP" || ip addr add "$ENI_IP/${CIDR#*/}" dev "$DEV" || true
    ip link set "$DEV" up || true
    ip route replace default via "$GW" dev "$DEV" table 100 || true
    ip rule | grep -q "from $ENI_IP lookup 100" || ip rule add from "$ENI_IP" table 100 || true
  else
    echo "second interface is attached but not visible yet; the next run will route it"
  fi
fi

# 3. Files: own directory, own unit, own data directory. Nothing shared with other applications on the host.
CHANGED=0
install -d "$R/opt/bamboozled" "$R/var/lib/bamboozled" "$R/etc/systemd/system"
chown 10002:10002 "$R/var/lib/bamboozled" 2>/dev/null || true
write_if_changed "$R/opt/bamboozled/env" 600 <<ENV
BAMBOOZLED_ENV=$ENVN
BAMBOOZLED_SSM_PREFIX=$PREFIX
BAMBOOZLED_BUCKET=$BUCKET
AWS_REGION=$REGION
PORT=$PORT
LOG_GROUP=$LOGG
LITESTREAM_ENABLED=1
ENV
write_if_changed "$R/opt/bamboozled/run.sh" 755 <<'RUN'
@@RUN_SH@@
RUN
write_if_changed "$R/etc/systemd/system/bamboozled.service" 644 <<'UNIT'
@@UNIT@@
UNIT
if [ "$CHANGED" = 1 ]; then systemctl daemon-reload; fi
systemctl enable bamboozled >/dev/null 2>&1 || true

# 4. Image: pull and restart only when the SSM image_uri changed (or the unit is not active).
IMAGE=$(ssm "$PREFIX/image_uri")
OLD=$(cat "$R/opt/bamboozled/image" 2>/dev/null || true)
if [ -n "$IMAGE" ] && { [ "$IMAGE" != "$OLD" ] || ! systemctl is-active --quiet bamboozled; }; then
  aws ecr get-login-password | docker login --username AWS --password-stdin "${IMAGE%%/*}"
  docker pull "$IMAGE"
  echo "$IMAGE" > "$R/opt/bamboozled/image"
  systemctl restart bamboozled
  [ -z "$OLD" ] || [ "$OLD" = "$IMAGE" ] || docker rmi "$OLD" >/dev/null 2>&1 || true   # only the previous Bamboozled image, by id
elif [ "$CHANGED" = 1 ] && systemctl is-active --quiet bamboozled; then
  systemctl restart bamboozled
fi
