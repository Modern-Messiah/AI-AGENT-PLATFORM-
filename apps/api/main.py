"""FastAPI entrypoint — synchronous hello-agent (phase 1).

The agent runs in-process. Temporal-backed durable execution is added in
phase 2.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from packages.agents import AgentRunInput, AgentRunOutput, build_research_agent
from packages.observability import setup_tracing


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_tracing("aap-api")
    yield


app = FastAPI(title="AI Agent Platform", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/agent/run", response_model=AgentRunOutput)
async def run_agent(payload: AgentRunInput) -> AgentRunOutput:
    agent = build_research_agent(model_name=payload.model)
    result = await agent.run(payload.user_query)
    return result.output
