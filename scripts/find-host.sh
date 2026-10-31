#!/bin/bash
# scripts/find-host.sh --tag-key <key> --tag-value <value> [--region ap-southeast-2]
# Discovers everything the CDK app needs about the shared VM by TAG, so no other project's code or outputs are read.
# Read-only against AWS. Writes infra/bamboozled.env (git-ignored).
set -euo pipefail
KEY=""; VALUE=""; REGION="${AWS_REGION:-ap-southeast-2}"
while [ $# -gt 0 ]; do
  case "$1" in
    --tag-key) KEY="$2"; shift 2;;
    --tag-value) VALUE="$2"; shift 2;;
    --region) REGION="$2"; shift 2;;
    *) echo "unknown argument: $1"; exit 2;;
  esac
done
[ -n "$KEY" ] && [ -n "$VALUE" ] || { echo "usage: $0 --tag-key K --tag-value V [--region R]"; exit 2; }
export AWS_DEFAULT_REGION="$REGION"
IID=$(aws ec2 describe-instances --filters "Name=tag:$KEY,Values=$VALUE" "Name=instance-state-name,Values=running" \
      --query 'Reservations[].Instances[].InstanceId' --output text)
[ "$(wc -w <<<"$IID" | tr -d ' ')" = "1" ] || { echo "expected exactly one running instance with that tag, found: '$IID'"; exit 1; }
read -r SUBNET VPC AZ PROFILE < <(aws ec2 describe-instances --instance-ids "$IID" \
   --query 'Reservations[0].Instances[0].[SubnetId,VpcId,Placement.AvailabilityZone,IamInstanceProfile.Arn]' --output text)
ROLE=$(aws iam get-instance-profile --instance-profile-name "${PROFILE##*/}" --query 'InstanceProfile.Roles[0].RoleName' --output text)
PL=$(aws ec2 describe-managed-prefix-lists --filters Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin_facing \
     --query 'PrefixLists[0].PrefixListId' --output text)
ROOT="$(cd "$(dirname "$0")" && cd .. && pwd)"
OUT="$ROOT/infra/bamboozled.env"
[ ! -e "$OUT" ] || { echo "$OUT already exists; move it away first (it may hold your other settings)"; exit 1; }
cat > "$OUT" <<ENV
BAMBOOZLED_ENV_NAME=prod
CDK_DEFAULT_REGION=$REGION
BAMBOOZLED_PLATFORM=linux/arm64
BAMBOOZLED_BUDGET_USD=10
BAMBOOZLED_HOST_TAG_KEY=$KEY
BAMBOOZLED_HOST_TAG_VALUE=$VALUE
BAMBOOZLED_HOST_ROLE_NAME=$ROLE
BAMBOOZLED_HOST_VPC_ID=$VPC
BAMBOOZLED_HOST_SUBNET_ID=$SUBNET
BAMBOOZLED_HOST_AZ=$AZ
BAMBOOZLED_CLOUDFRONT_PREFIX_LIST_ID=$PL
ENV
echo "written $OUT (git-ignored). Add: CDK_DEFAULT_ACCOUNT, BAMBOOZLED_ALERT_EMAIL, BAMBOOZLED_DISCORD_APP_ID, BAMBOOZLED_ORIGIN_VERIFY"
echo "Check the platform: linux/arm64 for t4g (Graviton) hosts, linux/amd64 otherwise."
