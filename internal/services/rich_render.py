"""rich_render.py — Math formula and chart rendering for the agent chat bubble.

Math: standard LaTeX  $inline$  /  $$block$$  syntax  → rendered via KaTeX (CDN).
Charts: fenced code block  ```chart  with JSON spec  → rendered via matplotlib → base64 PNG.

Chart spec JSON schema (all fields optional except `type`):
{
  "type":   "bar" | "line" | "pie" | "scatter" | "hist" | "barh",
  "title":  "Chart title",
  "xlabel": "X axis label",
  "ylabel": "Y axis label",
  "x":      [...],          // x-axis values  (bar / line / scatter)
  "y":      [...],          // y-axis values  (bar / line / scatter)
  "labels": [...],          // slice labels   (pie)
  "values": [...],          // slice values   (pie)
  "data":   [...],          // raw data list  (hist)
  "series": [               // multiple series (bar / line / scatter)
    {"label": "A", "x": [...], "y": [...]},
    ...
  ],
  "colors": [...],          // per-series or per-slice colors
  "grid":   true            // show grid (default true for most types)
}
"""

from __future__ import annotations
import base64
import json
import re
import html as _html
from io import BytesIO

# ── Pattern helpers ──────────────────────────────────────────────────────────

_MATH_RE = re.compile(r'\$\$[\s\S]+?\$\$|\$[^$\n]+?\$', re.DOTALL)
_CHART_BLOCK_RE = re.compile(r'```chart\s*\n([\s\S]*?)```', re.IGNORECASE)

KATEX_CDN = "https://cdn.jsdelivr.net/npm/katex@0.16.11/dist"


def has_rich_content(text: str) -> bool:
    """Return True if text contains math or chart syntax."""
    if _CHART_BLOCK_RE.search(text):
        return True
    if _MATH_RE.search(text):
        return True
    return False


# ── Chart rendering ──────────────────────────────────────────────────────────

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
        wedges, texts, autotexts = ax.pie(
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
            if chart_type == "barh":
                ax.set_yticks(x_pos)
                ax.set_yticklabels([str(v) for v in xs_raw], color="#b0c8e8")
            else:
                ax.set_xticks(x_pos)
                ax.set_xticklabels([str(v) for v in xs_raw], color="#b0c8e8")
            leg = ax.legend(facecolor="#1e2848", edgecolor="#3060a0", labelcolor="#dde8f8")
        else:
            x = spec.get("x", [])
            y = spec.get("y", [])
            if chart_type == "barh":
                ax.barh(x, y, color=_color(0), alpha=0.88, edgecolor="#1a2040")
            else:
                ax.bar(x, y, color=_color(0), alpha=0.88, edgecolor="#1a2040")
        if grid:
            ax.grid(True, color="#2a3860", linewidth=0.5, axis="y" if chart_type == "bar" else "x")

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

    else:  # line (default)
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

    if title:
        ax.set_title(title, fontsize=13, pad=8)
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)

    plt.tight_layout(pad=1.2)
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return "data:image/png;base64," + base64.b64encode(buf.read()).decode()


def _render_chart_block(json_src: str) -> str:
    """Parse a chart JSON block and return an <img> tag or an error div."""
    try:
        spec = json.loads(json_src.strip())
        uri = render_chart(spec)
        return (
            f'<div style="text-align:center;margin:10px 0;">'
            f'<img src="{uri}" style="max-width:100%;border-radius:8px;" /></div>'
        )
    except Exception as exc:
        return (
            f'<div style="color:#f06b6b;font-size:11px;padding:4px 8px;'
            f'background:rgba(240,80,80,0.1);border-radius:6px;">'
            f'⚠ Chart error: {_html.escape(str(exc))}</div>'
        )


# ── Markdown → HTML conversion ───────────────────────────────────────────────

def _md_to_html(text: str) -> str:
    """Convert markdown text to HTML, replacing chart blocks with <img> first."""
    # 1. Replace ```chart blocks with rendered images
    def _chart_repl(m: re.Match) -> str:
        return _render_chart_block(m.group(1))

    text = _CHART_BLOCK_RE.sub(_chart_repl, text)

    # 2. Convert markdown to HTML
    import markdown
    md = markdown.Markdown(extensions=["fenced_code", "tables", "nl2br"])
    return md.convert(text)


# ── Full page builder ────────────────────────────────────────────────────────

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link rel="stylesheet" href="{katex_css}">
<script defer src="{katex_js}"></script>
<script defer src="{auto_render_js}"
        onload="renderMathInElement(document.body,{{
          delimiters:[
            {{left:'$$',right:'$$',display:true}},
            {{left:'$',right:'$',display:false}}
          ],
          throwOnError:false
        }});">
</script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{
    background: transparent;
    color: #dde8f8;
    font-family: 'Segoe UI', 'Microsoft JhengHei', 'PingFang TC', sans-serif;
    font-size: 13px;
    line-height: 1.65;
    padding: 6px 2px;
    word-break: break-word;
  }}
  h1,h2,h3,h4,h5,h6 {{
    color: #90c0f0;
    margin: 10px 0 6px;
    line-height: 1.3;
  }}
  p {{ margin: 6px 0; }}
  a {{ color: #5eaef0; }}
  code {{
    background: rgba(30,40,80,0.7);
    color: #e8c87a;
    border-radius: 4px;
    padding: 1px 5px;
    font-family: 'Cascadia Code', 'Consolas', monospace;
    font-size: 12px;
  }}
  pre {{
    background: rgba(20,28,60,0.85);
    border: 1px solid rgba(60,90,180,0.4);
    border-radius: 8px;
    padding: 10px 14px;
    overflow-x: auto;
    margin: 8px 0;
  }}
  pre code {{
    background: transparent;
    color: #c8d8f0;
    font-size: 12px;
    padding: 0;
  }}
  table {{
    border-collapse: collapse;
    width: 100%;
    margin: 8px 0;
  }}
  th, td {{
    border: 1px solid rgba(60,90,180,0.4);
    padding: 5px 10px;
    text-align: left;
  }}
  th {{ background: rgba(40,60,120,0.5); color: #90c0f0; }}
  tr:nth-child(even) td {{ background: rgba(30,45,90,0.35); }}
  blockquote {{
    border-left: 3px solid rgba(80,140,255,0.5);
    padding: 4px 12px;
    color: #a0b8d8;
    margin: 6px 0;
    background: rgba(30,50,100,0.2);
    border-radius: 0 6px 6px 0;
  }}
  ul, ol {{ padding-left: 22px; margin: 6px 0; }}
  li {{ margin: 3px 0; }}
  .katex-display {{ margin: 12px 0; overflow-x: auto; }}
  .katex {{ font-size: 1.05em; }}
  hr {{ border: none; border-top: 1px solid rgba(60,90,180,0.4); margin: 10px 0; }}
  img {{ max-width: 100%; }}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def build_rich_html(markdown_text: str) -> str:
    """Return a full standalone HTML page with KaTeX math + chart images."""
    body_html = _md_to_html(markdown_text)
    return _HTML_TEMPLATE.format(
        katex_css=f"{KATEX_CDN}/katex.min.css",
        katex_js=f"{KATEX_CDN}/katex.min.js",
        auto_render_js=f"{KATEX_CDN}/contrib/auto-render.min.js",
        body=body_html,
    )
