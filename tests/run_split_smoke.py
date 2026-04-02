import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from internal.services.circle_ui import OutputBubble

cases = [
    ("Here is an image: ![alt](https://example.com/pic.png) and another https://example.com/photo.jpg ending.",
     [('text', True), ('image', True), ('text', True), ('image', True)]),
    ("No images here, just text.", [('text', True)]),
    ("Before ![Alt text](https://example.com/ix.png \"A title\"){width=240} after",
     [('text', True), ('image', 240), ('text', True)]),
    ("Here ![a](https://example.com/a.jpg =300) end", [('text', True), ('image', 300), ('text', True)]),
]

for text, expect in cases:
    parts = OutputBubble._split_images(None, text)
    print('TEXT:', text)
    for p in parts:
        print('  PART:', p)
    print('---')

print('Smoke run done')
