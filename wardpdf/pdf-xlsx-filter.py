import fitz
import pytesseract
from PIL import Image
import io, re, os
import numpy as np
import pandas as pd
from tqdm import tqdm

#config
INPUT_PDF = "ward 17.pdf"
OUTPUT_PDF = "filtered_output.pdf"
OUTPUT_XLSX = "voter_data.xlsx"
DPI = 400
DEBUG = False


HOUSE_RE = re.compile(r"(\d{1,3}\s*/\s*\d{1,4})")
TESSERACT_CONFIG = r"--oem 1 --psm 6"


def ocr_image(np_img):
    """Run Malayalam + English OCR and return cleaned text."""
    try:
        text = pytesseract.image_to_string(np_img, lang="mal+eng", config=TESSERACT_CONFIG)
    except Exception:
        text = pytesseract.image_to_string(np_img, config=TESSERACT_CONFIG)
    text = re.sub(r"[|•■□]+", "", text)
    return "\n".join([line.strip() for line in text.splitlines() if line.strip()])

def ocr_malayalam(pixmap):
    """Run OCR on image pixmap and return cleaned text."""
    img = Image.open(io.BytesIO(pixmap.tobytes("png")))
    text = pytesseract.image_to_string(img, lang="mal+eng")
    text = re.sub(r"[|•■□]+", "", text)
    return "\n".join([line.strip() for line in text.splitlines() if line.strip()])


def extract_and_filter(pdf_path, house_no_input, mode="both"):
    """Extract voter boxes filtered by house number and optionally save PDF and/or XLSX."""
    doc = fitz.open(pdf_path)
    collected = []
    all_voters = []

    print(f"\n🔍 Filtering for house number: {house_no_input}\n")

    for page_idx in tqdm(range(1, len(doc)), desc="📄 Processing pages", unit="page"):
        page = doc.load_page(page_idx)
        prefix = house_no_input.split("/")[0] + "/"
        if prefix not in page.get_text():
            continue

        pix = page.get_pixmap(dpi=DPI)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        img_arr = np.array(img)
        h_img, w_img = img_arr.shape[:2]
        rects = [d["rect"] for d in page.get_drawings() if d.get("rect")]
        scale = DPI / 72.0

        for rect_index, r in enumerate(rects):
            try:
                
                x0, y0, x1, y1 = int(r.x0 * scale), int(r.y0 * scale), int(r.x1 * scale), int(r.y1 * scale)
                full_crop = img_arr[y0:y1, x0:x1]

    
                sub_crop = full_crop[:, :int(full_crop.shape[1] * 0.5)]
                ocr_text = ocr_image(sub_crop)
                matches = [m.replace(" ", "") for m in HOUSE_RE.findall(ocr_text)]

                if house_no_input not in matches:
                    continue

                # Match found
                # --- Crop center-right portion for accurate field extraction ---
                width = r.x1 - r.x0
                height = r.y1 - r.y0
                value_area = fitz.Rect(
                    r.x0 + width * 0.26,
                    r.y0,
                    r.x1 - width * 0.2,
                    r.y1
                )

                pix = page.get_pixmap(clip=value_area, dpi=DPI)
                text = ocr_malayalam(pix)
                if not text.strip():
                    continue

                lines = [l.strip() for l in text.split("\n") if l.strip()]
                while len(lines) < 6:
                    lines.append("")

                # --- Improved voter ID detection ---
                id_match = re.search(r"[A-Z0-9/]{5,}", text.replace(" ", ""))
                voter_id = id_match.group(0).strip(".") if id_match else ""

                # --- Assign fields accurately ---
                name = lines[1] if len(lines) > 1 else ""
                relation = lines[2] if len(lines) > 2 else ""
                house_no = lines[3] if len(lines) > 3 else ""
                house_name = lines[4] if len(lines) > 4 else ""
                sex_age = lines[5] if len(lines) > 5 else ""

                # --- Extract sex and age ---
                sex, age = "", ""
                match = re.search(r"([പൂFMMS])[/\-]?\s*(\d{1,3})?", sex_age)
                if match:
                    sex = match.group(1)
                    age = match.group(2) if match.group(2) else ""


                sex, age = "", ""
                match = re.search(r"([പൂFMMS])[/\-]?\s*(\d{1,3})?", sex_age)
                if match:
                    sex = match.group(1)
                    age = match.group(2) if match.group(2) else ""

                all_voters.append({
                    "VoterID": voter_id,
                    "Name": name,
                    "Relation": relation,
                    "HouseNo": house_no,
                    "HouseName": house_name,
                    "Sex": sex,
                    "Age": age,
                    "Page": page_idx + 1,
                    "RectIndex": rect_index
                })

                collected.append(full_crop)

            except Exception as e:
                print(f"[Page {page_idx} | Rect {rect_index}] Error: {e}")

    # output
    if not collected:
        print("❌ No matches found — check OCR output or house number formatting.")
        return

    if mode in ("pdf", "both"):
        save_filtered_pdf(collected)
    if mode in ("xlsx", "both"):
        save_xlsx(all_voters)

    print("\n✅ Done.")


def save_filtered_pdf(collected):
    """Save filtered voter boxes as a new PDF."""
    out_doc = fitz.open()
    page_width, page_height = 595, 842  # A4
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

    out_doc.save(OUTPUT_PDF)
    out_doc.close()
    print(f"📄 Filtered PDF saved → {OUTPUT_PDF}")


def save_xlsx(voters):
    """Save extracted voter data to Excel."""
    df = pd.DataFrame(voters)
    df.to_excel(OUTPUT_XLSX, index=False, engine="openpyxl")
    print(f"📊 Excel file saved → {OUTPUT_XLSX}")


if __name__ == "__main__":
    house_no_input = input("Enter house number (e.g. 15/350): ").strip().replace(" ", "")
    if not house_no_input:
        print("⚠️ You must enter a house number.")
        exit()

    print("\nChoose output mode:")
    print("1️⃣  PDF only")
    print("2️⃣  XLSX only")
    print("3️⃣  Both PDF + XLSX")
    choice = input("Enter choice (1/2/3): ").strip()

    mode = "pdf" if choice == "1" else "xlsx" if choice == "2" else "both"
    extract_and_filter(INPUT_PDF, house_no_input, mode)
