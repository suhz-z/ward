
from fastapi import FastAPI, UploadFile, Form, HTTPException
from fastapi.responses import FileResponse
from core import process_voter_pdf
from enum import Enum

app = FastAPI(title="Voter OCR & Filter API")

class OutputMode(str, Enum):
    pdf = "pdf"
    xlsx = "xlsx"


@app.post("/process")
async def process_pdf(
    file: UploadFile,
    house_no: str = Form(...),
    mode: OutputMode = Form(...)
):

    
    if mode not in ("pdf", "xlsx"):
        raise HTTPException(status_code=400, detail="Invalid mode. Must be 'pdf' or 'xlsx'.")

    pdf_bytes = await file.read()
    results = process_voter_pdf(pdf_bytes, house_no, mode)

    if mode == "pdf" and "pdf" in results:
        return FileResponse(results["pdf"], filename=f"filtered_{house_no}.pdf")
    elif mode == "xlsx" and "xlsx" in results:
        return FileResponse(results["xlsx"], filename=f"voter_data_{house_no}.xlsx")
    else:
        raise HTTPException(status_code=500, detail="Output file not generated.")
