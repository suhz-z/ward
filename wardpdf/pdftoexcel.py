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

# ✅ Allowed house number ranges and fixed entries
VALID_HOUSES_RAW = """
4/42, 4/46, 4/54, 4/248-4/261, 4/263-4/267, 4/270, 4/272-4/282, 4/284-4/287, 4/289-4/293,
4/296-4/306, 4/309, 4/311-4/313, 4/315-4/316, 4/320-4/322, 4/349, 14/453, 15/0-15/3,
15/6, 15/8-15/10, 15/12-15/26, 15/28-15/31, 15/33, 15/35-15/44, 15/46, 15/48, 15/50,
15/55-15/56, 15/76-15/77, 15/80-15/81, 15/83, 15/85, 15/87-15/88, 15/90-15/91,
15/93-15/102, 15/104-15/105, 15/107-15/115, 15/126, 15/134, 15/169, 15/171, 15/174,
15/177-15/179, 15/181-15/182, 15/184-15/187, 15/189-15/201, 15/203-15/221, 15/223,
15/225-15/227, 15/229, 15/231-15/234, 15/236-15/241, 15/243, 15/245-15/247,
15/249-15/251, 15/256-15/260, 15/284-15/286, 15/300, 15/302, 15/304, 15/307-15/309,
15/311, 15/313-15/314, 15/316-15/318, 15/320-15/329, 15/333, 15/335-15/336,
15/339-15/343, 15/346-15/351, 15/378, 15/440, 15/449, 15/533
"""

def expand_house_ranges(raw_text):
    """Expand and normalize all house ranges like 15/0-15/3 or 4/248-4/261."""
    houses = set()
    parts = [p.strip() for p in re.split(r",\s*", raw_text.strip()) if p.strip()]
    for part in parts:
        try:
            if "-" in part:
                # find prefix and numeric parts flexibly
                match = re.match(r"(\d+)/(\d+)-(\d+)/(\d+)", part)
                if match:
                    # handles cross-prefix like 4/248-4/261
                    prefix1, start, prefix2, end = match.groups()
                    if prefix1 != prefix2:
                        continue  # skip inconsistent range
                    for i in range(int(start), int(end) + 1):
                        houses.add(f"{prefix1}/{i}")
                else:
                    # handles same-prefix like 15/0-15/3 or 15/0-3
                    match = re.match(r"(\d+)/(\d+)-(\d+)", part)
                    if match:
                        prefix, start, end = match.groups()
                        for i in range(int(start), int(end) + 1):
                            houses.add(f"{prefix}/{i}")
            else:
                houses.add(part)
        except Exception as e:
            print(f"⚠️ Skipping invalid entry '{part}': {e}")
            continue
    return houses


VALID_HOUSES = expand_house_ranges(VALID_HOUSES_RAW)

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

    # Use tqdm for progress bar
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
                    rect.x0 + width * 0.3,   # ⬅️ show more left side (was 0.1)
                    rect.y0 ,   # top trim (fine)
                    rect.x1 - width * 0.2,   # ➡️ crop a bit from right side
                    rect.y1   # bottom trim (fine)
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

                voter_id = lines[0] if re.search(r"[A-Z]+[A-Z0-9/]+", lines[0]) else ""
                name = lines[1] if len(lines) > 1 else ""
                relation = lines[2] if len(lines) > 2 else ""
                house_no = lines[3] if len(lines) > 3 else ""
                house_name = lines[4] if len(lines) > 4 else ""
                sex_age = lines[5] if len(lines) > 5 else ""

                # --- Normalize house number ---
                house_no_clean = house_no.replace(" ", "").replace("Apr-", "4/").strip()
                if not re.match(r"\d+/\d+", house_no_clean):
                    house_no_clean = re.sub(r"[^\d/]", "", house_no_clean)

                # --- Filter only allowed house numbers ---
                if house_no_clean not in VALID_HOUSES:
                    continue

                # --- Extract sex and age ---
                sex, age = "", ""
                match = re.search(r"([പൂFMMS])[/\-]?\s*(\d{1,3})?", sex_age)
                if match:
                    sex = match.group(1)
                    age = match.group(2) if match.group(2) else ""

                all_voters.append({
                    "VoterID": voter_id,
                    "Name": name,
                    "Relation": relation,
                    "HouseNo": house_no_clean,
                    "HouseName": house_name,
                    "Sex": sex,
                    "Age": age,
                    "Page": page_index + 1,
                    "RectIndex": rect_index
                })

            except Exception as e:
                print(f"[Page {page_index} | Rect {rect_index}] Error: {e}")
                continue

    df = pd.DataFrame(all_voters)
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n✅ Extraction completed: {len(df)} valid voters saved to {OUTPUT_CSV}")

# Run
if __name__ == "__main__":
    extract_voters(INPUT_PDF)
