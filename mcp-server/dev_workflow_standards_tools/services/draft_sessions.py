"""Bounded, process-local draft revisions; no remote conversation or persistence."""

from __future__ import annotations

import hashlib
import json
import time
from copy import deepcopy
from dataclasses import dataclass, field
from uuid import uuid4

from pydantic import Field, StrictInt, model_validator

from . import ai_workflow
from .ai_workflow import ContentGenerationRequest, EvidenceItem, StrictInput

TTL_SECONDS = 1800
MAX_SESSIONS = 16
MAX_ATTEMPTS = 16
MAX_SESSION_BYTES = 524288


class StartDraftRequest(StrictInput):
    request_id: str = Field(
        min_length=16,
        max_length=120,
        description="调用方生成的唯一请求标识；相同内容重放复用结果，不同内容冲突。进程内有效，不是用户身份。",
    )
    draft: ContentGenerationRequest = Field(
        description="首轮完整目标与证据；只允许issue/pr，继承完整patch、来源、语言及大小合同。"
    )

    @model_validator(mode="after")
    def issue_pr_only(self):
        if self.draft.kind not in {"issue", "pr"}:
            raise ValueError("only issue/pr drafts are supported")
        return self


class EvidenceChanges(StrictInput):
    add: list[EvidenceItem] = Field(
        default_factory=list,
        max_length=100,
        description="新增引用；ID不得已存在，默认空。",
    )
    replace: list[EvidenceItem] = Field(
        default_factory=list,
        max_length=100,
        description="替换现有引用的完整事实；ID必须存在，默认空。",
    )
    remove: list[str] = Field(
        default_factory=list,
        max_length=100,
        description="撤回现有引用ID；必须存在，与add/replace不交叉，默认空。",
    )


class ReviseDraftRequest(StrictInput):
    draft_session_id: str = Field(
        min_length=1,
        max_length=120,
        description="start返回的进程内不透明ID；不是认证凭据，重启/过期失效。",
    )
    expected_revision: StrictInt = Field(
        ge=0, description="get/start返回的当前版本；不匹配拒绝，防止覆盖其他修订。"
    )
    request_id: str = Field(
        min_length=16,
        max_length=120,
        description="本会话唯一尝试ID；相同内容重放缓存，不同内容拒绝。失败后新尝试使用新ID。",
    )
    feedback: str = Field(
        min_length=1,
        max_length=8000,
        description="本轮表达、重点或审查修订要求；不是事实、语言授权或绕过固定规则的指令。此前反馈累积保留，矛盾时明确本轮修正。",
    )
    evidence_changes: EvidenceChanges = Field(
        default_factory=EvidenceChanges,
        description="显式新增/替换/撤回事实；每轮重新校验来源和语言引用；默认不变。",
    )
    output_format: str | None = Field(
        default=None,
        min_length=1,
        max_length=12000,
        description="省略/null保留当前模板；非空字符串替换模板，不授权改变语言。",
    )


@dataclass
class DraftSession:
    request: ContentGenerationRequest
    touched: float = field(default_factory=time.monotonic)
    revision: int = 0
    evidence_revision: int = 1
    result: dict = field(default_factory=dict)
    feedback: list[str] = field(default_factory=list)
    attempts: dict = field(default_factory=dict)
    busy: bool = False


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _error(code):
    return {"ok": False, "adoptable": False, "error_code": code}


class DraftStore:
    """One local trusted stdio process is the isolation boundary, not a multi-user service."""

    def __init__(self):
        self.sessions: dict[str, DraftSession] = {}
        self.starts: dict[str, tuple[str, str]] = {}

    def _prune(self):
        now = time.monotonic()
        for sid, session in list(self.sessions.items()):
            if not session.busy and now - session.touched >= TTL_SECONDS:
                del self.sessions[sid]
        self.starts = {k: v for k, v in self.starts.items() if v[1] in self.sessions}

    def get(self, sid):
        if not sid or len(sid) > 120:
            return _error("invalid_draft_session_id")
        self._prune()
        session = self.sessions.get(sid)
        if session is None:
            return _error("draft_session_unavailable")
        return deepcopy(
            {
                "ok": True,
                "draft_session_id": sid,
                "revision": session.revision,
                "evidence_revision": session.evidence_revision,
                "status": "in_progress" if session.busy else "idle",
                "result": session.result,
                "expires_in_seconds": max(
                    0, int(TTL_SECONDS - (time.monotonic() - session.touched))
                ),
            }
        )

    def close(self, sid):
        if not sid or len(sid) > 120:
            return _error("invalid_draft_session_id")
        self._prune()
        session = self.sessions.get(sid)
        if session is None:
            return _error("draft_session_unavailable")
        if session.busy:
            return _error("draft_in_progress")
        del self.sessions[sid]
        self.starts = {k: v for k, v in self.starts.items() if v[1] != sid}
        return {"ok": True, "status": "closed", "draft_session_id": sid}

    async def start(self, request: StartDraftRequest):
        request = request.model_copy(deep=True)
        self._prune()
        digest = hashlib.sha256(
            _json(request.model_dump(mode="json")).encode()
        ).hexdigest()
        if request.request_id in self.starts:
            old_hash, sid = self.starts[request.request_id]
            if old_hash != digest:
                return _error("request_id_conflict")
            session = self.sessions[sid]
            if session.busy:
                return _error("draft_in_progress")
            return deepcopy(
                session.attempts.get(
                    request.request_id,
                    (
                        None,
                        {
                            **_error("draft_attempt_incomplete"),
                            "draft_session_id": sid,
                            "revision": session.revision,
                        },
                    ),
                )[1]
            )
        if len(self.sessions) >= MAX_SESSIONS:
            return _error("draft_capacity_exceeded")
        if len(_json(request.model_dump(mode="json")).encode()) > 32768:
            return _error("request_too_large")
        sid = uuid4().hex
        session = DraftSession(request.draft)
        self.sessions[sid] = session
        self.starts[request.request_id] = (digest, sid)
        result = await self._run(
            sid, session, request.draft, [], request.request_id, digest, False
        )
        if request.request_id not in session.attempts:
            result = {
                **result,
                "draft_session_id": sid,
                "revision": session.revision,
                "evidence_revision": session.evidence_revision,
            }
            session.attempts[request.request_id] = (digest, deepcopy(result))
        return result

    async def revise(self, request: ReviseDraftRequest):
        request = request.model_copy(deep=True)
        self._prune()
        session = self.sessions.get(request.draft_session_id)
        if session is None:
            return _error("draft_session_unavailable")
        digest = hashlib.sha256(
            _json(request.model_dump(mode="json")).encode()
        ).hexdigest()
        if session.busy:
            return _error("draft_in_progress")
        if request.request_id in session.attempts:
            old_hash, result = session.attempts[request.request_id]
            return (
                deepcopy(result)
                if digest == old_hash
                else _error("request_id_conflict")
            )
        if request.expected_revision != session.revision:
            return _error("draft_revision_conflict")
        if len(session.attempts) >= MAX_ATTEMPTS:
            return _error("draft_attempt_limit")
        changes = request.evidence_changes
        groups = [
            [x.reference_id for x in changes.add],
            [x.reference_id for x in changes.replace],
            changes.remove,
        ]
        flat = [reference for group in groups for reference in group]
        evidence = {x.reference_id: x for x in session.request.evidence}
        if (
            len(flat) != len(set(flat))
            or any(x in evidence for x in groups[0])
            or any(x not in evidence for x in groups[1] + groups[2])
        ):
            return _error("invalid_evidence_changes")
        for key in changes.remove:
            del evidence[key]
        for item in changes.replace + changes.add:
            evidence[item.reference_id] = item
        data = session.request.model_dump(mode="json")
        data["evidence"] = [x.model_dump(mode="json") for x in evidence.values()]
        if request.output_format is not None:
            data["output_format"] = request.output_format
        try:
            updated = ContentGenerationRequest.model_validate(data)
        except ValueError:
            return _error("invalid_draft_request")
        return await self._run(
            request.draft_session_id,
            session,
            updated,
            session.feedback + [request.feedback],
            request.request_id,
            digest,
            bool(flat),
        )

    async def _run(
        self, sid, session, request, feedback, request_id, digest, evidence_changed
    ):
        context = None
        if session.result or feedback:
            context = {
                "previous_candidate": session.result.get("candidate"),
                "previous_review": session.result.get("quality_review"),
                "feedback": feedback,
            }
        if (
            len(
                _json(
                    {
                        "request": request.model_dump(mode="json"),
                        "revision_context": context,
                    }
                ).encode()
            )
            > 32768
        ):
            return _error("request_too_large")
        # Reserve room for a bounded response before spending API work.
        if len(_json(session.attempts).encode()) > MAX_SESSION_BYTES - 66560:
            return _error("draft_capacity_exceeded")
        session.busy = True
        try:
            result = deepcopy(
                await ai_workflow.generate_skill_content(
                    request, revision_context=context
                )
            )
            completed = result.get("ok") is True
            response = {
                **result,
                "draft_session_id": sid,
                "revision": session.revision + int(completed),
                "evidence_revision": session.evidence_revision
                + int(completed and evidence_changed),
                "changes_summary": feedback[-1][:256] if feedback else "首轮候选",
                "stored": True,
                "storage": "process_memory",
                "executed_external_actions": False,
            }
            if len(_json(response).encode()) > 65536:
                response = {
                    **_error("draft_result_too_large"),
                    "draft_session_id": sid,
                    "revision": session.revision,
                    "evidence_revision": session.evidence_revision,
                }
                completed = False
            # Commit only after every bound and both API stages have succeeded.
            if completed:
                session.request = request
                session.feedback = feedback
                session.revision += 1
                session.evidence_revision += int(evidence_changed)
                session.result = deepcopy(result)
            session.attempts[request_id] = (digest, deepcopy(response))
            return response
        finally:
            session.busy = False
            session.touched = time.monotonic()


store = DraftStore()


async def start_issue_pr_draft(request: StartDraftRequest) -> dict:
    return await store.start(request)


async def revise_issue_pr_draft(request: ReviseDraftRequest) -> dict:
    return await store.revise(request)


def get_issue_pr_draft(draft_session_id: str) -> dict:
    return store.get(draft_session_id)


def close_issue_pr_draft(draft_session_id: str) -> dict:
    return store.close(draft_session_id)
