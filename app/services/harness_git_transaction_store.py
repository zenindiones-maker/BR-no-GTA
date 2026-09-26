from __future__ import annotations

from dataclasses import dataclass
import base64
import json
import os
from typing import Any
from urllib import error, parse, request


class CasConflict(RuntimeError):
    pass

class GitApiError(RuntimeError):
    def __init__(self,status:int|None,body:str,method:str,path:str,kind:str="HTTP")->None:
        self.status=status;self.body=body;self.method=method;self.path=path;self.kind=kind
        super().__init__(f"GITHUB_API_{kind}:{status}:{method}:{path}:{body[:500]}")

class RefUpdateOutcomeUnknown(RuntimeError):
    pass

class GitRefUpdateRejected(RuntimeError):
    def __init__(self,status:int,body:str,expected_head_sha:str,observed_head_sha:str)->None:
        self.status=status;self.body=body;self.expected_head_sha=expected_head_sha;self.observed_head_sha=observed_head_sha
        super().__init__(f"GITHUB_REF_UPDATE_VALIDATION_FAILED:{status}:expected={expected_head_sha}:observed={observed_head_sha}:{body[:300]}")


@dataclass(frozen=True)
class GitSnapshot:
    head_sha: str
    tree_sha: str
    mission_head: dict[str, Any] | None

    def read_json(self, store: "GitHubGitTransactionStore", path: str) -> dict[str, Any] | None:
        return store.read_json(path, self.head_sha)


class GitHubGitTransactionStore:
    """Git object database backed CAS store.

    A transaction builds immutable blobs/tree/commit against one observed branch
    head and publishes it with a non-forced ref update. The commit parent is the
    observed head, so a concurrent winner makes the losing update non-fast-forward.
    """

    def __init__(
        self,
        *,
        repository: str,
        token: str | None = None,
        branch: str = "harness-state",
        api_url: str = "https://api.github.com",
    ) -> None:
        self.repository = repository
        self.branch = branch
        self.api_url = api_url.rstrip("/")
        self.token = token or os.environ.get("GITHUB_TOKEN", "")
        if not self.token:
            raise ValueError("GITHUB_TOKEN_REQUIRED")

    def _api(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
        req = request.Request(
            f"{self.api_url}/repos/{self.repository}{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        try:
            with request.urlopen(req, timeout=30) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except error.HTTPError as exc:
            raw=exc.read().decode("utf-8","replace")
            raise GitApiError(exc.code,raw,method,path) from exc
        except (error.URLError,TimeoutError,ConnectionError) as exc:
            raise GitApiError(None,repr(exc),method,path,"TRANSPORT") from exc

    def _ref(self) -> dict[str, Any]:
        encoded = parse.quote(f"heads/{self.branch}", safe="/")
        return self._api("GET", f"/git/ref/{encoded}")

    def _commit(self, sha: str) -> dict[str, Any]:
        return self._api("GET", f"/git/commits/{sha}")

    def _blob_json(self, path: str, ref: str) -> dict[str, Any] | None:
        encoded = parse.quote(path, safe="/")
        try:
            row = self._api("GET", f"/contents/{encoded}?ref={parse.quote(ref, safe='')}")
        except GitApiError as exc:
            if exc.status==404:return None
            raise
        content = base64.b64decode(str(row["content"]).replace("\n", ""))
        return json.loads(content)

    def read_json(self, path: str, ref: str) -> dict[str, Any] | None:
        return self._blob_json(path, ref)

    def snapshot(self, mission_id: str) -> GitSnapshot:
        ref = self._ref()
        head_sha = str(ref["object"]["sha"])
        commit = self._commit(head_sha)
        return GitSnapshot(
            head_sha=head_sha,
            tree_sha=str(commit["tree"]["sha"]),
            mission_head=self._blob_json(f"missions/{mission_id}/head.json", head_sha),
        )

    def create_blob(self, payload: Any) -> tuple[str, bytes]:
        canonical = canonical_bytes(payload)
        row = self._api(
            "POST",
            "/git/blobs",
            {"content": canonical.decode("utf-8"), "encoding": "utf-8"},
        )
        return str(row["sha"]), canonical

    def transact(
        self,
        *,
        mission_id: str,
        expected_head_sha: str,
        expected_state_version: int | None,
        mission_head: dict[str, Any],
        immutable_objects: dict[str, dict[str, Any]] | None = None,
    ) -> str:
        current = self.snapshot(mission_id)
        if current.head_sha != expected_head_sha:
            raise CasConflict("CAS_CONFLICT:STATE_REF_MOVED")
        observed_version = (
            None if current.mission_head is None
            else int(current.mission_head.get("state_version", -1))
        )
        if observed_version != expected_state_version:
            raise CasConflict(
                f"CAS_CONFLICT:STATE_VERSION:{observed_version}!={expected_state_version}"
            )

        elements: list[dict[str, Any]] = []
        for path, payload in sorted((immutable_objects or {}).items()):
            blob_sha, _ = self.create_blob(payload)
            elements.append({"path": path, "mode": "100644", "type": "blob", "sha": blob_sha})
        head_blob_sha, _ = self.create_blob(mission_head)
        elements.append({
            "path": f"missions/{mission_id}/head.json",
            "mode": "100644",
            "type": "blob",
            "sha": head_blob_sha,
        })
        tree = self._api(
            "POST",
            "/git/trees",
            {"base_tree": current.tree_sha, "tree": elements},
        )
        commit = self._api(
            "POST",
            "/git/commits",
            {
                "message": f"harness-state: {mission_id} v{mission_head['state_version']}",
                "tree": tree["sha"],
                "parents": [expected_head_sha],
            },
        )
        encoded = parse.quote(f"heads/{self.branch}", safe="/")
        candidate=str(commit["sha"])
        for patch_attempt in range(1,3):
            try:
                self._api(
                    "PATCH",
                    f"/git/refs/{encoded}",
                    {"sha": candidate, "force": False},
                )
                return candidate
            except GitApiError as exc:
                ambiguous=exc.kind=="TRANSPORT" or (exc.status is not None and 500<=exc.status<=599)
                reconcilable=ambiguous or exc.status in {409,422}
                if not reconcilable: raise
                try: observed=str(self._ref()["object"]["sha"])
                except GitApiError as read_exc:
                    raise RefUpdateOutcomeUnknown(f"REF_UPDATE_OUTCOME_UNKNOWN:expected={expected_head_sha}:candidate={candidate}") from read_exc
                if observed==candidate:return candidate
                if observed!=expected_head_sha:
                    raise CasConflict(f"CAS_CONFLICT_CONFIRMED:expected={expected_head_sha}:candidate={candidate}:observed={observed}:http={exc.status}") from exc
                if exc.status==422:
                    raise GitRefUpdateRejected(422,exc.body,expected_head_sha,observed) from exc
                if exc.status in {409}:
                    raise GitRefUpdateRejected(409,exc.body,expected_head_sha,observed) from exc
                if ambiguous and patch_attempt<2:continue
                raise RefUpdateOutcomeUnknown(f"REF_UPDATE_OUTCOME_UNKNOWN:expected={expected_head_sha}:candidate={candidate}:observed={observed}") from exc
        raise RefUpdateOutcomeUnknown("REF_UPDATE_OUTCOME_UNKNOWN")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
