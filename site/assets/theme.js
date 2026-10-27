// Light / dark / system theme. Loaded in <head> so the saved choice applies
// before the page paints; the switch is added once the nav exists.
(() => {
  const KEY = "yyc-theme";
  const read = () => { try { return localStorage.getItem(KEY) || ""; } catch { return ""; } };
  const write = (v) => { try { v ? localStorage.setItem(KEY, v) : localStorage.removeItem(KEY); } catch {} };
  const apply = (v) => (v ? document.documentElement.setAttribute("data-theme", v) : document.documentElement.removeAttribute("data-theme"));
  apply(read());

  document.addEventListener("DOMContentLoaded", () => {
    const nav = document.querySelector("nav.tabs");
    if (!nav) return;
    const group = document.createElement("div");
    group.className = "theme";
    group.setAttribute("role", "group");
    group.setAttribute("aria-label", "Colour theme");
    const options = [["", "Auto"], ["light", "Light"], ["dark", "Dark"]];
    const buttons = options.map(([value, label]) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = label;
      if (!value) b.title = "Match your device setting";
      b.addEventListener("click", () => { write(value); apply(value); sync(); });
      group.append(b);
      return [value, b];
    });
    const sync = () => { const cur = read(); for (const [v, b] of buttons) b.setAttribute("aria-pressed", String(v === cur)); };
    sync();
    nav.append(group);
  });
})();
