import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import io
import pandas as pd
import re
from tqdm import tqdm  # progress bar

# ========== CONFIG ==========
INPUT_PDF = "ward 17.pdf"
OUTPUT_CSV = "voter_data.csv"
DPI = 300
DEBUG = False   # 🔧 Set to True → shows 1 cropped box for checking
# ============================

# Malayalam + English OCR
def ocr_malayalam(pixmap):
    """Run OCR on image pixmap and return cleaned text."""
    img = Image.open(io.BytesIO(pixmap.tobytes("png")))
    text = pytesseract.image_to_string(img, lang="mal+eng")
    text = re.sub(r"[|•■□]+", "", text)
    return "\n".join([line.strip() for line in text.splitlines() if line.strip()])


def extract_voters(pdf_path):
    doc = fitz.open(pdf_path)
    all_voters = []

    pages = range(1, len(doc))  # Skip first page
    for page_index in tqdm(pages, desc="📄 Processing pages", unit="page"):
        page = doc.load_page(page_index)
        drawings = page.get_drawings()
        rects = [fitz.Rect(d["rect"]) for d in drawings if "rect" in d]

        for rect_index, rect in enumerate(rects):
            try:
                # --- Crop center-right portion (value area) ---
                width = rect.x1 - rect.x0
                height = rect.y1 - rect.y0
                value_area = fitz.Rect(
                    rect.x0 + width * 0.26,   # ⬅️ show more left side
                    rect.y0,
                    rect.x1 - width * 0.2,    # ➡️ crop a bit from right side
                    rect.y1
                )

                pix = page.get_pixmap(clip=value_area, dpi=DPI)

                # 🧩 Debug mode → show first cropped voter box and stop
                if DEBUG:
                    img = Image.open(io.BytesIO(pix.tobytes("png")))
                    img.show()
                    print(f"🪟 Debug crop shown for Page {page_index}, Rect {rect_index}")
                    return

                text = ocr_malayalam(pix)
                if not text.strip():
                    continue

                lines = [l.strip() for l in text.split("\n") if l.strip()]
                while len(lines) < 6:
                    lines.append("")

                # --- Improved voter ID detection ---
                id_match = re.search(r"[A-Z0-9/]{5,}", text.replace(" ", ""))
                voter_id = id_match.group(0).strip(".") if id_match else ""

                # --- Assign fields ---
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

                # ✅ No house number filtering — save all entries
                all_voters.append({
                    "VoterID": voter_id,
                    "Name": name,
                    "Relation": relation,
                    "HouseNo": house_no.strip(),
                    "HouseName": house_name.strip(),
                    "Sex": sex,
                    "Age": age,
                    "Page": page_index + 1,
                    "RectIndex": rect_index
                })

            except Exception as e:
                print(f"[Page {page_index} | Rect {rect_index}] Error: {e}")
                continue

    df = pd.DataFrame(all_voters)
    OUTPUT_XLSX = "voter_data.xlsx"
    df.to_excel(OUTPUT_XLSX, index=False, engine="openpyxl")



# Run
if __name__ == "__main__":
    extract_voters(INPUT_PDF)
