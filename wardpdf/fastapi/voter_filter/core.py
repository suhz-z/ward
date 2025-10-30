import fitz
import io
from PIL import Image
import numpy as np
from .helper import ocr_text_from_image, expand_rect_px
from .settings import dpi, DEFAULT_PAD, HOUSE_RE

def filter_pdf_for_house(input_pdf, output_pdf, house_no):
    house_no = house_no.strip().replace(" ", "")
    doc = fitz.open(input_pdf)
    collected = []

    for page_idx in range(1, len(doc)):
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
            ex0, ey0, ex1, ey1 = expand_rect_px(x0, y0, x1-x0, y1-y0, w_img, h_img, DEFAULT_PAD)
            full_crop = img_arr[ey0:ey1, ex0:ex1]
            sub_crop = img_arr[ey0:ey1, ex0:int(ex0+(ex1-ex0)*0.5)]
            ocr = ocr_text_from_image(sub_crop)
            matches = [m.replace(" ", "") for m in HOUSE_RE.findall(ocr)]
            if house_no in matches:
                collected.append((page_idx, full_crop))

    # build PDF output
    out_doc = fitz.open()
    page_width, page_height = 595, 842
    boxes_per_row, boxes_per_page = 2, 20
    voter_width = page_width // boxes_per_row
    voter_height = page_height // (boxes_per_page // boxes_per_row)
    count = 0

    for page_idx, crop in collected:
        if count % boxes_per_page == 0:
            page = out_doc.new_page(width=page_width, height=page_height)
            x_pt, y_pt = 0, 0
        pil = Image.fromarray(crop).resize((int(voter_width - 10), int(voter_height - 10)))
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        rect = fitz.Rect(x_pt+5, y_pt+5, x_pt+voter_width-5, y_pt+voter_height-5)
        page.insert_image(rect, stream=buf.getvalue())
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
