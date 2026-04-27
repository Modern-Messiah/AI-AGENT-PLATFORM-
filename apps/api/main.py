"""FastAPI entrypoint.

Exposes a thin HTTP surface that starts a Temporal workflow and waits for
the result. Streaming and async-result endpoints come later.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from temporalio.client import Client

from apps.worker.workflows.agent_run import AgentRunWorkflow
from packages.agents import AgentRunInput, AgentRunOutput
from packages.core import settings
from packages.observability import setup_tracing


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_tracing("aap-api")
    app.state.temporal = await Client.connect(
        settings.temporal_address, namespace=settings.temporal_namespace
    )
    yield


app = FastAPI(title="AI Agent Platform", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/agent/run", response_model=AgentRunOutput)
async def run_agent(payload: AgentRunInput) -> AgentRunOutput:
    client: Client = app.state.temporal
    workflow_id = f"agent-run-{payload.tenant_id}-{uuid.uuid4()}"
    try:
        return await client.execute_workflow(
            AgentRunWorkflow.run,
            payload,
            id=workflow_id,
            task_queue=settings.temporal_task_queue,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e
