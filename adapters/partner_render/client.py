from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx


class RenderWorkflowsClient:
    """
    Render Workflows REST client (`https://api.render.com/v1`).
    Triggers and inspects Render Workflow task runs when RENDER_API_KEY is configured,
    and simulates deterministic run tracking locally when unconfigured.
    """

    def __init__(
        self,
        *,
        api_key: str = "",
        api_base: str = "https://api.render.com/v1",
        default_task_slug: str = "",
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key.strip()
        self.api_base = api_base.rstrip("/")
        self.default_task_slug = default_task_slug.strip()
        self.timeout = timeout
        self._transport = transport
        self._simulated_runs: dict[str, dict[str, Any]] = {}

    @property
    def is_live(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def probe(self) -> dict[str, Any]:
        """Verify Render API connectivity via GET /v1/workflows."""
        if not self.is_live:
            return {"configured": False, "ok": False, "mode": "simulated"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
                resp = await client.get(f"{self.api_base}/workflows", headers=self._headers())
                return {
                    "configured": True,
                    "ok": resp.status_code < 400,
                    "status_code": resp.status_code,
                    "mode": "live",
                }
        except Exception as exc:
            return {"configured": True, "ok": False, "mode": "live", "error": str(exc)[:200]}

    async def trigger_task(
        self,
        *,
        task_slug: str | None = None,
        input_args: list[Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Trigger a Render Workflow task run or record a local simulated run."""
        resolved_slug = (task_slug or self.default_task_slug or "mandate-recheck/sweep").strip()
        args = input_args if input_args is not None else []

        if not self.is_live:
            run_id = f"rnd-sim-{uuid.uuid4().hex[:12]}"
            record = {
                "run_id": run_id,
                "task_slug": resolved_slug,
                "status": "SUCCEEDED",
                "mode": "simulated",
                "started_at": datetime.now(UTC).isoformat(),
                "input": args,
                "results": {"metadata": metadata or {}},
            }
            self._simulated_runs[run_id] = record
            return record

        async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
            resp = await client.post(
                f"{self.api_base}/tasks/{resolved_slug}/runs",
                headers=self._headers(),
                json={"input": args},
            )
            if resp.status_code >= 400:
                return {
                    "run_id": "",
                    "task_slug": resolved_slug,
                    "status": "FAILED",
                    "mode": "live",
                    "started_at": datetime.now(UTC).isoformat(),
                    "input": args,
                    "results": {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"},
                }
            data = resp.json()
            return {
                "run_id": str(data.get("id") or data.get("run_id") or ""),
                "task_slug": resolved_slug,
                "status": str(data.get("status") or "RUNNING"),
                "mode": "live",
                "started_at": str(data.get("startedAt") or datetime.now(UTC).isoformat()),
                "input": args,
                "results": data,
            }

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Fetch status for a live or simulated Render Workflow task run."""
        if run_id in self._simulated_runs:
            return self._simulated_runs[run_id]
        if not self.is_live:
            return None

        async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
            resp = await client.get(
                f"{self.api_base}/task-runs/{run_id}",
                headers=self._headers(),
            )
            if resp.status_code == 404:
                return None
            if resp.status_code >= 400:
                return {
                    "run_id": run_id,
                    "task_slug": self.default_task_slug or "unknown",
                    "status": "ERROR",
                    "mode": "live",
                    "results": {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"},
                }
            data = resp.json()
            return {
                "run_id": str(data.get("id") or run_id),
                "task_slug": str(data.get("taskId") or self.default_task_slug or "unknown"),
                "status": str(data.get("status") or "UNKNOWN"),
                "mode": "live",
                "started_at": data.get("startedAt"),
                "input": data.get("input") or [],
                "results": data,
            }
