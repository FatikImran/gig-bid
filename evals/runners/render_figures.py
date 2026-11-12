from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "evals" / "results" / "demo_eval.json"
OUTPUT = ROOT / "docs" / "images" / "local-smoke-eval.svg"


def render() -> None:
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    variants = data["retrieval_variants"]
    names = list(variants)
    colors = ["#6f9873", "#83a981", "#91b38f", "#9ab996", "#aec6a8", "#c5d5bd"]
    chart_left, chart_width = 185, 660
    chart_top, row_height = 104, 49
    elements = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="510" viewBox="0 0 1000 510">',
        '<rect width="1000" height="510" rx="18" fill="#fbfcf9"/>',
        '<text x="54" y="52" font-family="Arial, sans-serif" font-size="21" font-weight="700" fill="#223226">Local retrieval smoke evaluation</text>',
        f'<text x="54" y="77" font-family="Arial, sans-serif" font-size="12" fill="#768477">Recall@5 · {data["retrieval_query_count"]} positive query · one synthetic evidence item</text>',
    ]
    for tick in range(6):
        x = chart_left + tick * chart_width / 5
        elements.append(
            f'<line x1="{x:.1f}" y1="95" x2="{x:.1f}" y2="410" stroke="#e6ebe3" stroke-width="1"/>'
        )
        elements.append(
            f'<text x="{x:.1f}" y="434" text-anchor="middle" font-family="Arial, sans-serif" font-size="10" fill="#879187">{tick / 5:.1f}</text>'
        )
    for row, name in enumerate(names):
        y = chart_top + row * row_height
        value = variants[name]["recall_at_5"] or 0
        width = chart_width * value
        elements.append(
            f'<text x="54" y="{y + 17}" font-family="Arial, sans-serif" font-size="12" font-weight="600" fill="#344238">{name}</text>'
        )
        elements.append(
            f'<rect x="{chart_left}" y="{y}" width="{chart_width}" height="25" rx="5" fill="#edf1eb"/>'
        )
        elements.append(
            f'<rect x="{chart_left}" y="{y}" width="{width:.1f}" height="25" rx="5" fill="{colors[row % len(colors)]}"/>'
        )
        elements.append(
            f'<text x="{min(chart_left + width + 10, 900):.1f}" y="{y + 17}" font-family="Arial, sans-serif" font-size="11" font-weight="700" fill="#46564a">{value:.2f}</text>'
        )
    elements.extend(
        [
            '<rect x="54" y="466" width="892" height="25" rx="6" fill="#f3f5ef"/>',
            '<text x="66" y="483" font-family="Arial, sans-serif" font-size="10" fill="#6f7d70">All variants tie because the corpus contains one relevant item; this is not evidence of general retrieval quality.</text>',
            "</svg>",
        ]
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(elements) + "\n", encoding="utf-8")


if __name__ == "__main__":
    render()
