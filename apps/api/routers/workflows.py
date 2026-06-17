from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from temporalio.client import Client
from temporalio.service import RPCError

from packages.agents import AgentRunOutput
from packages.core.tenant_utils import check_workflow_tenant

from apps.api.deps import TenantID
from apps.api.schemas import AgentRunApiResponse, WorkflowSignalResponse
from apps.worker.workflows.agent_run import AgentRunWorkflow

router = APIRouter()


@router.get("/workflows/{workflow_id}/result", response_model=AgentRunApiResponse)
async def get_workflow_result(
    workflow_id: str,
    tenant_id: TenantID,
    request: Request,
) -> AgentRunApiResponse:
    """Poll for HITL workflow result. Returns pending_approval=True while still waiting."""
    check_workflow_tenant(workflow_id, tenant_id)
    client: Client = request.app.state.temporal
    handle = client.get_workflow_handle(workflow_id)
    try:
        result: AgentRunOutput = await asyncio.wait_for(handle.result(), timeout=2.0)
        return AgentRunApiResponse(
            answer=result.answer,
            confidence=result.confidence,
            sources=result.sources,
            workflow_id=workflow_id,
        )
    except asyncio.TimeoutError:
        return AgentRunApiResponse(workflow_id=workflow_id, pending_approval=True)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/workflows/{workflow_id}/approve", response_model=WorkflowSignalResponse)
async def approve_workflow(
    workflow_id: str,
    tenant_id: TenantID,
    request: Request,
) -> WorkflowSignalResponse:
    check_workflow_tenant(workflow_id, tenant_id)
    client: Client = request.app.state.temporal
    try:
        await client.get_workflow_handle(workflow_id).signal(AgentRunWorkflow.approve)
    except RPCError as e:
        code = 404 if "not found" in str(e).lower() else 503
        detail = "workflow not found" if code == 404 else "workflow service unavailable"
        raise HTTPException(status_code=code, detail=detail) from e
    return WorkflowSignalResponse(workflow_id=workflow_id, action="approved")


@router.post("/workflows/{workflow_id}/reject", response_model=WorkflowSignalResponse)
async def reject_workflow(
    workflow_id: str,
    tenant_id: TenantID,
    request: Request,
) -> WorkflowSignalResponse:
    check_workflow_tenant(workflow_id, tenant_id)
    client: Client = request.app.state.temporal
    try:
        await client.get_workflow_handle(workflow_id).signal(AgentRunWorkflow.reject)
    except RPCError as e:
        code = 404 if "not found" in str(e).lower() else 503
        detail = "workflow not found" if code == 404 else "workflow service unavailable"
        raise HTTPException(status_code=code, detail=detail) from e
    return WorkflowSignalResponse(workflow_id=workflow_id, action="rejected")
