# ocr_logic.py
import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import io, re, os
import numpy as np
import pandas as pd
from tqdm import tqdm

DPI = 400
OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

HOUSE_RE = re.compile(r"(\d{1,3}\s*/\s*\d{1,4})")
TESSERACT_CONFIG = r"--oem 1 --psm 6"

def ocr_malayalam(pixmap):
    """Run OCR on image pixmap and return cleaned text."""
    img = Image.open(io.BytesIO(pixmap.tobytes("png")))
    text = pytesseract.image_to_string(img, lang="mal+eng")
    text = re.sub(r"[|•■□]+", "", text)
    return "\n".join([line.strip() for line in text.splitlines() if line.strip()])


def process_voter_pdf(pdf_bytes, house_no_input,mode):
    """Main processing logic: filter by house number and export PDF/XLSX."""
    temp_pdf = os.path.join(OUTPUT_DIR, "temp_input.pdf")
    with open(temp_pdf, "wb") as f:
        f.write(pdf_bytes)

    doc = fitz.open(temp_pdf)
    collected = []
    all_voters = []

    for page_idx in tqdm(range(1, len(doc)), desc="📄 Processing pages", unit="page"):
        page = doc.load_page(page_idx)
        prefix = house_no_input.split("/")[0] + "/"
        if prefix not in page.get_text():
            continue

        pix = page.get_pixmap(dpi=DPI)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        img_arr = np.array(img)
        rects = [d["rect"] for d in page.get_drawings() if d.get("rect")]
        scale = DPI / 72.0

        for rect_index, r in enumerate(rects):
            try:
                # --- Check if this box belongs to the house ---
                x0, y0, x1, y1 = int(r.x0 * scale), int(r.y0 * scale), int(r.x1 * scale), int(r.y1 * scale)
                full_crop = img_arr[y0:y1, x0:x1]
                sub_crop = full_crop[:, :int(full_crop.shape[1] * 0.5)]
                ocr_text = pytesseract.image_to_string(sub_crop, lang="mal+eng", config=TESSERACT_CONFIG)
                matches = [m.replace(" ", "") for m in HOUSE_RE.findall(ocr_text)]
                if house_no_input not in matches:
                    continue

                # --- Crop center-right portion for structured extraction ---
                width = r.x1 - r.x0
                height = r.y1 - r.y0
                value_area = fitz.Rect(
                    r.x0 + width * 0.26,
                    r.y0,
                    r.x1 - width * 0.2,
                    r.y1
                )

                pix_val = page.get_pixmap(clip=value_area, dpi=DPI)
                text = ocr_malayalam(pix_val)
                if not text.strip():
                    continue

                lines = [l.strip() for l in text.split("\n") if l.strip()]
                while len(lines) < 6:
                    lines.append("")

                id_match = re.search(r"[A-Z0-9/]{5,}", text.replace(" ", ""))
                voter_id = id_match.group(0).strip(".") if id_match else ""

                name = lines[1] if len(lines) > 1 else ""
                relation = lines[2] if len(lines) > 2 else ""
                house_no = lines[3] if len(lines) > 3 else ""
                house_name = lines[4] if len(lines) > 4 else ""
                sex_age = lines[5] if len(lines) > 5 else ""

                sex, age = "", ""
                match = re.search(r"([പൂFMMS])[/\-]?\s*(\d{1,3})?", sex_age)
                if match:
                    sex = match.group(1)
                    age = match.group(2) if match.group(2) else ""

                all_voters.append({
                    "VoterID": voter_id,
                    "Name": name,
                    "Relation": relation,
                    "HouseNo": house_no.strip(),
                    "HouseName": house_name.strip(),
                    "Sex": sex,
                    "Age": age,
                    "Page": page_idx + 1,
                    "RectIndex": rect_index
                })

                collected.append(full_crop)

            except Exception as e:
                print(f"[Page {page_idx} | Rect {rect_index}] Error: {e}")

    results = {}



    if mode == "xlsx":
        xlsx_path = os.path.join(OUTPUT_DIR, f"voter_data_{house_no_input.replace('/', '-')}.xlsx")
        pd.DataFrame(all_voters).to_excel(xlsx_path, index=False, engine="openpyxl")
        results["xlsx"] = xlsx_path

    elif mode == "pdf":
        pdf_path = os.path.join(OUTPUT_DIR, f"filtered_{house_no_input.replace('/', '-')}.pdf")
        save_filtered_pdf(collected, pdf_path)
        results["pdf"] = pdf_path


    doc.close()
    return results


def save_filtered_pdf(collected, output_path):
    """Save filtered voter boxes as a new PDF."""
    out_doc = fitz.open()
    page_width, page_height = 595, 842
    boxes_per_row, boxes_per_page = 2, 20
    voter_width = page_width // boxes_per_row
    voter_height = page_height // (boxes_per_page // boxes_per_row)

    count = 0
    for crop in collected:
        if count % boxes_per_page == 0:
            out_page = out_doc.new_page(width=page_width, height=page_height)
            x_pt, y_pt = 0, 0

        pil = Image.fromarray(crop).resize((int(voter_width - 10), int(voter_height - 10)))
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        rect = fitz.Rect(x_pt + 5, y_pt + 5, x_pt + voter_width - 5, y_pt + voter_height - 5)
        out_page.insert_image(rect, stream=buf.getvalue())

        count += 1
        if count % boxes_per_row == 0:
            x_pt = 0
            y_pt += voter_height
        else:
            x_pt += voter_width

    out_doc.save(output_path)
    out_doc.close()
