"""
FastAPI web app for voter list filtering by house number.

Features:
 - Uses PyMuPDF get_drawings() for vector box detection
 - OCRs only left half of each voter box for speed
 - Filters by a given house number (Malayalam + English OCR)
 - Returns a filtered PDF containing matching boxes only

Usage:
  pip install fastapi uvicorn PyMuPDF pillow pytesseract numpy python-multipart
  Make sure Tesseract + mal.traineddata installed.

Run:
  uvicorn app:app --reload

Then open:
  http://127.0.0.1:8000/docs  → upload PDF + enter house number
  or call /filter via HTML form / JS fetch.
"""

from fastapi import FastAPI, UploadFile, Form, File
from fastapi.responses import FileResponse
import fitz
from PIL import Image
import numpy as np
import pytesseract
import tempfile, io, re, os

app = FastAPI(title="Voter List Filter", version="1.0")

# OCR / detection settings
dpi = 200  # render resolution
DEFAULT_PAD = (5, 10, 5, 20)
HOUSE_RE = re.compile(r"(\d{1,3}\s*/\s*\d{1,4})")
TESSERACT_CONFIG = r"--oem 1 --psm 6"  # fast mode

def ocr_text_from_image(np_img):
    try:
        return pytesseract.image_to_string(np_img, lang="mal+eng", config=TESSERACT_CONFIG)
    except Exception:
        return pytesseract.image_to_string(np_img, config=TESSERACT_CONFIG)

def expand_rect_px(x, y, w, h, img_w, img_h, pad=DEFAULT_PAD):
    left, top, right, bottom = pad
    x0 = max(0, x - left)
    y0 = max(0, y - top)
    x1 = min(img_w, x + w + right)
    y1 = min(img_h, y + h + bottom)
    return x0, y0, x1, y1

def filter_pdf_for_house(input_pdf: str, output_pdf: str, house_no: str):
    """Main logic (same as CLI version)"""
    house_no = house_no.strip().replace(" ", "")
    doc = fitz.open(input_pdf)
    pages = len(doc)
    collected = []

    for page_idx in range(1, pages):  # skip first page (header)
        page = doc[page_idx]
        prefix = house_no.split("/")[0] + "/"
        if prefix not in page.get_text():
            continue

        pix = page.get_pixmap(dpi=dpi)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        img_arr = np.array(img)
        h_img, w_img = img_arr.shape[:2]

        rects = [d["rect"] for d in page.get_drawings() if d.get("rect")]
        scale = dpi / 72.0

        for idx, r in enumerate(rects):
            x0, y0, x1, y1 = int(r.x0*scale), int(r.y0*scale), int(r.x1*scale), int(r.y1*scale)
            ex0, ey0, ex1, ey1 = expand_rect_px(x0, y0, x1-x0, y1-y0, w_img, h_img)
            full_crop = img_arr[ey0:ey1, ex0:ex1]

            # OCR left half only
            w_box = ex1 - ex0
            sub_crop = img_arr[ey0:ey1, ex0:int(ex0 + w_box*0.5)]

            ocr = ocr_text_from_image(sub_crop)
            matches = [m.replace(" ", "") for m in HOUSE_RE.findall(ocr)]

            if house_no in matches:
                collected.append((page_idx, full_crop))

    # === Build output PDF ===
    out_doc = fitz.open()
    page_width, page_height = 595, 842  # A4
    boxes_per_row, boxes_per_page = 2, 20
    voter_width = page_width // boxes_per_row
    voter_height = page_height // (boxes_per_page // boxes_per_row)

    count = 0
    for page_idx, crop in collected:
        if count % boxes_per_page == 0:
            out_page = out_doc.new_page(width=page_width, height=page_height)
            x_pt, y_pt = 0, 0

        pil = Image.fromarray(crop).resize((int(voter_width - 10), int(voter_height - 10)))
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        rect = fitz.Rect(x_pt+5, y_pt+5, x_pt+voter_width-5, y_pt+voter_height-5)
        out_page.insert_image(rect, stream=buf.getvalue())

        count += 1
        if count % boxes_per_row == 0:
            x_pt = 0
            y_pt += voter_height
        else:
            x_pt += voter_width

    out_doc.save(output_pdf)
    out_doc.close()
    doc.close()
    return len(collected)

@app.post("/filter", response_class=FileResponse)
async def filter_pdf(file: UploadFile = File(...), house_no: str = Form(...)):
    """API endpoint: upload PDF + house number → get filtered PDF"""
    # save uploaded file to temp
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_in:
        tmp_in.write(await file.read())
        tmp_in.flush()
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
