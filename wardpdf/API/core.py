import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import io, re, os
import numpy as np
import pandas as pd
from tqdm import tqdm

# ---------------- CONFIG ----------------
DPI = 400
OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

HOUSE_RE = re.compile(r"(\d{1,3}\s*/\s*\d{1,4})")
TESSERACT_CONFIG = r"--oem 3 --psm 6"
# ----------------------------------------


def ocr_malayalam(pixmap):
    """Run OCR on image pixmap with improved English top-line accuracy for Voter ID."""
    img = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("L")

    # Binarize for better contrast
    img = img.point(lambda x: 0 if x < 165 else 255, "1")

    # OCR full block (Malayalam + English)
    text = pytesseract.image_to_string(img, lang="mal+eng", config=TESSERACT_CONFIG)
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    # Re-OCR top ~18% for cleaner Voter ID (English only)
    if lines:
        top_crop = img.crop((0, 0, img.width, int(img.height * 0.18)))
        id_text = pytesseract.image_to_string(
            top_crop,
            lang="eng",
            config="--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/",
        )
        id_text = re.sub(r"[^A-Za-z0-9/]", "", id_text).strip()
        if id_text:
            lines[0] = id_text

    return "\n".join(lines)


def parse_voter_lines(lines, pixmap=None):
    """Parse OCR lines into structured fields (VoterID, Name, Relation, HouseNo, HouseName, Age)."""
    lines = [l.strip() for l in lines if l.strip()]
    while len(lines) < 6:
        lines.append("")

    # Extract Voter ID (English alphanumeric)
    id_match = re.search(r"[A-Z0-9/]{5,}", "".join(lines))
    voter_id = id_match.group(0).strip(".") if id_match else ""

    name = lines[1] if len(lines) > 1 else ""
    relation = lines[2] if len(lines) > 2 else ""
    house_no = lines[3] if len(lines) > 3 else ""
    house_name = ""
    age = ""

    # ✅ Clean OCR artifact: remove unwanted 'വ്‌' prefix
    relation = re.sub(r"^(വ്‌|വ്|\u0D35\u0D4D\u200C)", "", relation).strip()

    # Try to get Malayalam house name
    has_house_name = False
    if len(lines) > 4 and not re.search(r"\d{1,3}", lines[4]):
        house_name = lines[4].strip()
        has_house_name = True

    # 🧠 Determine which line likely contains age info
    age_line_index = 5 if has_house_name else 4
    if len(lines) > age_line_index:
        candidate_line = lines[age_line_index]
        # Extract digits after '/'
        match = re.search(r"/\s*(\d{2,3})", candidate_line)
        if match:
            age = match.group(1)
        else:
            # As fallback, re-OCR lower 20% of block in English mode
            if pixmap:
                img = Image.open(io.BytesIO(pixmap.tobytes("png")))
                w, h = img.size
                low_crop = img.crop((0, int(h * 0.80), w, h))
                eng_text = pytesseract.image_to_string(low_crop, lang="eng", config="--psm 6")
                match2 = re.search(r"(\d{2,3})", eng_text)
                if match2:
                    age = match2.group(1)

    return voter_id, name, relation, house_no, house_name, age


def process_voter_pdf(pdf_bytes, house_no_input, mode):
    """Filter by house number and export as PDF/XLSX."""
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
                x0, y0, x1, y1 = int(r.x0 * scale), int(r.y0 * scale), int(r.x1 * scale), int(r.y1 * scale)
                full_crop = img_arr[y0:y1, x0:x1]
                sub_crop = full_crop[:, :int(full_crop.shape[1] * 0.5)]
                ocr_text = pytesseract.image_to_string(sub_crop, lang="mal+eng", config=TESSERACT_CONFIG)
                matches = [m.replace(" ", "") for m in HOUSE_RE.findall(ocr_text)]
                if house_no_input not in matches:
                    continue

                # Crop voter box (region with full details)
                width = r.x1 - r.x0
                height = r.y1 - r.y0
                value_area = fitz.Rect(
                    r.x0 + width * 0.26,
                    r.y0,
                    r.x1 - width * 0.2,
                    r.y1,
                )

                pix_val = page.get_pixmap(clip=value_area, dpi=DPI)
                text = ocr_malayalam(pix_val)
                if not text.strip():
                    continue

                lines = [l.strip() for l in text.split("\n") if l.strip()]
                voter_id, name, relation, house_no, house_name, age = parse_voter_lines(lines, pix_val)

                all_voters.append({
                    "VoterID": voter_id,
                    "Name": name,
                    "Relation": relation,
                    "HouseNo": house_no.strip(),
                    "HouseName": house_name.strip(),
                    "Age": age.strip(),
                    "Page": page_idx + 1,
                    "RectIndex": rect_index,
                })

                collected.append(full_crop)

            except Exception as e:
                print(f"[Page {page_idx} | Rect {rect_index}] Error: {e}")

    results = {}

    if mode == "xlsx":
        xlsx_path = os.path.join(OUTPUT_DIR, f"voter_data_{house_no_input.replace('/', '-')}.xlsx")
        df = pd.DataFrame(all_voters)
        df.to_excel(xlsx_path, index=False, engine="openpyxl")
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
    
