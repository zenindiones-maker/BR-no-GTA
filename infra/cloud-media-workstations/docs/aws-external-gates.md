# AWS external gates runbook

This runbook deliberately separates authentication, verification, human policy, secrets, planning and apply. A failed phase is a causal blocker; do not skip forward.

## PHASE 1 — AUTH ONLY

Preferred path: AWS IAM Identity Center with a dedicated least-privilege permission set derived from `bootstrap/auth/provisioner-policy.json`.

Run:

```bash
scripts/bootstrap-aws-auth.sh
```

The script installs AWS CLI v2 into the Sprite user's home directory when missing, starts `aws configure sso`, and finishes with `aws sts get-caller-identity`.

Do not commit SSO cache files or credential material.

## PHASE 2 — VERIFY

The first AWS runtime proof is always:

```bash
aws sts get-caller-identity --profile cloud-media-workstations --region sa-east-1
```

Expected: the intended account and temporary SSO/role identity. If this fails, status remains `BLOCKED_AWS_AUTH`.

Do not query quota, pricing, capacity or run OpenTofu apply before STS passes.

## PHASE 3 — HUMAN POLICY INPUT

The human must provide:

```bash
export MONTHLY_BUDGET_USD='<human-approved-value>'
export BUDGET_EMAIL='<human-approved-address>'
```

No default or inferred budget is permitted.

Configure the remote S3 state backend first. The repository uses S3 native state locking with `use_lockfile = true`, bucket versioning and server-side encryption. Hazewave and BR-no-GTA use distinct object keys.

Set:

```bash
export TF_BACKEND_CONFIG='/absolute/path/to/backend.hcl'
```

## PHASE 4 — SECRET BOOTSTRAP

Create independent Tailscale keys and store them as SSM Parameter Store SecureString values:

```text
/cloud-media-workstations/hazewave/tailscale-auth-key
/cloud-media-workstations/br-no-gta/tailscale-auth-key
```

Never use the same key for both projects and never commit either value.

Verify only metadata/type, not plaintext secret contents:

```bash
scripts/verify-external-gates.sh
```

## PHASE 5 — PLAN ONLY

After STS and all external gates pass:

1. query EC2 Service Quotas in `sa-east-1`;
2. query AWS Price List API;
3. check instance type offerings;
4. generate CostEvidence;
5. run `tofu init`;
6. run `tofu plan`;
7. review the plan for tag scope, IAM scope, budget action and final stopped state.

An AZ offering is not proof of allocatable capacity. Real capacity remains unproven until AWS accepts the launch.

## PHASE 6 — APPLY

Do not run PHASE 6 until every prior gate is PASS.

Provision only through the governed script:

```bash
scripts/provision.sh hazewave
scripts/provision.sh br-no-gta
```

Each successful provisioning path must end in `STOPPED`.

Never replace StopInstances with termination merely to reduce cost.

## Failure semantics

Use explicit blockers:

- `BLOCKED_AWS_AUTH`
- `BLOCKED_GPU_QUOTA`
- `BLOCKED_CAPACITY_UNPROVEN`
- `MONTHLY_BUDGET_USD_UNSET`
- `BUDGET_EMAIL_UNSET`
- `TF_BACKEND_CONFIG_UNSET`
- `BLOCKED_TAILSCALE_SECRET`

A code/test PASS is not a runtime infrastructure PASS.
