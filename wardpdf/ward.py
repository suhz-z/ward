"""
oter box filter -left-side OCR optimization
Detects voter boxes using PyMuPDF get_drawings(),
OCRs only the left half of each box for speed
but saves the full rectangle if the house number matches
debug 

"""

import fitz
from PIL import Image
import numpy as np
import pytesseract
import io, re


INPUT_PDF = "ward 17.pdf"
OUTPUT_PDF = "filtered_output.pdf"
dpi = 400  #pixel
DEFAULT_PAD = (5, 10, 5, 15)  # (left, top, right, bottom)


house_no_input = input("Enter a single house number (e.g. 15/350): ").strip().replace(" ", "")
if not house_no_input:
    print("⚠️ You must enter a house number.")
    exit()

print(f"\n🔍 Filtering for house number: {house_no_input}\n")

HOUSE_RE = re.compile(r"(\d{1,3}\s*/\s*\d{1,4})")
TESSERACT_CONFIG = r"--oem 1 --psm 6"  # fast OCR config

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

def main():
    doc = fitz.open(INPUT_PDF)
    pages = len(doc)
    print(f"Opened PDF: {INPUT_PDF}, pages: {pages}")

    collected = []

    for page_idx in range(1, pages):  # skip 
        page = doc[page_idx]

        # skip pages not containing the house prefix
        prefix = house_no_input.split("/")[0] + "/"
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

            # only left half for OCR
            w_box = ex1 - ex0
            sub_x0 = ex0
            sub_x1 = int(ex0 + w_box * 0.5)
            sub_crop = img_arr[ey0:ey1, sub_x0:sub_x1]

            ocr = ocr_text_from_image(sub_crop)
            matches = [m.replace(" ", "") for m in HOUSE_RE.findall(ocr)]

            if house_no_input in matches:
                print(f" page {page_idx+1:02}, rect {idx:02}: {matches} ->  found {house_no_input}")
                collected.append((page_idx, full_crop))
            elif matches:
                print(f" page {page_idx+1:02}, rect {idx:02}: {matches} -> not found")
            else:
                print(f" page {page_idx+1:02}, rect {idx:02}: no match")

    print(f"\n Total collected boxes for {house_no_input}: {len(collected)}")

    if not collected:
        print(" No matches found — check OCR output or house number formatting.")
        return

    out_doc = fitz.open()
    page_width, page_height = 595, 842  # A4 in points
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

    out_doc.save(OUTPUT_PDF)
    out_doc.close()
    print(f"\n Output PDF saved: {OUTPUT_PDF}")

    doc.close()

if __name__ == "__main__":
    main()
