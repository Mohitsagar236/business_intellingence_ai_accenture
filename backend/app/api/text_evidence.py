from __future__ import annotations

import io

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_roles
from app.pipeline.ingestion import IngestionError, validate_and_insert_text_evidence
from app.schemas import UploadResultOut

router = APIRouter(
    prefix="/api/text-evidence", tags=["text-evidence"], dependencies=[Depends(require_roles("analyst", "admin"))]
)


@router.post("/upload", response_model=UploadResultOut)
async def upload_text_evidence(file: UploadFile = File(...), db: Session = Depends(get_db)):
    file_bytes = await file.read()
    try:
        result = validate_and_insert_text_evidence(db, file_bytes, file.filename or "upload.csv")
    except IngestionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return UploadResultOut(
        rows_inserted=result.rows_inserted,
        date_range_start=result.date_range[0] if result.date_range else None,
        date_range_end=result.date_range[1] if result.date_range else None,
        warnings=result.warnings,
        duplicates_skipped=result.duplicates_skipped,
    )


@router.get("/template")
def text_evidence_template():
    csv_text = (
        "date,text,source_system,region,product,channel\n"
        '2026-01-01,"Customer reported a failed payment at checkout.",ticketing,South,Product B,\n'
    )
    return StreamingResponse(
        io.StringIO(csv_text),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="text_evidence_template.csv"'},
    )
