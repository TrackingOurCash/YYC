// Shared helpers for the Calgary dashboard pages: formatting, safe DOM
// building, one tooltip, and the two chart forms the pages use.
window.YYC = (() => {
  const $ = (id) => document.getElementById(id);

  function money(v) {
    const a = Math.abs(v);
    const s = a >= 1e9 ? `${(a / 1e9).toFixed(2)}B` : a >= 1e6 ? `${(a / 1e6).toFixed(1)}M` : a >= 1e3 ? `${Math.round(a / 1e3)}K` : `${Math.round(a)}`;
    return (v < 0 ? "−$" : "$") + s.replace(/\.0+(?=[MB])/, "");
  }
  const moneyFull = (v) => (v == null ? "–" : "$" + Math.round(v).toLocaleString("en-CA"));
  const num = (v) => v.toLocaleString("en-CA");
  const pct = (v) => `${(v * 100).toFixed(v < 0.1 ? 1 : 0)}%`;
  const monthName = (m) => new Date(m + "-15").toLocaleDateString("en-CA", { month: "short", year: "numeric" });
  const dayName = (d) => (d ? new Date(d.slice(0, 10) + "T12:00").toLocaleDateString("en-CA", { month: "short", day: "numeric", year: "numeric" }) : "–");

  // Labels come from City data, so text always goes in via textContent.
  function el(tag, props = {}, text) {
    const n = document.createElement(tag);
    Object.assign(n, props);
    if (text != null) n.textContent = text;
    return n;
  }
  function svgEl(tag, attrs = {}) {
    const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    return n;
  }

  // One tooltip per page. Rows are [label, value]; the value leads.
  let tip;
  function showTip(evt, title, rows) {
    if (!tip) {
      tip = el("div", { id: "tip", role: "tooltip" });
      document.body.append(tip);
    }
    tip.replaceChildren(el("div", { className: "t" }, title), ...rows.map(([k, v]) => {
      const r = el("div", { className: "r" });
      r.append(el("span", {}, k), el("b", {}, v));
      return r;
    }));
    tip.style.display = "block";
    const box = evt.currentTarget.getBoundingClientRect();
    const x = evt.clientX || box.left + box.width / 2;
    const y = evt.clientY || box.top;
    tip.style.left = Math.min(window.innerWidth - tip.offsetWidth - 8, Math.max(8, x + 12)) + "px";
    tip.style.top = Math.max(8, y - tip.offsetHeight - 12) + "px";
  }
  function hover(node, title, rows) {
    node.tabIndex = 0;
    for (const e of ["pointermove", "focus"]) node.addEventListener(e, (evt) => showTip(evt, title, rows()));
    for (const e of ["pointerleave", "blur"]) node.addEventListener(e, () => tip && (tip.style.display = "none"));
  }

  // Horizontal bars as HTML rows: [{name, value, tip: () => rows}].
  function hbars(host, items, { format = money, empty = "Nothing matches these filters." } = {}) {
    host.replaceChildren();
    if (!items.length) {
      host.append(el("div", { className: "empty" }, empty));
      return;
    }
    const max = Math.max(1, ...items.map((d) => d.value));
    for (const d of items) {
      const row = el("div", { className: "hbar" });
      const track = el("div", { className: "track" });
      const fill = el("div", { className: "fill" });
      fill.style.width = (100 * Math.max(0, d.value) / max) + "%";
      track.append(fill);
      row.append(el("div", { className: "name", title: d.name }, d.name), track, el("div", { className: "val" }, format(d.value)));
      row.setAttribute("aria-label", `${d.name}: ${format(d.value)}`);
      if (d.tip) hover(row, d.name, d.tip);
      host.append(row);
    }
  }

  // Columns in an SVG: one category per x, series stacked or side by side.
  // series: [{label, color, values: [...]}]; values may be null (no data).
  function columns(svg, cats, series, { stacked = false, format = num, catLabel = String, height = 240 } = {}) {
    svg.replaceChildren();
    const W = svg.clientWidth || 360, H = height, L = 56, R = 8, T = 20, B = 26;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("height", H);
    const totals = cats.map((_, i) => stacked
      ? series.reduce((s, se) => s + (se.values[i] || 0), 0)
      : Math.max(0, ...series.map((se) => se.values[i] || 0)));
    const maxV = Math.max(1, ...totals);
    const mag = Math.pow(10, Math.floor(Math.log10(maxV)));
    const tickStep = [1, 2, 2.5, 5, 10].map((k) => k * mag).find((s) => maxV / s <= 5);
    const top = Math.ceil(maxV / tickStep) * tickStep;
    const y = (v) => T + (H - T - B) * (1 - v / top);

    const grid = svgEl("g", { class: "grid" });
    for (let v = 0; v <= top + 1e-9; v += tickStep) {
      if (v > 0) grid.append(svgEl("line", { x1: L, x2: W - R, y1: y(v), y2: y(v) }));
      const t = svgEl("text", { x: L - 6, y: y(v) + 4, "text-anchor": "end" });
      t.textContent = format(v);
      svg.append(t);
    }
    svg.append(grid, svgEl("line", { class: "base", x1: L, x2: W - R, y1: y(0), y2: y(0) }));

    const band = (W - L - R) / Math.max(1, cats.length);
    const groupW = stacked ? Math.min(24, band * 0.6) : Math.min(24 * series.length + 2 * (series.length - 1), band * 0.8);
    const barW = stacked ? groupW : (groupW - 2 * (series.length - 1)) / series.length;
    // Rounded at the data end, square at the baseline.
    const topRounded = (x, y0, w, h, r) => {
      r = Math.max(0, Math.min(r, h, w / 2));
      return `M${x},${y0 + h}V${y0 + r}Q${x},${y0} ${x + r},${y0}H${x + w - r}Q${x + w},${y0} ${x + w},${y0 + r}V${y0 + h}Z`;
    };
    const labelEvery = Math.ceil(cats.length / Math.max(1, Math.floor((W - L - R) / 56)));

    cats.forEach((c, i) => {
      const cx = L + band * i + band / 2;
      const col = svgEl("g", { class: "col" });
      col.append(svgEl("rect", { x: L + band * i, y: T, width: band, height: H - T - B, fill: "transparent" }));
      if (stacked) {
        const parts = series.map((se) => se.values[i] || 0);
        let acc = 0;
        const lastIdx = parts.reduce((li, v, k) => (v ? k : li), -1);
        parts.forEach((v, k) => {
          if (!v) return;
          const y1 = y(acc + v), y0 = y(acc);
          const gap = acc ? 2 : 0;
          const h = Math.max(1, y0 - y1 - gap);
          const shape = k === lastIdx
            ? svgEl("path", { d: topRounded(cx - groupW / 2, y1, groupW, h, 4) })
            : svgEl("rect", { x: cx - groupW / 2, y: y1, width: groupW, height: h });
          shape.setAttribute("class", "seg");
          shape.setAttribute("fill", series[k].color);
          col.append(shape);
          acc += v;
        });
      } else {
        series.forEach((se, k) => {
          const v = se.values[i];
          if (!v) return;
          const x = cx - groupW / 2 + k * (barW + 2);
          col.append(svgEl("path", { d: topRounded(x, y(v), barW, y(0) - y(v), 4), class: "seg", fill: se.color }));
        });
      }
      if (stacked && totals[i]) {
        const t = svgEl("text", { x: cx, y: y(totals[i]) - 6, "text-anchor": "middle", class: "lbl" });
        t.textContent = format(totals[i]);
        col.append(t);
      }
      if (i % labelEvery === 0) {
        const xl = svgEl("text", { x: cx, y: H - 8, "text-anchor": "middle" });
        xl.textContent = catLabel(c);
        col.append(xl);
      }
      const rows = series.filter((se) => se.values[i] != null).map((se) => [se.label, format(se.values[i])]);
      col.setAttribute("aria-label", `${catLabel(c)}: ` + rows.map((r) => r.join(" ")).join(", "));
      hover(col, catLabel(c), () => (stacked && series.length > 1 ? [...rows, ["Total", format(totals[i])]] : rows));
      svg.append(col);
    });
  }

  // Sortable table. cols: [{key, label, num, value(row), render(row) -> Node|string}]
  function table(head, body, rows, cols, state, onSort) {
    head.replaceChildren(...cols.map((c) => {
      const th = el("th", { className: c.num ? "num" : "" });
      const b = el("button", {}, c.label + (state.sort === c.key ? (state.dir > 0 ? " ↑" : " ↓") : ""));
      b.addEventListener("click", () => {
        state.dir = state.sort === c.key ? -state.dir : (c.num || c.desc ? -1 : 1);
        state.sort = c.key;
        onSort();
      });
      th.setAttribute("aria-sort", state.sort === c.key ? (state.dir > 0 ? "ascending" : "descending") : "none");
      th.append(b);
      return th;
    }));
    const col = cols.find((c) => c.key === state.sort) || cols[0];
    const sorted = [...rows].sort((a, b) => {
      const va = col.value(a), vb = col.value(b);
      return (va < vb ? -1 : va > vb ? 1 : 0) * state.dir;
    });
    body.replaceChildren(...sorted.map((r) => {
      const tr = el("tr");
      for (const c of cols) {
        const td = el("td", { className: (c.num ? "num " : "") + (c.cls || "") });
        const v = c.render ? c.render(r) : c.value(r);
        td.append(v instanceof Node ? v : document.createTextNode(v));
        tr.append(td);
      }
      return tr;
    }));
    if (!sorted.length) {
      const tr = el("tr");
      tr.append(el("td", { className: "empty", colSpan: cols.length }, "Nothing matches these filters."));
      body.append(tr);
    }
  }

  function fillSelect(id, values, label) {
    const s = $(id);
    for (const v of values) s.append(el("option", { value: v }, label ? label(v) : String(v)));
  }

  function onResize(fn) {
    let t;
    window.addEventListener("resize", () => { clearTimeout(t); t = setTimeout(fn, 150); });
  }

  return { $, money, moneyFull, num, pct, monthName, dayName, el, svgEl, hover, hbars, columns, table, fillSelect, onResize };
})();
