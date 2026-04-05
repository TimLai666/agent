"""rich_render.py — Math formula, flowchart and chart rendering for the agent chat bubble.

Math  : $inline$  /  $$block$$  /  \\(inline\\)  /  \\[block\\]  → KaTeX
Charts: ```chart JSON``` → matplotlib (offline, base64 PNG)
Mermaid flowcharts: ```mermaid ... ``` → Mermaid.js
"""

from __future__ import annotations
import base64
import json
import re
import html as _html
from io import BytesIO

# ── Detection patterns ───────────────────────────────────────────────────────

# $$ ... $$  /  $ ... $
_DOLLAR_MATH_RE   = re.compile(r'\$\$[\s\S]+?\$\$|\$(?!\s)[^$\n]+?(?<!\s)\$')
# \[ ... \]  /  \( ... \)  (with literal backslashes in the text)
_BRACKET_MATH_RE  = re.compile(r'\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)')
# Bare [ on its own line ... ] on its own line  (agent sometimes writes this)
_BARE_BRACKET_RE  = re.compile(r'(?m)^[ \t]*\[[ \t]*\n([\s\S]+?)\n[ \t]*\][ \t]*$')
# ```chart ... ```
_CHART_BLOCK_RE   = re.compile(r'```chart\s*\n([\s\S]*?)```', re.IGNORECASE)
# ```mermaid ... ```
_MERMAID_BLOCK_RE = re.compile(r'```mermaid\s*\n([\s\S]*?)```', re.IGNORECASE)


def preprocess_math(text: str) -> str:
    """Normalise various math delimiter styles to $$ / $ before rendering."""
    # \[...\]  →  $$...$$
    text = re.sub(r'\\\[([\s\S]+?)\\\]', r'$$\1$$', text)
    # \(...\)  →  $...$
    text = re.sub(r'\\\(([\s\S]+?)\\\)', r'$\1$', text)
    # Bare-bracket block: standalone [ ... ] lines → $$...$$
    text = _BARE_BRACKET_RE.sub(r'$$\n\1\n$$', text)
    return text


def has_rich_content(text: str) -> bool:
    """Return True if text contains math, chart, or mermaid syntax."""
    preprocessed = preprocess_math(text)
    return bool(
        _CHART_BLOCK_RE.search(preprocessed)
        or _MERMAID_BLOCK_RE.search(preprocessed)
        or _DOLLAR_MATH_RE.search(preprocessed)
        or _BRACKET_MATH_RE.search(preprocessed)
    )


# ── Chart rendering (matplotlib, fully offline) ──────────────────────────────

def render_chart(spec: dict) -> str:
    """Render a chart spec dict to a base64-encoded PNG data URI."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    chart_type = spec.get("type", "bar").lower()
    title  = spec.get("title", "")
    xlabel = spec.get("xlabel", "")
    ylabel = spec.get("ylabel", "")
    grid   = spec.get("grid", True)
    colors = spec.get("colors") or None

    fig, ax = plt.subplots(figsize=(7, 4), dpi=110)
    fig.patch.set_facecolor("#1a2040")
    ax.set_facecolor("#1e2848")
    ax.tick_params(colors="#b0c8e8")
    ax.xaxis.label.set_color("#b0c8e8")
    ax.yaxis.label.set_color("#b0c8e8")
    ax.title.set_color("#dde8f8")
    for spine in ax.spines.values():
        spine.set_edgecolor("#3060a0")

    default_colors = ["#4ea8de", "#e06c75", "#98c379", "#e5c07b",
                      "#c678dd", "#56b6c2", "#be5046", "#61afef"]

    def _color(i: int):
        if colors and i < len(colors):
            return colors[i]
        return default_colors[i % len(default_colors)]

    series = spec.get("series")

    if chart_type == "pie":
        labels = spec.get("labels", [])
        values = spec.get("values", spec.get("y", []))
        pie_colors = colors or default_colors[:len(labels)]
        _, texts, autotexts = ax.pie(
            values, labels=labels, colors=pie_colors,
            autopct="%1.1f%%", startangle=140,
            textprops={"color": "#dde8f8"},
        )
        for at in autotexts:
            at.set_color("#dde8f8")

    elif chart_type == "hist":
        data = spec.get("data", spec.get("y", []))
        bins = spec.get("bins", 10)
        ax.hist(data, bins=bins, color=_color(0), edgecolor="#1a2040", alpha=0.85)
        if grid:
            ax.grid(True, color="#2a3860", linewidth=0.5)

    elif chart_type in ("bar", "barh"):
        if series:
            import numpy as np
            n_series = len(series)
            xs_raw = series[0].get("x", list(range(len(series[0].get("y", [])))))
            n_groups = len(xs_raw)
            x_pos = np.arange(n_groups)
            width = 0.8 / max(n_series, 1)
            for i, s in enumerate(series):
                ys = s.get("y", [])
                offset = (i - n_series / 2 + 0.5) * width
                if chart_type == "barh":
                    ax.barh(x_pos + offset, ys, width, label=s.get("label", f"S{i+1}"),
                            color=_color(i), alpha=0.88)
                else:
                    ax.bar(x_pos + offset, ys, width, label=s.get("label", f"S{i+1}"),
                           color=_color(i), alpha=0.88)
            ticks = x_pos
            tick_labels = [str(v) for v in xs_raw]
            if chart_type == "barh":
                ax.set_yticks(ticks); ax.set_yticklabels(tick_labels, color="#b0c8e8")
            else:
                ax.set_xticks(ticks); ax.set_xticklabels(tick_labels, color="#b0c8e8")
            ax.legend(facecolor="#1e2848", edgecolor="#3060a0", labelcolor="#dde8f8")
        else:
            x = spec.get("x", [])
            y = spec.get("y", [])
            if chart_type == "barh":
                ax.barh(x, y, color=_color(0), alpha=0.88, edgecolor="#1a2040")
            else:
                ax.bar(x, y, color=_color(0), alpha=0.88, edgecolor="#1a2040")
        if grid:
            axis = "y" if chart_type == "bar" else "x"
            ax.grid(True, color="#2a3860", linewidth=0.5, axis=axis)

    elif chart_type == "scatter":
        if series:
            for i, s in enumerate(series):
                ax.scatter(s.get("x", []), s.get("y", []),
                           label=s.get("label", f"S{i+1}"),
                           color=_color(i), alpha=0.85, s=40)
            ax.legend(facecolor="#1e2848", edgecolor="#3060a0", labelcolor="#dde8f8")
        else:
            ax.scatter(spec.get("x", []), spec.get("y", []),
                       color=_color(0), alpha=0.85, s=40)
        if grid:
            ax.grid(True, color="#2a3860", linewidth=0.5)

    else:  # line
        if series:
            for i, s in enumerate(series):
                ax.plot(s.get("x", []), s.get("y", []),
                        label=s.get("label", f"S{i+1}"),
                        color=_color(i), linewidth=1.8, marker="o", markersize=4)
            ax.legend(facecolor="#1e2848", edgecolor="#3060a0", labelcolor="#dde8f8")
        else:
            ax.plot(spec.get("x", []), spec.get("y", []),
                    color=_color(0), linewidth=1.8, marker="o", markersize=4)
        if grid:
            ax.grid(True, color="#2a3860", linewidth=0.5)

    if title:  ax.set_title(title, fontsize=13, pad=8)
    if xlabel: ax.set_xlabel(xlabel)
    if ylabel: ax.set_ylabel(ylabel)

    plt.tight_layout(pad=1.2)
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return "data:image/png;base64," + base64.b64encode(buf.read()).decode()


def _render_chart_block(json_src: str) -> str:
    try:
        spec = json.loads(json_src.strip())
        uri = render_chart(spec)
        return (
            f'<div class="chart-wrap">'
            f'<img src="{uri}" /></div>'
        )
    except Exception as exc:
        return (
            f'<div class="err">⚠ Chart error: {_html.escape(str(exc))}</div>'
        )


# ── Markdown → HTML (pre-process special blocks) ─────────────────────────────

def _md_to_html(text: str) -> str:
    """Convert markdown to HTML; normalise math delimiters and render chart blocks."""
    # 1. Normalise math delimiters (\[..\], \(..\), bare [..] → $$ / $)
    text = preprocess_math(text)
    # 2. Replace ```chart blocks with rendered <img>
    text = _CHART_BLOCK_RE.sub(lambda m: _render_chart_block(m.group(1)), text)
    # 3. Standard markdown conversion
    import markdown
    md = markdown.Markdown(extensions=["fenced_code", "tables", "nl2br"])
    return md.convert(text)


# ── HTML page builder ─────────────────────────────────────────────────────────

# Mermaid + KaTeX are loaded from CDN.
# The page is loaded via setHtml(..., baseUrl=QUrl("https://cdn.jsdelivr.net/"))
# so Qt WebEngine treats the page as remote content and allows CDN script loading.

_KATEX_CDN  = "https://cdn.jsdelivr.net/npm/katex@0.16.11/dist"
_MERMAID_CDN = "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link rel="stylesheet" href="{katex_css}">
<script defer src="{katex_js}"></script>
<script defer src="{auto_render_js}"
  onload="renderMathInElement(document.body, {{
    delimiters: [
      {{left: '$$', right: '$$', display: true}},
      {{left: '$',  right: '$',  display: false}},
      {{left: '\\\\[', right: '\\\\]', display: true}},
      {{left: '\\\\(', right: '\\\\)', display: false}}
    ],
    throwOnError: false
  }});">
</script>
<script src="{mermaid_js}"></script>
<script>
  document.addEventListener('DOMContentLoaded', function() {{
    if (window.mermaid) {{
      mermaid.initialize({{
        startOnLoad: true,
        theme: 'dark',
        themeVariables: {{
          darkMode: true,
          background: '#1a2040',
          primaryColor: '#4ea8de',
          primaryTextColor: '#dde8f8',
          lineColor: '#5080c0',
          fontSize: '13px'
        }}
      }});
    }}
  }});
</script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{
    background: transparent;
    color: #dde8f8;
    font-family: 'Segoe UI', 'Microsoft JhengHei', 'PingFang TC', sans-serif;
    font-size: 13px;
    line-height: 1.7;
    padding: 4px 2px;
    word-break: break-word;
  }}
  h1,h2,h3,h4,h5,h6 {{ color: #90c0f0; margin: 10px 0 5px; line-height: 1.3; }}
  p {{ margin: 5px 0; }}
  a {{ color: #5eaef0; }}
  code {{
    background: rgba(30,40,80,0.7); color: #e8c87a;
    border-radius: 4px; padding: 1px 5px;
    font-family: 'Cascadia Code','Consolas',monospace; font-size: 12px;
  }}
  pre {{
    background: rgba(20,28,60,0.85);
    border: 1px solid rgba(60,90,180,0.4);
    border-radius: 8px; padding: 10px 14px;
    overflow-x: auto; margin: 8px 0;
  }}
  pre code {{ background: transparent; color: #c8d8f0; font-size: 12px; padding: 0; }}
  table {{ border-collapse: collapse; width: 100%; margin: 8px 0; }}
  th, td {{ border: 1px solid rgba(60,90,180,0.4); padding: 5px 10px; text-align: left; }}
  th {{ background: rgba(40,60,120,0.5); color: #90c0f0; }}
  tr:nth-child(even) td {{ background: rgba(30,45,90,0.35); }}
  blockquote {{
    border-left: 3px solid rgba(80,140,255,0.5);
    padding: 4px 12px; color: #a0b8d8; margin: 6px 0;
    background: rgba(30,50,100,0.2); border-radius: 0 6px 6px 0;
  }}
  ul, ol {{ padding-left: 22px; margin: 6px 0; }}
  li {{ margin: 3px 0; }}
  hr {{ border: none; border-top: 1px solid rgba(60,90,180,0.4); margin: 10px 0; }}
  img {{ max-width: 100%; }}
  .katex-display {{ margin: 12px 0; overflow-x: auto; }}
  .katex {{ font-size: 1.05em; }}
  .chart-wrap {{ text-align: center; margin: 10px 0; }}
  .chart-wrap img {{ max-width: 100%; border-radius: 8px; }}
  .err {{
    color: #f06b6b; font-size: 11px; padding: 4px 8px;
    background: rgba(240,80,80,0.1); border-radius: 6px; margin: 6px 0;
  }}
  /* Mermaid */
  .mermaid {{ margin: 10px 0; text-align: center; }}
  .mermaid svg {{ max-width: 100%; }}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def build_rich_html(markdown_text: str) -> str:
    """Return a full HTML page with KaTeX math + Mermaid diagrams + chart images."""
    body_html = _md_to_html(markdown_text)
    return _HTML_TEMPLATE.format(
        katex_css=f"{_KATEX_CDN}/katex.min.css",
        katex_js=f"{_KATEX_CDN}/katex.min.js",
        auto_render_js=f"{_KATEX_CDN}/contrib/auto-render.min.js",
        mermaid_js=_MERMAID_CDN,
        body=body_html,
    )
