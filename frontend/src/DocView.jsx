import React from "react";

/** Notion の文字(太字・リンク等)を表示 */
export function Rich({ segs }) {
  return (segs || []).map((s, i) => {
    let el = s.t;
    if (s.c) el = <code key={i}>{el}</code>;
    if (s.b) el = <strong key={i}>{el}</strong>;
    if (s.i) el = <em key={i}>{el}</em>;
    if (s.s) el = <s key={i}>{el}</s>;
    if (s.href) el = <a key={i} href={s.href} target="_blank" rel="noreferrer">{el}</a>;
    return <React.Fragment key={i}>{el}</React.Fragment>;
  });
}

function Table({ block }) {
  const rows = block.children || [];
  return (
    <div className="doc-table-wrap">
      <table className="doc-table">
        <tbody>
          {rows.map((r, i) => {
            const Cell = block.header && i === 0 ? "th" : "td";
            return (
              <tr key={i}>
                {(r.cells || []).map((c, j) => <Cell key={j}><Rich segs={c} /></Cell>)}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** 連続するリスト項目をまとめて <ul>/<ol> にする */
function group(blocks) {
  const out = [];
  for (const b of blocks || []) {
    const list = b.type === "bulleted_list_item" ? "ul" : b.type === "numbered_list_item" ? "ol" : null;
    const last = out[out.length - 1];
    if (list && last && last.list === list) last.items.push(b);
    else if (list) out.push({ list, items: [b] });
    else out.push(b);
  }
  return out;
}

export function Blocks({ blocks, onOpenPage }) {
  return group(blocks).map((b, i) => {
    if (b.list) {
      const L = b.list;
      return (
        <L key={i}>
          {b.items.map((it, j) => (
            <li key={j}><Rich segs={it.text} />{it.children && <Blocks blocks={it.children} onOpenPage={onOpenPage} />}</li>
          ))}
        </L>
      );
    }
    const kids = b.children && b.type !== "table" ? <Blocks blocks={b.children} onOpenPage={onOpenPage} /> : null;
    switch (b.type) {
      case "heading_1": return <h2 key={i}><Rich segs={b.text} /></h2>;
      case "heading_2": return <h3 key={i}><Rich segs={b.text} /></h3>;
      case "heading_3": return <h4 key={i}><Rich segs={b.text} /></h4>;
      case "paragraph": return <div key={i}><p><Rich segs={b.text} /></p>{kids}</div>;
      case "to_do":
        return <div key={i} className={`todo ${b.checked ? "done" : ""}`}><span>{b.checked ? "☑" : "☐"}</span><Rich segs={b.text} />{kids}</div>;
      case "callout":
        return <div key={i} className="callout"><span className="callout-icon">{b.icon}</span><div><Rich segs={b.text} />{kids}</div></div>;
      case "quote": return <blockquote key={i}><Rich segs={b.text} />{kids}</blockquote>;
      case "toggle": return <details key={i}><summary><Rich segs={b.text} /></summary>{kids}</details>;
      case "divider": return <hr key={i} />;
      case "code": return <pre key={i}><code><Rich segs={b.text} /></code></pre>;
      case "table": return <Table key={i} block={b} />;
      case "column_list": return <div key={i} className="columns">{kids}</div>;
      case "column": return <div key={i} className="column">{kids}</div>;
      case "child_page":
        return <button key={i} className="child-page" onClick={() => onOpenPage?.(b.page_id)}>📄 <Rich segs={b.text} /></button>;
      case "child_database":
        return <button key={i} className="child-page" onClick={() => onOpenPage?.(b.db_id)}>🗂 <Rich segs={b.text} /> を表で開く</button>;
      case "image": return <figure key={i}><img src={b.url} alt="" /><figcaption><Rich segs={b.text} /></figcaption></figure>;
      case "bookmark": case "embed": case "link_preview": case "file": case "pdf": case "video":
        return b.url ? <a key={i} className="bookmark" href={b.url} target="_blank" rel="noreferrer">🔗 {b.url}</a> : null;
      default: return kids ? <div key={i}>{kids}</div> : null;
    }
  });
}
