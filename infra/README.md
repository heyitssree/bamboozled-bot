# Bamboozled infrastructure (its own CDK app)

Four stacks, per environment name: `BamboozledData-<env>` (bucket, log group, image, image pointer; termination
protected), `BamboozledEdge-<env>` (second network interface, its own security group and Elastic IP, CloudFront),
`BamboozledHost-<env>` (a managed policy on the VM's role, the install document, an association by tag, the
`run_enabled` flag), `BamboozledMonitoring-<env>` (heartbeat alarm, e-mail topic, budget). Nothing is imported from
another project, and the only things touched outside these stacks are one managed policy attached to the VM's role and
an association that targets the tag.

## Use
1. `scripts/find-host.sh --tag-key K --tag-value V` (read-only; writes the git-ignored `infra/bamboozled.env`), then fill
   in the account, alert e-mail, application id and an origin-verify value (`openssl rand -hex 24`).
2. `scripts/put-secrets.sh prod` (silent prompts, SSM SecureString under `/bamboozled/prod/`).
3. `scripts/deploy.sh` (diff, confirm, deploy). The unit stays idle: `run_enabled` is `false`.
4. `scripts/enable.sh` when ready; `scripts/disable.sh` to stop. Both take effect at the unit's next restart.

Tests (no AWS needed): `python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt && .venv/bin/pytest tests`.

## The host contract (what Bamboozled assumes about the VM)
Exactly one running instance carrying the tag; its role name, VPC, subnet and zone (found by `find-host.sh`); Linux with
systemd, Docker, AWS CLI v2 and the SSM agent; instance metadata v2 with hop limit 2; room for a second container (400 MB,
3 GiB disk); an instance type that allows a second network interface. `install.sh` checks what it can and fails loudly,
changing nothing, if a command is missing.

## Failure modes
| What happens | Effect | Fix |
|---|---|---|
| Tag removed from the VM | the association stops applying; the container keeps running | put the tag back |
| VM replaced (same tag) | the association installs Bamboozled within 30 minutes; the database is restored from the bucket | none |
| Role or VPC recreated by the host's owner | the policy attachment or the subnet no longer match | re-run `find-host.sh`, redeploy |
| Instance type too small for a second interface | `install.sh` prints "could not attach" and the Activity is unreachable | use a larger type |
| Heartbeat alarm while `run_enabled=false` | the alarm fires (no heartbeat is expected) | expected; enable, or ignore until cutover |

## Not verifiable offline (the Phase 8 gate on the real VM)
CloudFront WebSocket upgrade through `/api/*`; reply routing from the second interface (`install.sh` sets a policy route,
check `ip route get 1.1.1.1` still uses the primary interface); the VPC resolves the Elastic IP's public DNS name (needs
DNS hostnames on); port 8480 unreachable via the primary address; memory, disk and CPU-credit measurements; the other
bot's container, logs and connectivity unchanged; `cdk destroy` leaves the VM as it was.
