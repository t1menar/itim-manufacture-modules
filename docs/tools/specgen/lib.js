// Shared builder for Manufacture spec documents.
// Content is a list of blocks: ['h1', t] ['h2', t] ['h3', t] ['p', t] ['ul', [..]] ['ol', [..]]
// ['table', headers, rows, widths] ['code', text] ['note', text]. Inline: **bold**, `code`.
const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, WidthType, ShadingType,
  BorderStyle, AlignmentType, LevelFormat, HeadingLevel, Header, Footer, PageNumber,
  TabStopType,
} = require('docx');

const FONT = 'Arial';
const MONO = 'Consolas';
const ACCENT = '1F4E79';
const MUTED = '595959';
const LINE = 'BFBFBF';
const HEAD_FILL = 'E8EEF4';
const CODE_FILL = 'F3F3F3';
const NOTE_FILL = 'FFF4E5';
const PAGE_W = 11906, PAGE_H = 16838, MARGIN = 720;      // A4, 0.5" margins
const CONTENT_W = PAGE_W - 2 * MARGIN;                   // 10466 DXA

function runs(text, base = {}) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(new TextRun({ font: FONT, text: text.slice(last, m.index), ...base }));
    const tok = m[0];
    if (tok.startsWith('**')) out.push(new TextRun({ font: FONT, text: tok.slice(2, -2), bold: true, ...base }));
    else out.push(new TextRun({ font: FONT, text: tok.slice(1, -1), font: MONO, size: 18, color: '7A2E0E', ...base }));
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(new TextRun({ font: FONT, text: text.slice(last), ...base }));
  return out;
}

const thin = { style: BorderStyle.SINGLE, size: 4, color: LINE };
const cellBorders = { top: thin, bottom: thin, left: thin, right: thin };

function table(headers, rows, widths) {
  const n = headers.length;
  const fr = widths || Array(n).fill(1 / n);
  const sum = fr.reduce((a, b) => a + b, 0);
  let cols = fr.map(f => Math.floor(CONTENT_W * f / sum));
  cols[n - 1] += CONTENT_W - cols.reduce((a, b) => a + b, 0);
  const mk = (t, i, head) => new TableCell({
    width: { size: cols[i], type: WidthType.DXA },
    borders: cellBorders,
    shading: head ? { fill: HEAD_FILL, type: ShadingType.CLEAR, color: 'auto' } : undefined,
    margins: { top: 50, bottom: 50, left: 90, right: 90 },
    children: String(t).split('\n').map(line => new Paragraph({
      spacing: { before: 0, after: 0, line: 252 },
      children: runs(line, head ? { bold: true, size: 18 } : { size: 18 }),
    })),
  });
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: cols,
    rows: [
      new TableRow({ tableHeader: true, children: headers.map((h, i) => mk(h, i, true)) }),
      ...rows.map(r => new TableRow({ cantSplit: true, children: r.map((c, i) => mk(c, i, false)) })),
    ],
  });
}

function build(meta, blocks, outFile) {
  let olCount = 0;
  const numbering = [{
    reference: 'bullets',
    levels: [
      { level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 360, hanging: 240 } } } },
      { level: 1, format: LevelFormat.BULLET, text: '–', alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 720, hanging: 240 } } } },
    ],
  }];
  const children = [];
  // Title block
  children.push(new Paragraph({ spacing: { before: 0, after: 40 },
    children: [new TextRun({ font: FONT, text: 'MANUFACTURE · SPECIFICATION', font: FONT, size: 16, bold: true, color: MUTED, characterSpacing: 40 })] }));
  children.push(new Paragraph({ heading: HeadingLevel.TITLE, children: [new TextRun({ font: FONT, text: meta.title })] }));
  if (meta.subtitle) children.push(new Paragraph({ spacing: { before: 0, after: 120 },
    children: [new TextRun({ font: FONT, text: meta.subtitle, size: 22, color: MUTED })] }));
  children.push(table(['Document', 'Version', 'Status', 'Date', 'Owner'],
    [[meta.doc, meta.version || '0.1', meta.status || 'Draft', meta.date || '2026-11-08', 'Timur']],
    [3, 1, 1, 1.2, 1.2]));
  if (meta.toc !== false) {
    children.push(new Paragraph({ spacing: { before: 160, after: 60 },
      children: [new TextRun({ font: FONT, text: 'Contents', bold: true, size: 22, color: ACCENT })] }));
    const h1s = blocks.filter(b => b[0] === 'h1').map(b => b[1]);
    const half = Math.ceil(h1s.length / 2);
    const col = list => list.join('\n');
    children.push(new Table({
      width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: [CONTENT_W / 2, CONTENT_W / 2],
      borders: { top: { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' }, bottom: { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' },
        left: { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' }, right: { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' },
        insideHorizontal: { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' }, insideVertical: { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' } },
      rows: [new TableRow({ children: [h1s.slice(0, half), h1s.slice(half)].map(part => new TableCell({
        width: { size: CONTENT_W / 2, type: WidthType.DXA },
        borders: { top: { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' }, bottom: { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' },
          left: { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' }, right: { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' } },
        children: part.length ? part.map(t => new Paragraph({ spacing: { after: 20 }, children: [new TextRun({ font: FONT, text: t, size: 18 })] }))
                              : [new Paragraph({ children: [] })],
      })) })],
    }));
  }
  for (const b of blocks) {
    const [k, a, c, d] = b;
    if (k === 'h1') children.push(new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun({ font: FONT, text: a })] }));
    else if (k === 'h2') children.push(new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun({ font: FONT, text: a })] }));
    else if (k === 'h3') children.push(new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun({ font: FONT, text: a })] }));
    else if (k === 'p') children.push(new Paragraph({ children: runs(a) }));
    else if (k === 'ul') for (const it of a) {
      const lvl = it.startsWith('  ') ? 1 : 0;
      children.push(new Paragraph({ numbering: { reference: 'bullets', level: lvl }, spacing: { after: 40 }, children: runs(it.trim()) }));
    }
    else if (k === 'ol') {
      const ref = 'ol' + (++olCount);
      numbering.push({ reference: ref, levels: [{ level: 0, format: LevelFormat.DECIMAL, text: '%1.', alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 360, hanging: 300 } } } }] });
      for (const it of a) children.push(new Paragraph({ numbering: { reference: ref, level: 0 }, spacing: { after: 40 }, children: runs(it) }));
    }
    else if (k === 'table') { children.push(table(a, c, d)); children.push(new Paragraph({ spacing: { before: 0, after: 60 }, children: [] })); }
    else if (k === 'code') {
      const lines = a.split('\n');
      lines.forEach((ln, i) => children.push(new Paragraph({
        shading: { fill: CODE_FILL, type: ShadingType.CLEAR, color: 'auto' },
        spacing: { before: i === 0 ? 60 : 0, after: i === lines.length - 1 ? 120 : 0, line: 240 },
        indent: { left: 120, right: 120 },
        children: [new TextRun({ font: FONT, text: ln.length ? ln : ' ', font: MONO, size: 17 })],
      })));
    }
    else if (k === 'note') children.push(new Paragraph({
      shading: { fill: NOTE_FILL, type: ShadingType.CLEAR, color: 'auto' },
      border: { left: { style: BorderStyle.SINGLE, size: 18, color: 'E08A00', space: 6 } },
      indent: { left: 120, right: 120 }, spacing: { before: 80, after: 120 },
      children: runs(a),
    }));
    else throw new Error('unknown block ' + k);
  }
  const H = (size, before, after, color = ACCENT) => ({
    run: { font: FONT, size, bold: true, color },
    paragraph: { spacing: { before, after }, keepNext: true, keepLines: true },
  });
  const doc = new Document({
    creator: 'Manufacture', title: meta.title, description: meta.doc,

    styles: {
      default: { document: { run: { font: FONT, size: 20 }, paragraph: { spacing: { after: 80, line: 264 } } } },
      paragraphStyles: [
        { id: 'Title', name: 'Title', basedOn: 'Normal', next: 'Normal', quickFormat: true, ...H(36, 0, 40, '1A1A1A') },
        { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true,
          run: { font: FONT, size: 28, bold: true, color: ACCENT },
          paragraph: { spacing: { before: 240, after: 80 }, keepNext: true, keepLines: true, outlineLevel: 0,
            border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: 'C9D6E3', space: 2 } } } },
        { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true, ...H(23, 180, 60), },
        { id: 'Heading3', name: 'Heading 3', basedOn: 'Normal', next: 'Normal', quickFormat: true, ...H(20, 120, 40, '262626') },
      ],
    },
    numbering: { config: numbering },
    sections: [{
      properties: { page: { size: { width: PAGE_W, height: PAGE_H }, margin: { top: MARGIN, bottom: MARGIN, left: MARGIN, right: MARGIN, header: 360, footer: 360 } } },
      headers: { default: new Header({ children: [new Paragraph({
        tabStops: [{ type: TabStopType.RIGHT, position: CONTENT_W }],
        border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: LINE, space: 2 } },
        children: [new TextRun({ font: FONT, text: 'Manufacture', size: 16, color: MUTED, bold: true }),
                   new TextRun({ font: FONT, text: '\t' + meta.doc, size: 16, color: MUTED })] })] }) },
      footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.RIGHT,
        children: [new TextRun({ font: FONT, text: 'Page ', size: 16, color: MUTED }), new TextRun({ children: [PageNumber.CURRENT], size: 16, color: MUTED }),
                   new TextRun({ font: FONT, text: ' of ', size: 16, color: MUTED }), new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 16, color: MUTED })] })] }) },
      children,
    }],
  });
  fs.mkdirSync(path.dirname(outFile), { recursive: true });
  return Packer.toBuffer(doc).then(buf => { fs.writeFileSync(outFile, buf); console.log('wrote', outFile); });
}

module.exports = { build };
