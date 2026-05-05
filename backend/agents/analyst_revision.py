"""Backward-compatible shim: revision lives on AnalystAgent.revise."""

from agents.analyst import AnalystAgent


class AnalystRevisionAgent:
    async def run(self, **kwargs):
        return await AnalystAgent().revise(**kwargs)
