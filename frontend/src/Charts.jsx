import React, { useEffect, useRef, useState } from "react";

/* 媒体の色は固定(並び順で塗り替えない)。暗い面 #151a31 で色覚多様性チェック済み */
export const PLATFORM_COLORS = { instagram: "#3987e5", x: "#d95926", threads: "#199e70", note: "#c98500" };

function useWidth() {
  const ref = useRef(null);
  const [w, setW] = useState(520);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(240, Math.floor(e.contentRect.width))));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

const md = (d) => { const [, m, day] = d.split("-"); return `${Number(m)}/${Number(day)}`; };
const dayNum = (d) => Math.round(new Date(d + "T00:00:00").getTime() / 86400000);

function niceMax(v) {
  if (v <= 0) return 10;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  return [1, 2, 2.5, 5, 10].map((m) => m * p).find((x) => x >= v);
}

/**
 * 折れ線グラフ(1本の縦軸)。series: [{ key, label, color, points: [{ date, value }] }]
 * なぞると縦線と、その日の値の吹き出しが出る。2系列以上は凡例+線の端にラベル。
 */
export function LineChart({ series, height = 180, format = (v) => v.toLocaleString(), unit = "" }) {
  const [ref, width] = useWidth();
  const [hover, setHover] = useState(null);
  const pad = { l: 44, r: series.length > 1 ? 74 : 16, t: 12, b: 24 };
  const all = series.flatMap((s) => s.points);
  if (!all.length) return <div ref={ref} />;
  const days = all.map((p) => dayNum(p.date));
  let x0 = Math.min(...days), x1 = Math.max(...days);
  if (x0 === x1) { x0 -= 3; x1 += 3; }
  const yMax = niceMax(Math.max(...all.map((p) => p.value)));
  const iw = width - pad.l - pad.r, ih = height - pad.t - pad.b;
  const X = (d) => pad.l + ((dayNum(d) - x0) / (x1 - x0)) * iw;
  const Y = (v) => pad.t + ih - (v / yMax) * ih;
  const ticks = [0, yMax / 2, yMax];
  const dates = [...new Set(all.map((p) => p.date))].sort();
  // 線の端のラベルが重ならないよう、縦に12px以上あける
  const labelY = {};
  [...series].map((s) => ({ k: s.key, y: Y(s.points[s.points.length - 1].value) + 4 }))
    .sort((a, b) => a.y - b.y)
    .forEach((l, i, arr) => { if (i && l.y - arr[i - 1].y < 12) l.y = arr[i - 1].y + 12; labelY[l.k] = l.y; });

  const onMove = (e) => {
    const box = e.currentTarget.getBoundingClientRect();
    const mx = e.clientX - box.left;
    let best = dates[0];
    for (const d of dates) if (Math.abs(X(d) - mx) < Math.abs(X(best) - mx)) best = d;
    setHover(best);
  };
  const hoverRows = hover ? series.map((s) => ({ s, p: [...s.points].reverse().find((p) => p.date <= hover) })).filter((r) => r.p) : [];

  return (
    <div className="chart" ref={ref}>
      {series.length > 1 && (
        <div className="legend">
          {series.map((s) => <span key={s.key}><i style={{ background: s.color }} />{s.label}</span>)}
        </div>
      )}
      <svg width={width} height={height} onPointerMove={onMove} onPointerLeave={() => setHover(null)} role="img"
           aria-label={series.map((s) => `${s.label} 最新 ${format(s.points[s.points.length - 1].value)}${unit}`).join("、")}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={width - pad.r} y1={Y(t)} y2={Y(t)} className="grid" />
            <text x={pad.l - 6} y={Y(t) + 4} textAnchor="end" className="axis">{format(t)}</text>
          </g>
        ))}
        <text x={pad.l} y={height - 6} className="axis">{md(dates[0])}</text>
        {dates.length > 1 && <text x={width - pad.r} y={height - 6} textAnchor="end" className="axis">{md(dates[dates.length - 1])}</text>}
        {hover && <line x1={X(hover)} x2={X(hover)} y1={pad.t} y2={pad.t + ih} className="crosshair" />}
        {series.map((s) => {
          const d = s.points.map((p, i) => `${i ? "L" : "M"}${X(p.date).toFixed(1)},${Y(p.value).toFixed(1)}`).join("");
          const last = s.points[s.points.length - 1];
          return (
            <g key={s.key}>
              <path d={d} fill="none" stroke={s.color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
              <circle cx={X(last.date)} cy={Y(last.value)} r="4" fill={s.color} stroke="var(--panel)" strokeWidth="2" />
              {series.length > 1 && (
                <text x={X(last.date) + 8} y={labelY[s.key]} className="end-label">{s.label} {format(last.value)}</text>
              )}
            </g>
          );
        })}
        {hoverRows.map(({ s, p }) => (
          <circle key={s.key} cx={X(p.date)} cy={Y(p.value)} r="4" fill={s.color} stroke="var(--panel)" strokeWidth="2" />
        ))}
      </svg>
      {hover && hoverRows.length > 0 && (
        <div className="tip" style={{ left: Math.min(X(hover) + 10, width - 150) }}>
          <div className="tip-date">{md(hover)}</div>
          {hoverRows.map(({ s, p }) => (
            <div key={s.key} className="tip-row"><i style={{ background: s.color }} />{s.label}<b>{format(p.value)}{unit}</b></div>
          ))}
        </div>
      )}
    </div>
  );
}
