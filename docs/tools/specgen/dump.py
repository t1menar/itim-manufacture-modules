#!/usr/bin/env python3
"""Print the plain text of a .docx (one paragraph per line) to check a built spec."""
import re, sys, zipfile
xml = zipfile.ZipFile(sys.argv[1]).read('word/document.xml').decode('utf-8')
for p in re.findall(r'<w:p[ >].*?</w:p>', xml, re.S):
    t = ''.join(re.findall(r'<w:t[^>]*>(.*?)</w:t>', p, re.S))
    if t: print(t.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&apos;', "'"))
