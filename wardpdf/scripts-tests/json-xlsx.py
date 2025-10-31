import pdfplumber
import pytesseract
import cv2
import json
import numpy as np
from pdf2image import convert_from_path

# Path to PDF file
pdf_path = "ward 17.pdf"

# Configure Tesseract for Malayalam OCR
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
custom_oem_psm_config = '--psm 6 -l mal'

# Convert PDF pages to images (skip first page)
pages = convert_from_path(pdf_path, dpi=300)[1:]

voter_data = []

for page_num, page_image in enumerate(pages, start=2):
    # Convert PIL image to OpenCV format
    img = np.array(page_image)
    img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

    # Convert to grayscale and detect edges
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edged = cv2.Canny(gray, 50, 150)

    # Find contours (rectangular boxes)
    contours, _ = cv2.findContours(edged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = [cv2.boundingRect(c) for c in contours if cv2.contourArea(c) > 5000]

    # Sort boxes top-to-bottom, left-to-right
    boxes = sorted(boxes, key=lambda b: (b[1], b[0]))

    for i, (x, y, w, h) in enumerate(boxes[:20]):  # first 20 boxes per page
        roi = img[y:y+h, x:x+w]
        text = pytesseract.image_to_string(roi, config=custom_oem_psm_config)

        # Clean and parse Malayalam text
        voter_id = None
        name = None
        relation = None
        house_no = None
        house_name = None
        sex_age = None

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for line in lines:
            if 'ീ' in line or 'ID' in line:
                voter_id = line.strip()
            elif 'േപര്' in line:
                name = line.replace('േപര്:', '').strip()
            elif 'ഭർാവ്' in line or 'അൻ' in line or 'അ' in line:
                relation = line.strip()
            elif 'വീ നർ' in line:
                house_no = line.replace('വീ നർ:', '').strip()
            elif 'വീ േപര്' in line:
                house_name = line.replace('വീ േപര്:', '').strip()
            elif '/' in line and any(ch.isdigit() for ch in line):
                sex_age = line.strip()

        voter_data.append({
            "page": page_num,
            "voter_id": voter_id,
            "name": name,
            "relation": relation,
            "house_no": house_no,
            "house_name": house_name,
            "sex_age": sex_age
        })

# Save as JSON
with open("voters_data.json", "w", encoding="utf-8") as f:
    json.dump(voter_data, f, ensure_ascii=False, indent=2)

print("✅ Extracted data saved to voters_data.json")
