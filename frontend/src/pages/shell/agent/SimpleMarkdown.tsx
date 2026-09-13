import type { ReactNode } from 'react';

function splitBlocks(text: string) {
  const chunks: Array<{ type: 'code' | 'text'; lang?: string; body: string }> = [];
  const parts = (text || '').split(/```/);
  parts.forEach((part, index) => {
    if (index % 2 === 1) {
      const nl = part.indexOf('\n');
      const lang = nl >= 0 ? part.slice(0, nl).trim() : '';
      const body = nl >= 0 ? part.slice(nl + 1) : part;
      chunks.push({ type: 'code', lang, body: body.replace(/\n$/, '') });
    } else if (part) {
      chunks.push({ type: 'text', body: part });
    }
  });
  return chunks;
}

function inline(text: string) {
  const nodes: Array<string | { code: string }> = [];
  const re = /`([^`]+)`/g;
  let last = 0;
  let match: RegExpExecArray | null;
  while ((match = re.exec(text))) {
    if (match.index > last) nodes.push(text.slice(last, match.index));
    nodes.push({ code: match[1] });
    last = match.index + match[0].length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes.map((item, index) => (
    typeof item === 'string'
      ? <span key={index}>{item}</span>
      : <code key={index}>{item.code}</code>
  ));
}

function renderText(body: string) {
  const lines = body.split('\n');
  const blocks: ReactNode[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i += 1;
      continue;
    }
    if (line.startsWith('> ')) {
      const quote: string[] = [];
      while (i < lines.length && lines[i].startsWith('> ')) {
        quote.push(lines[i].slice(2));
        i += 1;
      }
      blocks.push(<blockquote key={`q-${i}`}>{quote.join('\n')}</blockquote>);
      continue;
    }
    if (line.includes('|') && i + 1 < lines.length && /^\s*\|?\s*-+/.test(lines[i + 1])) {
      const header = line.split('|').map((cell) => cell.trim()).filter(Boolean);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].includes('|')) {
        rows.push(lines[i].split('|').map((cell) => cell.trim()).filter(Boolean));
        i += 1;
      }
      blocks.push(
        <table key={`t-${i}`}>
          <thead><tr>{header.map((cell) => <th key={cell}>{cell}</th>)}</tr></thead>
          <tbody>{rows.map((row, ri) => <tr key={ri}>{row.map((cell, ci) => <td key={ci}>{cell}</td>)}</tr>)}</tbody>
        </table>,
      );
      continue;
    }
    if (/^\s*[-*]\s+/.test(line) || /^\s*\d+\.\s+/.test(line)) {
      const items: string[] = [];
      const ordered = /^\s*\d+\.\s+/.test(line);
      while (i < lines.length && (/^\s*[-*]\s+/.test(lines[i]) || /^\s*\d+\.\s+/.test(lines[i]))) {
        items.push(lines[i].replace(/^\s*[-*]\s+/, '').replace(/^\s*\d+\.\s+/, ''));
        i += 1;
      }
      const Tag = ordered ? 'ol' : 'ul';
      blocks.push(<Tag key={`l-${i}`}>{items.map((item, index) => <li key={index}>{inline(item)}</li>)}</Tag>);
      continue;
    }
    blocks.push(<p key={`p-${i}`}>{inline(line)}</p>);
    i += 1;
  }
  return blocks;
}

export default function SimpleMarkdown({ text }: { text: string }) {
  return (
    <div className="agent-md">
      {splitBlocks(text).map((chunk, index) => (
        chunk.type === 'code'
          ? <pre key={index} className="agent-md-code"><code>{chunk.body}</code></pre>
          : <div key={index}>{renderText(chunk.body)}</div>
      ))}
    </div>
  );
}
