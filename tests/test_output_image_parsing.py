from internal.services.circle_ui import OutputBubble


def test_split_images_markdown_and_urls():
    text = "Here is an image: ![alt](https://example.com/pic.png) and another https://example.com/photo.jpg ending."
    parts = OutputBubble._split_images(None, text)
    assert parts[0][0] == 'text' and 'Here is an image' in parts[0][1]
    assert parts[1][0] == 'image' and parts[1][1].endswith('pic.png') and parts[1][3] is None
    assert parts[2][0] == 'text' and 'and another' in parts[2][1]
    assert parts[3][0] == 'image' and parts[3][1].endswith('photo.jpg') and parts[3][3] is None


def test_split_images_only_text():
    text = "No images here, just text."
    parts = OutputBubble._split_images(None, text)
    assert len(parts) == 1 and parts[0][0] == 'text' and 'No images' in parts[0][1]


def test_md_image_with_title_and_width_brace():
    text = "Before ![Alt text](https://example.com/ix.png \"A title\"){width=240} after"
    parts = OutputBubble._split_images(None, text)
    assert parts[0][0] == 'text' and 'Before' in parts[0][1]
    assert parts[1][0] == 'image' and parts[1][1].endswith('ix.png') and parts[1][2] == 'Alt text' and parts[1][3] == 240
    assert parts[2][0] == 'text' and 'after' in parts[2][1]


def test_md_image_with_eq_width_inside_parentheses():
    text = "Here ![a](https://example.com/a.jpg =300) end"
    parts = OutputBubble._split_images(None, text)
    assert parts[1][0] == 'image' and parts[1][1].endswith('a.jpg') and parts[1][3] == 300
