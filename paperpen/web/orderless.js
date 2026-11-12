// Orderless matching, as emacs's `orderless` does it, for every search on the
// pages. The same rules as paperpen/orderless.py, which the server uses:
//
//   pieces split on spaces, all of them in the text, in any order
//   !piece     must not be in it
//   a capital  matches as written; without one, case is ignored (smart case)
//
// Each piece is literal text, never a regular expression, so nothing typed can
// be an error.
(function (root) {
  function parse(query) {
    return String(query || '').split(/\s+/).filter(Boolean).map(raw => {
      const negated = raw.length > 1 && raw[0] === '!';
      const text = negated ? raw.slice(1) : raw;
      return {text: text, negated: negated, exact: text !== text.toLowerCase()};
    });
  }

  function found(piece, text) {
    return piece.exact ? text.includes(piece.text)
      : text.toLowerCase().includes(piece.text.toLowerCase());
  }

  function matches(pieces, text) {
    if (!pieces.length) return false;
    text = String(text || '');
    return pieces.every(p => found(p, text) !== p.negated);
  }

  // where the wanted pieces are, merged, for a highlight
  function spans(pieces, text) {
    text = String(text || '');
    const folded = text.toLowerCase(), out = [];
    for (const p of pieces) {
      if (p.negated || !p.text) continue;
      const hay = p.exact ? text : folded, needle = p.exact ? p.text : p.text.toLowerCase();
      for (let at = hay.indexOf(needle); at >= 0; at = hay.indexOf(needle, at + needle.length)) {
        out.push([at, at + needle.length]);
      }
    }
    out.sort((a, b) => a[0] - b[0]);
    const merged = [];
    for (const [a, b] of out) {
      if (merged.length && a <= merged[merged.length - 1][1]) {
        merged[merged.length - 1][1] = Math.max(b, merged[merged.length - 1][1]);
      } else merged.push([a, b]);
    }
    return merged;
  }

  // the text as nodes, with <mark> around what was found: built with text
  // nodes, so nothing in the text is ever read as markup
  function marked(pieces, text) {
    text = String(text || '');
    const box = document.createDocumentFragment();
    let at = 0;
    for (const [a, b] of spans(pieces, text)) {
      if (a > at) box.appendChild(document.createTextNode(text.slice(at, a)));
      const m = document.createElement('mark');
      m.textContent = text.slice(a, b);
      box.appendChild(m);
      at = b;
    }
    if (at < text.length) box.appendChild(document.createTextNode(text.slice(at)));
    return box;
  }

  // A filter over a list already on the page: an element whose text does not
  // match is hidden, and `/` goes to the filter from anywhere not typing.
  function filter(input, nodes, after) {
    const run = () => {
      const pieces = parse(input.value);
      let shown = 0;
      for (const node of nodes()) {
        const on = !pieces.length || matches(pieces, node.textContent);
        node.hidden = !on;
        if (on) shown++;
      }
      if (after) after(shown, pieces.length > 0);
    };
    input.addEventListener('input', run);
    document.addEventListener('keydown', e => {
      const typing = e.target.closest && e.target.closest('input, textarea, select');
      if (e.key === '/' && !typing) { e.preventDefault(); input.focus(); input.select(); }
      if (e.key === 'Escape' && e.target === input) { input.value = ''; run(); input.blur(); }
    });
    return run;
  }

  root.Orderless = {parse: parse, matches: matches, spans: spans, marked: marked, filter: filter};
})(window);
