import pytesseract, numpy as np, re

TESSERACT_CONFIG = r"--oem 1 --psm 6"

def ocr_text_from_image(np_img):
    try:
        return pytesseract.image_to_string(np_img, lang="mal+eng", config=TESSERACT_CONFIG)
    except Exception:
        return pytesseract.image_to_string(np_img, config=TESSERACT_CONFIG)

def expand_rect_px(x, y, w, h, img_w, img_h, pad=(5,10,5,20)):
    l, t, r, b = pad
    return max(0,x-l), max(0,y-t), min(img_w,x+w+r), min(img_h,y+h+b)
