import os
from PIL import Image
import pytesseract

img_path = r"C:\manish\SchoolOfAI\session9\S9SharedCode\code\state\artifacts\screenshots\s8-657e45b3_a11y_turn_01_raw.png"
if os.path.exists(img_path):
    # Try basic OCR to see what's on the screen
    try:
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
        text = pytesseract.image_to_string(Image.open(img_path))
        print("OCR TEXT:", text[:500])
    except Exception as e:
        print("OCR failed:", e)
else:
    print("File not found.")
