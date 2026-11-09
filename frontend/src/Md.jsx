import React from "react";

/**
 * かんたんなマークダウン表示(AIの返答や部署の文書を読みやすく)。
 * 見出し・箇条書き・番号つき・表・引用・コード・区切り線・太字・コード・リンクに対応。
 * HTML として流し込まない(React の要素で組み立てる)ので、文書の中に何が書いてあっても安全。
 */
function inline(text, key = "i") {
  const out = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\((https?:\/\/[^)\s]+)\)|https?:\/\/[^\s)」』]+)/g;
  let last = 0, m, n = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const t = m[0];
    if (t.startsWith("**")) out.push(<strong key={`${key}${n++}`}>{t.slice(2, -2)}</strong>);
    else if (t.startsWith("`")) out.push(<code key={`${key}${n++}`}>{t.slice(1, -1)}</code>);
    else if (t.startsWith("[")) { const lab = t.slice(1, t.indexOf("](")); out.push(<a key={`${key}${n++}`} href={m[2]} target="_blank" rel="noreferrer">{lab}</a>); }
    else out.push(<a key={`${key}${n++}`} href={t} target="_blank" rel="noreferrer">{t}</a>);
    last = m.index + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

const isTableRow = (l) => /^\s*\|.*\|\s*$/.test(l);
const isSep = (l) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(l);
const cells = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());

export default function Md({ text, className = "" }) {
  const lines = (text || "").replace(/\r/g, "").split("\n");
  const blocks = [];
  let i = 0, k = 0;
  while (i < lines.length) {
    const l = lines[i];
    if (!l.trim()) { i++; continue; }
    if (/^```/.test(l.trim())) { // コード
      const body = []; i++;
      while (i < lines.length && !/^```/.test(lines[i].trim())) body.push(lines[i++]);
      i++; blocks.push(<pre key={k++} className="md-code"><code>{body.join("\n")}</code></pre>); continue;
    }
    const h = l.match(/^(#{1,4})\s+(.*)$/);
    if (h) { const T = `h${Math.min(h[1].length + 2, 6)}`; blocks.push(<T key={k++} className="md-h">{inline(h[2], `h${k}`)}</T>); i++; continue; }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(l)) { blocks.push(<hr key={k++} />); i++; continue; }
    if (isTableRow(l)) { // 表
      const rows = [];
      while (i < lines.length && isTableRow(lines[i])) rows.push(lines[i++]);
      const head = rows.length > 1 && isSep(rows[1]) ? cells(rows[0]) : null;
      const body = (head ? rows.slice(2) : rows).filter((r) => !isSep(r)).map(cells);
      blocks.push(
        <div key={k++} className="md-table-wrap"><table className="md-table">
          {head && <thead><tr>{head.map((c, j) => <th key={j}>{inline(c, `th${k}${j}`)}</th>)}</tr></thead>}
          <tbody>{body.map((r, ri) => <tr key={ri}>{r.map((c, j) => <td key={j}>{inline(c, `td${k}${ri}${j}`)}</td>)}</tr>)}</tbody>
        </table></div>);
      continue;
    }
    if (/^\s*>/.test(l)) { // 引用
      const q = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) q.push(lines[i++].replace(/^\s*>\s?/, ""));
      blocks.push(<blockquote key={k++} className="md-quote">{q.map((x, j) => <div key={j}>{inline(x, `q${k}${j}`)}</div>)}</blockquote>);
      continue;
    }
    const li = l.match(/^(\s*)([-*・]|\d+[.)])\s+(.*)$/);
    if (li) { // 箇条書き・番号つき(字下げで1段だけ入れ子)
      const ordered = /\d/.test(li[2]);
      const items = [];
      while (i < lines.length) {
        const m = lines[i].match(/^(\s*)([-*・]|\d+[.)])\s+(.*)$/);
        if (!m) {
          if (lines[i].trim() && /^\s{2,}/.test(lines[i]) && items.length) { items[items.length - 1].more.push(lines[i].trim()); i++; continue; }
          break;
        }
        const sub = m[1].length >= 2 && items.length;
        if (sub) items[items.length - 1].kids.push(m[3]); else items.push({ t: m[3], kids: [], more: [] });
        i++;
      }
      const L = ordered ? "ol" : "ul";
      blocks.push(<L key={k++} className="md-list">{items.map((it, j) => (
        <li key={j}>{inline(it.t, `l${k}${j}`)}{it.more.map((x, xi) => <div key={xi}>{inline(x, `m${k}${j}${xi}`)}</div>)}
          {it.kids.length > 0 && <ul>{it.kids.map((c, ci) => <li key={ci}>{inline(c, `c${k}${j}${ci}`)}</li>)}</ul>}</li>))}</L>);
      continue;
    }
    // 段落: 空行までをひとまとまりに。行の区切りはそのまま改行で出す
    const para = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|\s*>|\s*(-{3,}|\*{3,})\s*$)/.test(lines[i]) && !isTableRow(lines[i]) && !/^(\s*)([-*・]|\d+[.)])\s+/.test(lines[i])) para.push(lines[i++]);
    blocks.push(<p key={k++} className="md-p">{para.map((x, j) => <React.Fragment key={j}>{j > 0 && <br />}{inline(x, `p${k}${j}`)}</React.Fragment>)}</p>);
  }
  return <div className={`md ${className}`}>{blocks}</div>;
}
