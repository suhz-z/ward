from fastapi import FastAPI, UploadFile, Form, File
from fastapi.responses import FileResponse
import tempfile, os
from voter_filter.core import filter_pdf_for_house

app = FastAPI(title="Voter List Filter")

@app.post("/filter", response_class=FileResponse)
async def filter_pdf(file: UploadFile = File(...), house_no: str = Form(...)):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_in:
        tmp_in.write(await file.read())
        input_path = tmp_in.name

    output_path = tempfile.mktemp(suffix=".pdf")
    total = filter_pdf_for_house(input_path, output_path, house_no)

    if total == 0:
        os.remove(output_path)
        return {"message": f"No matches found for {house_no}"}

    return FileResponse(
        output_path,
        media_type="application/pdf",
        filename=f"filtered_{house_no}.pdf"
    )
