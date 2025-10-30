# main.py
from fastapi import FastAPI, UploadFile, Form, HTTPException
from fastapi.responses import FileResponse
from ocr_logic import process_voter_pdf

app = FastAPI(title="Voter OCR & Filter API")

@app.post("/process")
async def process_pdf(
    file: UploadFile,
    house_no: str = Form("write houseno (e.g. 15/350,4/54) here"),
    mode: str = Form("pdf or xlsx")
):
    """
    mode: 'pdf' or 'xlsx'
    """
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
