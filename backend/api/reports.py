from fastapi import APIRouter, HTTPException

from db.queries import get_report

router = APIRouter()


@router.get("/{session_id}")
async def get_report_endpoint(session_id: str) -> dict:
    report = await get_report(session_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report
