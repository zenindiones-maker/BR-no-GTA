# Cloud Media Workstations

Infrastructure-as-code and governed workstation runtime for two independent persistent AWS media workstations:

- **Hazewave** — `g6f.2xlarge`, audio/CPU-first, 80 GiB root + 250 GiB data, `/srv/hazewave`.
- **BR-no-GTA** — `g6.2xlarge`, full L4 video/media workstation, 100 GiB root + 500 GiB data, `/srv/br-no-gta`.

Region is fixed to `sa-east-1`. Interactive v1 uses On-Demand only.

## Safety state

Chargeable deployment defaults to disabled. Live provisioning requires:

1. AWS authorization that passes `scripts/aws_preflight.py`;
2. a human-provided `MONTHLY_BUDGET_USD`;
3. a project-scoped Tailscale SecureString already present in SSM;
4. a pinned AWS GRID driver S3 URI and SHA256 discovered from the real AWS account/runtime;
5. explicit `deploy_resources=true` through `scripts/provision.sh`.

Normal final instance state is **STOPPED**. No live AWS resource has been created by the safe-build phase.

## Validation

Run:

```bash
scripts/verify-safe-build
```

The gate covers pytest contracts, secret scanning, lifecycle semantics, isolation, backup/state, GPU/NVENC failure semantics, REAPER receipts and acceptance orchestration. OpenTofu/Ansible validation is additionally run by the build runbook before provisioning.

## Runtime flow

```
PROJECT HARNESS
  -> authorized MediaExecutionRequest
  -> workstation executor
  -> REAPER / FFmpeg / media tools
  -> typed MediaExecutionResult
  -> durable project state
```

The workstation is an executor, never a control plane.
