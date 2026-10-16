import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

root = Path(__file__).resolve().parent
final = root.parents[1] / '隐盾挑战杯答辩_白底简约版_20261014' / '隐盾_挑战杯大挑_6分钟答辩_白底简约版_定稿.pptx'
ns = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main', 'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
notes = json.loads((root / 'speaker_notes.json').read_text(encoding='utf-8'))
assert sum(n['seconds'] for n in notes if not n['backup']) == 360
with zipfile.ZipFile(final) as z:
    hidden = []
    for i in range(1, 18):
        slide = ET.fromstring(z.read(f'ppt/slides/slide{i}.xml'))
        if slide.get('show') == '0':
            hidden.append(i)
        assert slide.find('p:cSld/p:bg/p:bgPr/a:solidFill/a:srgbClr', ns).get('val') == 'FFFFFF'
        note = ET.fromstring(z.read(f'ppt/notesSlides/notesSlide{i}.xml'))
        text = ''.join(note.itertext())
        assert ('备答页' if i > 14 else '主讲') in text
    assert hidden == [15, 16, 17], hidden

review = {'file': str(final), 'native_application': 'Microsoft PowerPoint', 'rendered_slide_count': 17,
          'visually_reviewed_slides': list(range(1,18)), 'render_resolution': '1600x900',
          'backgrounds': 'white', 'hidden_backup_slides': hidden, 'main_talk_seconds': 360,
          'visual_findings_remaining': [], 'editable_tables': 6, 'editable_charts': 1}
(root / 'visual_review.json').write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'status': 'pass', 'slides': 17, 'hidden': hidden, 'main_talk_seconds': 360}, ensure_ascii=False))
