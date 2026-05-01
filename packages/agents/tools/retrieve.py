"""Retrieval tool — gives the agent access to the tenant-scoped vector store."""

from __future__ import annotations

from pydantic import BaseModel
from pydantic_ai import Agent, RunContext

from packages.agents.deps import AgentDeps
from packages.agents.schemas import AgentRunOutput
from packages.rag import retrieve_chunks


class RetrievedSource(BaseModel):
    document_id: str
    filename: str
    content: str
    score: float


def register_retrieval_tool(agent: Agent[AgentDeps, AgentRunOutput]) -> None:
    @agent.tool
    async def retrieve(
        ctx: RunContext[AgentDeps],
        query: str,
        k: int = 5,
    ) -> list[RetrievedSource]:
        """Search the knowledge base for chunks relevant to the query.

        Use this whenever the user asks about anything that might be in the
        uploaded documents. Pass a focused query string. Returns up to `k`
        chunks ordered by relevance (best first).

        In your answer's sources field, include ONLY the filename of documents
        whose content you directly cited or paraphrased. If a chunk was not
        helpful for your answer, do not include its filename.
        """
        results = await retrieve_chunks(query=query, tenant_id=ctx.deps.tenant_id, k=k)
        for r in results:
            if r.filename not in ctx.deps.sources:
                ctx.deps.sources.append(r.filename)
        return [
            RetrievedSource(
                document_id=r.document_id,
                filename=r.filename,
                content=r.content,
                score=r.score,
            )
            for r in results
        ]
