import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import pandas as pd
import re
import io

# ==============================
# CONFIG
# ==============================
INPUT_PDF = "ward 17.pdf"
OUTPUT_XLSX = "voter_data.xlsx"
DPI = 300
DEBUG = False  # Set True to save crop previews
# ==============================

# Flexible crop settings — all values are in percentages (0–1)
# Adjust these until both left/right crops look perfect.
CROP_CONFIG = {
    "top": 0.05,       # Remove top 8%
    "bottom": 0.935,    # Keep up to 95% of height
    "left_outer": 0.19, # Trim 2% from left edge of left crop
    "left_inner": 0.41, # Where left crop ends (50% = middle)
    "right_inner": 0.62,# Where right crop starts (52% = just right of middle)
    "right_outer": 0.8 # Trim 2% from right edge of page
}


def extract_voters_flexible(pdf_path, output_xlsx):
    doc = fitz.open(pdf_path)
    all_voters = []

    print(f"📘 Starting OCR on '{pdf_path}' ({len(doc)} pages)...")

    for page_idx in range(1, len(doc)):  # Skip first page
        page = doc.load_page(page_idx)
        print(f"📄 Processing page {page_idx + 1}/{len(doc)}...")

        # Convert PDF page → image
        pix = page.get_pixmap(dpi=DPI)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        width, height = img.size

        # Compute pixel positions from percentages
        t = int(height * CROP_CONFIG["top"])
        b = int(height * CROP_CONFIG["bottom"])
        lo = int(width * CROP_CONFIG["left_outer"])
        li = int(width * CROP_CONFIG["left_inner"])
        ri = int(width * CROP_CONFIG["right_inner"])
        ro = int(width * CROP_CONFIG["right_outer"])

        # Define left & right crops using the config
        left_box = (lo, t, li, b)
        right_box = (ri, t, ro, b)

        halves = [
            ("left", img.crop(left_box)),
            ("right", img.crop(right_box))
        ]

        for side, crop_img in halves:
            if DEBUG:
                crop_img.save(f"debug_page{page_idx+1}_{side}.png")

            # Run OCR
            data = pytesseract.image_to_data(
                crop_img, lang="mal+eng", output_type=pytesseract.Output.DATAFRAME
            )
            data = data.dropna(subset=["text"])
            data = data[data.conf > 40]
            if data.empty:
                continue

            # Group roughly by rows
            data["row_id"] = (data["top"] // 100)

            for _, g in data.groupby("row_id"):
                line = " ".join(g["text"])
                if not re.search(r"[A-Z0-9/]{5,}", line):
                    continue

                # Extract fields
                voter_id = re.search(r"[A-Z0-9/]{5,}", line)
                sex_age = re.search(r"[പൂസ്ത്രീFM]/\d{1,3}", line)
                house_no = re.search(r"\d+/\d+", line)
                name_match = re.search(r"[A-Za-zഅ-ഹ]+", line)

                all_voters.append({
                    "VoterID": voter_id.group(0) if voter_id else "",
                    "Name": name_match.group(0) if name_match else "",
                    "HouseNo": house_no.group(0) if house_no else "",
                    "SexAge": sex_age.group(0) if sex_age else "",
                    "Text": line,
                    "Page": page_idx + 1,
                    "Column": side
                })

    # Save to Excel
    df = pd.DataFrame(all_voters)
    df.to_excel(output_xlsx, index=False)
    print(f"\n✅ Done! {len(df)} voters extracted → {output_xlsx}")


# ==============================
# Run directly
# ==============================
if __name__ == "__main__":
    extract_voters_flexible(INPUT_PDF, OUTPUT_XLSX)
