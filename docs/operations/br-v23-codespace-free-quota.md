# BR-no-GTA V23: Codespace 2-core, free-quota-first

This is a continuation of V23, not a replacement of the original Sprite.
Original Sprite, worktree and checkpoint v2 are **untouched**.

## Fixed identity

- Repository: `zenindiones-maker/BR-no-GTA`
- Codespace: `br-v23-recovery-gxp67g5g7wphwxjw`
- Branch: `work/br-v23-actions-contract-recovery-v1`
- Python runtime for bootstrap: 3.12
- The existing Codespace uses the GitHub default development image. **Do not
  add a custom devcontainer, rebuild it, run prebuilds or upgrade the machine**
  merely for this bootstrap. Default base-image storage is not charged by
  GitHub; additional project content and running compute still count.

## A15 Termux -> Codespace boundary

On the A15, use:

```sh
gh codespace view -c br-v23-recovery-gxp67g5g7wphwxjw \
  --json name,state,machineDisplayName,billableOwner,idleTimeoutMinutes,devcontainerPath
gh codespace ssh -c br-v23-recovery-gxp67g5g7wphwxjw
```

After connecting, the shell should show a Linux Codespace, with
`CODESPACES=true`, not the Android `~/GTA/BR` worktree. **Never run the
bootstrap in Termux.**

On the Codespace itself:

```sh
cd /workspaces/BR-no-GTA
test "${CODESPACES:-}" = "true" || { echo "NOT_INSIDE_CODESPACE"; exit 1; }
git status --short --branch
git rev-parse HEAD
```

Only if the intended recovery branch is checked out and `git status` is
clean, update it without discarding any work:

```sh
git pull --ff-only origin work/br-v23-actions-contract-recovery-v1
python3.12 scripts/workstations/br_v23_codespace_bootstrap.py --doctor
python3.12 scripts/workstations/br_v23_codespace_bootstrap.py --setup
```

The bootstrap creates or repairs `~/.cache/br-no-gta/v23-workstation/venv` **without pip or ensurepip** and a
sanitized receipt outside the repository. It installs **no large models**,
uses standard-library tests with network/HF disabled, and runs no background
daemon. It refuses the wrong Codespace, branch, git remote, dirty worktree,
insecure runtime or low storage headroom; all private inputs remain absent.

## Cost controls

A personal account has finite monthly Codespaces compute and storage included
in its GitHub plan. **The user has not confirmed remaining quota; zero extra
cost is not guaranteed.** Check GitHub Settings -> Billing and licensing ->
Budgets and alerts / Codespaces usage and keep any allowed paid overage at
zero. Do not add billing information or authorize overage for this task.

GitHub counts compute while the codespace is running. The CLI creation
requested a 10-minute idle timeout. Verify actual setting with
`gh codespace view` from Termux. Stop manually when idle:

```sh
gh codespace stop -c br-v23-recovery-gxp67g5g7wphwxjw
```

This stops compute but does not eliminate ongoing storage use for added files.

## Human voice boundaries

The existing 17+ V23 tests demonstrate contracts, **not** cloned-voice
quality, private reference availability or Qwen inference. The Codespace
bootstrap does not fetch or log owner voice samples, request secrets, run
Qwen weights, send Telegram messages, mutate the private ledger, fine-tune
models or attempt production. The current V23 branch is an isolated
reconstruction from versioned code, not proof that the original Sprite's
uncommitted worktree v2 was fully recovered.

For later legitimate model work, first verify runtime memory, storage,
consented sample provenance and remaining free compute. Run only a separately
approved, bounded diagnostic, without changing human approval gates.

## Ubuntu 24.04 ensurepip recovery (observed)

The initial Codespace run passed the identity doctor but failed while trying to
create a pip-enabled venv: `ensurepip is not available`. This is a packaging
difference in the base Ubuntu Python installation, **not** loss of the Codespace.

The versioned bootstrap was corrected to use `venv.EnvBuilder(with_pip=False,
clear=False)` on every setup invocation, even if the first attempt left a
partial `venv/bin/python`. It validates the interpreter is isolated and Python
3.12, and then executes the stdlib tests. It does **not** install
`python3.12-venv`, download `get-pip.py`, alter system packages, or delete
the partial virtual environment. It is safe to retry setup from the Codespace
after the fast-forward-only Git pull.

`gh codespace stop` should be issued **after exiting SSH, from the Android
Termux prompt**. Stopping the Codespace from its own SSH session closes that
connection; this is expected and does not delete stored workspace files.
