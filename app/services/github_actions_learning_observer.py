from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
import json
from typing import Any, Callable, Mapping, Sequence

from app.services.harness_learning_service import (
    HarnessEpisode,
    persist_episode,
    record_or_reuse_failure_memory,
)
from app.services.render_learning_profile_service import (
    BASELINE_RENDER_PROFILE_VERSION,
    RENDER_PROFILE_SKILL_ID,
)


CommandRunner = Callable[[Sequence[str]], str]
RENDER_CAPABILITY_ID = "production.render.execute"
RENDER_AGENT_ID = "audiovisual-worker"
RENDER_TASK_CLASS = "long-form-render"
RENDER_DOMAIN = "production-render"


def _parse_time(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("GitHub observation timestamp is required")
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _stable_id(prefix: str, payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}-{sha256(raw.encode('utf-8')).hexdigest()[:24]}"


@dataclass(frozen=True)
class GitHubRenderObservation:
    repository: str
    run_id: int
    job_id: int
    run_status: str
    run_conclusion: str | None
    job_status: str
    job_conclusion: str | None
    head_sha: str
    workflow_path: str
    run_started_at: str
    job_started_at: str
    job_completed_at: str
    duration_seconds: float
    job_name: str
    steps: tuple[dict[str, Any], ...]
    artifacts: tuple[dict[str, Any], ...]
    log_sha256: str
    orphan_processes: tuple[str, ...]
    timeout_minutes: int | None
    evidence_refs: tuple[str, ...]
    observed: bool = True

    @property
    def terminal(self) -> bool:
        return self.job_status == "completed" and bool(self.job_conclusion)

    @property
    def success(self) -> bool:
        return self.terminal and self.job_conclusion == "success"

    @property
    def skipped_stages(self) -> tuple[str, ...]:
        return tuple(
            str(step.get("name"))
            for step in self.steps
            if str(step.get("conclusion") or "").lower() == "skipped"
        )

    @property
    def cancelled_stages(self) -> tuple[str, ...]:
        return tuple(
            str(step.get("name"))
            for step in self.steps
            if str(step.get("conclusion") or "").lower() == "cancelled"
        )

    @property
    def failure_class(self) -> str | None:
        if self.success:
            return None
        if self.job_conclusion == "cancelled":
            if self.timeout_minutes is not None:
                boundary = max(0.0, self.timeout_minutes * 60.0 - 180.0)
                if self.duration_seconds >= boundary:
                    return "GITHUB_JOB_CANCELLED_AT_TIMEOUT_BOUNDARY"
            return "GITHUB_JOB_CANCELLED"
        if self.job_conclusion == "timed_out":
            return "GITHUB_JOB_TIMED_OUT"
        return f"GITHUB_JOB_{str(self.job_conclusion or 'UNKNOWN').upper()}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GitHubActionsLearningObserver:
    """Read canonical GitHub run/job/log/artifact state for Learning Plane use."""

    def __init__(self, command_runner: CommandRunner):
        if command_runner is None:
            raise ValueError("GitHub command runner is required")
        self.command_runner = command_runner

    def _json(self, repository: str, path: str) -> dict[str, Any]:
        output = self.command_runner([
            "gh", "api", f"repos/{repository}/{path}",
            "-H", "Accept: application/vnd.github+json",
        ])
        try:
            payload = json.loads(output)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"GitHub API returned invalid JSON for {path}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"GitHub API returned non-object for {path}")
        return payload

    def _job(self, repository: str, run_id: int, job_id: int | None) -> dict[str, Any]:
        if job_id is not None:
            return self._json(repository, f"actions/jobs/{job_id}")
        jobs = self._json(repository, f"actions/runs/{run_id}/jobs?per_page=100")
        candidates = [
            item for item in (jobs.get("jobs") or ())
            if isinstance(item, dict)
        ]
        exact = [item for item in candidates if item.get("name") == "audiovisual"]
        if len(exact) == 1:
            return exact[0]
        edit_plan = [
            item for item in candidates
            if any(
                isinstance(step, dict)
                and step.get("name") == "Execute authorized EditPlan"
                for step in (item.get("steps") or ())
            )
        ]
        if len(edit_plan) == 1:
            return edit_plan[0]
        raise RuntimeError("Unable to identify one canonical audiovisual GitHub job")

    def observe(
        self,
        *,
        repository: str,
        run_id: int,
        job_id: int | None = None,
        expected_head_sha: str | None = None,
        timeout_minutes: int | None = None,
    ) -> GitHubRenderObservation:
        if not repository or run_id <= 0:
            raise ValueError("repository and positive run_id are required")
        run = self._json(repository, f"actions/runs/{run_id}")
        job = self._job(repository, run_id, job_id)
        resolved_job_id = int(job["id"])

        run_url = str(job.get("run_url") or "")
        if run_url and not run_url.rstrip("/").endswith(f"/runs/{run_id}"):
            raise PermissionError("GitHub job does not belong to the observed run")
        head_sha = str(run.get("head_sha") or "")
        if expected_head_sha and head_sha != expected_head_sha:
            raise PermissionError("GitHub run commit does not match expected commit")

        started = str(job.get("started_at") or run.get("run_started_at") or "")
        completed = str(job.get("completed_at") or run.get("updated_at") or "")
        duration = (_parse_time(completed) - _parse_time(started)).total_seconds()
        if duration < 0:
            raise RuntimeError("GitHub job completion predates start")

        try:
            log_text = self.command_runner([
                "gh", "run", "view", str(run_id),
                "--repo", repository,
                "--job", str(resolved_job_id),
                "--log",
            ])
        except Exception:
            log_text = ""
        log_digest = sha256(log_text.encode("utf-8")).hexdigest()
        lowered = log_text.lower()
        orphan_processes = tuple(
            process for process in ("python", "ffmpeg")
            if f"terminate orphan process" in lowered and f"({process})" in lowered
        )

        artifact_payload = self._json(
            repository,
            f"actions/runs/{run_id}/artifacts?per_page=100",
        )
        artifacts = tuple(
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "size_in_bytes": item.get("size_in_bytes"),
                "expired": item.get("expired"),
                "digest": item.get("digest"),
            }
            for item in (artifact_payload.get("artifacts") or ())
            if isinstance(item, dict)
        )
        refs = (
            f"github:repo:{repository}",
            f"github:run:{run_id}",
            f"github:job:{resolved_job_id}",
            f"github:commit:{head_sha}",
            f"github:job-log-sha256:{log_digest}",
        )
        return GitHubRenderObservation(
            repository=repository,
            run_id=run_id,
            job_id=resolved_job_id,
            run_status=str(run.get("status") or ""),
            run_conclusion=(
                str(run["conclusion"]) if run.get("conclusion") is not None else None
            ),
            job_status=str(job.get("status") or ""),
            job_conclusion=(
                str(job["conclusion"]) if job.get("conclusion") is not None else None
            ),
            head_sha=head_sha,
            workflow_path=str(run.get("path") or ""),
            run_started_at=str(run.get("run_started_at") or ""),
            job_started_at=started,
            job_completed_at=completed,
            duration_seconds=duration,
            job_name=str(job.get("name") or ""),
            steps=tuple(
                dict(step) for step in (job.get("steps") or ())
                if isinstance(step, dict)
            ),
            artifacts=artifacts,
            log_sha256=log_digest,
            orphan_processes=orphan_processes,
            timeout_minutes=timeout_minutes,
            evidence_refs=refs,
        )


def _render_learning_binding(render_job: Mapping[str, Any]) -> dict[str, Any]:
    render = render_job.get("render")
    if not isinstance(render, Mapping):
        return {}
    binding = render.get("learning_profile")
    return dict(binding) if isinstance(binding, Mapping) else {}


def capture_observed_render_episode(
    *,
    render_job: Mapping[str, Any],
    observation: GitHubRenderObservation,
    routing_decision: Mapping[str, Any] | None = None,
    failure_class_override: str | None = None,
    failure_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if observation.observed is not True or not observation.terminal:
        raise ValueError("only a terminal canonical GitHub observation can create an Episode")
    render_job_id = render_job.get("render_job_id", render_job.get("id"))
    video_id = render_job.get("video_id")
    execution_id = str(render_job.get("execution_id") or "")
    goal_id = str(render_job.get("goal_id") or "")
    decision_id = str(render_job.get("brain_decision_id") or "")
    if not all((render_job_id, video_id, execution_id, goal_id, decision_id)):
        raise ValueError("RenderJob lacks canonical learning lineage")

    binding = _render_learning_binding(render_job)
    skill_version = str(
        binding.get("version") or BASELINE_RENDER_PROFILE_VERSION
    )
    status = (
        "COMPLETED" if observation.success
        else "CANCELLED" if observation.job_conclusion == "cancelled"
        else "FAILED"
    )
    effective_failure_class = None if observation.success else (
        str(failure_class_override).strip()
        if failure_class_override is not None and str(failure_class_override).strip()
        else observation.failure_class
    )
    effective_failure_metadata = dict(failure_metadata or {})
    artifact_refs = tuple(
        f"github:artifact:{item.get('id')}:{item.get('name')}"
        for item in observation.artifacts
        if item.get("id") is not None
    )
    output_refs = artifact_refs if observation.success else ()
    if observation.success and not output_refs:
        raise ValueError("successful render observation requires GitHub artifact evidence")

    evidence_refs = tuple(dict.fromkeys([
        *observation.evidence_refs,
        *artifact_refs,
        f"render-job:{render_job_id}",
        f"video:{video_id}",
        f"execution:{execution_id}",
    ]))
    episode_id = _stable_id("episode", {
        "render_job_id": render_job_id,
        "run_id": observation.run_id,
        "job_id": observation.job_id,
        "execution_id": execution_id,
    })
    failed_stage = next(iter(observation.cancelled_stages), None)
    qa = {
        "observed_from": "github-actions-job-steps",
        "unfinished_stages": list(observation.skipped_stages),
        "cancelled_stages": list(observation.cancelled_stages),
        "artifact_count": len(observation.artifacts),
    }
    episode = HarnessEpisode(
        episode_id=episode_id,
        goal_id=goal_id,
        decision_id=decision_id,
        execution_id=execution_id,
        task_id=f"render-job:{render_job_id}",
        agent_id=RENDER_AGENT_ID,
        capability_id=RENDER_CAPABILITY_ID,
        skill_id=RENDER_PROFILE_SKILL_ID,
        skill_version=skill_version,
        provider="github-actions",
        domain=RENDER_DOMAIN,
        task_class=RENDER_TASK_CLASS,
        input_refs=(f"render-job:{render_job_id}",),
        output_refs=output_refs,
        evidence_refs=evidence_refs,
        tool_calls=({
            "provider": "github-actions",
            "run_id": observation.run_id,
            "job_id": observation.job_id,
            "workflow": observation.workflow_path,
            "conclusion": observation.job_conclusion,
        },),
        routing_decision=dict(routing_decision or {}),
        started_at=observation.job_started_at,
        finished_at=observation.job_completed_at,
        duration_seconds=observation.duration_seconds,
        status=status,
        actual_outcome={
            "observed": True,
            "source": "github-actions-api",
            "run_status": observation.run_status,
            "run_conclusion": observation.run_conclusion,
            "job_status": observation.job_status,
            "job_conclusion": observation.job_conclusion,
            "failure_class": effective_failure_class,
            "failure_stage": failed_stage,
            "orphan_processes": list(observation.orphan_processes),
            **effective_failure_metadata,
        },
        outcome_evidence=evidence_refs,
        error=effective_failure_class,
        retry_count=0,
        human_intervention=False,
        qa_results=qa,
        latency_seconds=observation.duration_seconds,
        commit_ref=observation.head_sha,
        run_ref=f"github:run:{observation.run_id}",
        artifact_refs=artifact_refs,
        source_versions={
            "commit": observation.head_sha,
            f"skill:{RENDER_PROFILE_SKILL_ID}": skill_version,
        },
        lineage={
            "mission_id": render_job.get("mission_id"),
            "goal_id": goal_id,
            "content_item_id": render_job.get("content_item_id"),
            "video_id": video_id,
            "render_job_id": render_job_id,
            "execution_id": execution_id,
            "github_run_id": observation.run_id,
            "github_job_id": observation.job_id,
            "commit_sha": observation.head_sha,
            "capability_id": RENDER_CAPABILITY_ID,
            "skill_id": RENDER_PROFILE_SKILL_ID,
            "skill_version": skill_version,
            "routing_decision": dict(routing_decision or {}),
        },
    )
    persisted = persist_episode(episode)

    failure_memory = None
    if not observation.success:
        diagnostic_status = "OUTCOME_CONFIRMED_ROOT_CAUSE_OPEN"
        failure_memory = record_or_reuse_failure_memory(
            claim=(
                f"Observed RenderJob {render_job_id} ended with "
                f"{observation.job_conclusion} after {observation.duration_seconds:.3f}s "
                f"before post-render stages completed."
            ),
            domain=RENDER_DOMAIN,
            task_class=RENDER_TASK_CLASS,
            failure_pattern=str(effective_failure_class),
            source_episode_id=persisted["episode_id"],
            evidence_refs=evidence_refs,
            agent_id=RENDER_AGENT_ID,
            capability_id=RENDER_CAPABILITY_ID,
            skill_id=RENDER_PROFILE_SKILL_ID,
            skill_version=skill_version,
            source_versions={
                "commit": observation.head_sha,
                f"skill:{RENDER_PROFILE_SKILL_ID}": skill_version,
            },
            metadata={
                "failure_class": effective_failure_class,
                "affected_task_class": RENDER_TASK_CLASS,
                "affected_capability": RENDER_CAPABILITY_ID,
                "affected_skill": RENDER_PROFILE_SKILL_ID,
                "duration_seconds": observation.duration_seconds,
                "workflow_timeout_minutes": observation.timeout_minutes,
                "unfinished_stages": list(observation.skipped_stages),
                "cancelled_stages": list(observation.cancelled_stages),
                "orphan_processes": list(observation.orphan_processes),
                "known_execution_context": {
                    "render_job_id": render_job_id,
                    "video_id": video_id,
                    "execution_id": execution_id,
                    "run_id": observation.run_id,
                    "job_id": observation.job_id,
                    "commit_sha": observation.head_sha,
                },
                "diagnostic_status": diagnostic_status,
                "root_cause": effective_failure_metadata.get("root_cause"),
                "waste_cause": effective_failure_metadata.get("waste_cause"),
                "avoidable_render_waste_ms": effective_failure_metadata.get("avoidable_render_waste_ms"),
                "applicable_scope": "TASK_CLASS",
            },
            confidence=0.99,
        )
    return {
        "episode": persisted,
        "failure_memory": failure_memory,
        "observation": observation.to_dict(),
    }
