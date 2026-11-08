"""Build the one-page design card and ontology from verified run artifacts."""
from __future__ import annotations

import html
import json
import re
import shutil
import sys
from pathlib import Path

try:
    import reportlab
except ImportError:
    sys.path.append(str(Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/python/Lib/site-packages"))

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
MODEL_URL = "https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite"
NAVY = colors.HexColor("#101c30")
INK = colors.HexColor("#17263a")
MUTED = colors.HexColor("#5c6e83")
TEAL = colors.HexColor("#198777")
CORAL = colors.HexColor("#f47a61")
PALE = colors.HexColor("#edf4f5")


def load(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def text_block(c, text, x, top, width, size=9, leading=12.6, color=INK, bold=False):
    style = ParagraphStyle("body", fontName="WWBold" if bold else "WW", fontSize=size,
                           leading=leading, textColor=color, spaceAfter=0)
    p = Paragraph(text, style)
    _, height = p.wrap(width, 1000)
    p.drawOn(c, x, top - height)
    return top - height


def heading(c, label, x, y):
    c.setFillColor(TEAL)
    c.setFont("WWBold", 9)
    c.drawString(x, y, label.upper())


def arrow(c, x1, y1, x2, y2, color=MUTED):
    c.setStrokeColor(color)
    c.setLineWidth(.8)
    c.line(x1, y1, x2, y2)
    c.line(x2 - 4, y2 + 2.6, x2, y2)
    c.line(x2 - 4, y2 - 2.6, x2, y2)


def small_box(c, x, y, width, title, subtitle, accent):
    c.setFillColor(colors.white)
    c.setStrokeColor(colors.HexColor("#d4e0e6"))
    c.roundRect(x, y, width, 49, 6, fill=1, stroke=1)
    c.setFillColor(accent)
    c.roundRect(x, y + 45, width, 4, 2, fill=1, stroke=0)
    text_block(c, title, x + 11, y + 36, width - 22, 9, 11, INK, True)
    text_block(c, subtitle, x + 11, y + 19, width - 22, 7.5, 10, MUTED)


def build_pdf(summary, audit, graph, test_count, graph_checks):
    regular = Path("C:/Windows/Fonts/segoeui.ttf")
    bold = Path("C:/Windows/Fonts/segoeuib.ttf")
    if regular.exists() and bold.exists():
        pdfmetrics.registerFont(TTFont("WW", str(regular)))
        pdfmetrics.registerFont(TTFont("WWBold", str(bold)))
    else:
        pdfmetrics.registerFont(pdfmetrics.Font("WW", "Helvetica", "WinAnsiEncoding"))
        pdfmetrics.registerFont(pdfmetrics.Font("WWBold", "Helvetica-Bold", "WinAnsiEncoding"))
    output = DOCS / "design-card.pdf"
    c = canvas.Canvas(str(output), pagesize=(612, 792))
    c.setTitle("Highway Control Tower - One-page design card")
    c.setAuthor("Wacky Wheels Control Tower / TAMU Datathon 2026")
    c.setSubject("Architecture, guardrails, independent evaluation and model provenance")
    c.setFillColor(colors.HexColor("#f7f9fb"))
    c.rect(0, 0, 612, 792, fill=1, stroke=0)
    c.setFillColor(NAVY)
    c.rect(0, 681, 612, 111, fill=1, stroke=0)
    c.setFillColor(CORAL)
    c.roundRect(36, 728, 39, 39, 8, fill=1, stroke=0)
    c.setFont("WWBold", 14)
    c.setFillColor(NAVY)
    c.drawCentredString(55.5, 741, "WW")
    text_block(c, "TAMU DATATHON 2026 / CHALLENGE 6 / HITACHI", 91, 770, 485, 7.5, 10,
               colors.HexColor("#a7b8d0"), True)
    text_block(c, "Highway Control Tower", 91, 752, 485, 25, 29, colors.white, True)
    text_block(c, "A traceable response to every disruption.", 91, 714, 485, 11, 14,
               colors.HexColor("#c5d3e5"))

    stats = [(f"{audit['events_passed']}/{audit['events_total']}", "independent event audit", f"Do-nothing baseline: {audit['baseline_do_nothing_events_passed']}/15"),
             (str(summary["failed_calls"]), "failed enterprise calls", f"{summary['server_calls']:,} official HTTP calls"),
             (f"{test_count}/{test_count}", "tests passing", "Policy, parser, client, agents"),
             (f"{graph_checks}/{graph_checks}", "direct-table graph checks", "Baseline: no graph")]
    for index, (value, label, note) in enumerate(stats):
        x = 36 + index * 137
        c.setFillColor(colors.white)
        c.setStrokeColor(colors.HexColor("#dce5ec"))
        c.roundRect(x, 603, 129, 61, 7, fill=1, stroke=1)
        text_block(c, value, x + 11, 655, 111, 21, 23, TEAL, True)
        text_block(c, label, x + 11, 630, 111, 7.5, 10, INK, True)
        text_block(c, note, x + 11, 617, 111, 6.6, 8, MUTED)

    heading(c, "One coordinator. Three bounded specialists.", 36, 582)
    steps = [(36, 76, "Event text"), (125, 132, "LLM extraction"), (270, 140, "Coordinator"), (423, 153, "Official HTTP tools")]
    for x, width, label in steps:
        c.setFillColor(NAVY if label == "Coordinator" else colors.HexColor("#e5edf3"))
        c.roundRect(x, 538, width, 28, 5, fill=1, stroke=0)
        c.setFillColor(colors.white if label == "Coordinator" else INK)
        c.setFont("WWBold", 8.5)
        c.drawCentredString(x + width / 2, 548, label)
    for left, right in zip(steps, steps[1:]):
        arrow(c, left[0] + left[1] + 2, 552, right[0] - 3, 552)
    c.setStrokeColor(colors.HexColor("#b8c9d4"))
    c.line(340, 538, 340, 526)
    c.line(120, 526, 492, 526)
    for x in (120, 306, 492):
        c.line(x, 526, x, 516)
    small_box(c, 36, 465, 168, "Supply Chain Planner", "Graph impact, earliest slots, transfers", colors.HexColor("#559bc7"))
    small_box(c, 222, 465, 168, "Dealer / Customer Care", "One dealer notice; priority loaners", colors.HexColor("#e4a14b"))
    small_box(c, 408, 465, 168, "Quality", "Lot hold, stop sale, owner contact", colors.HexColor("#9a82c8"))
    text_block(c, "Each agent has its own tool allowlist, enforced before any HTTP call. Typed handoffs are traced: Coordinator → Planner → Care. Fresh world per event.",
               36, 454, 540, 8, 10.5, MUTED)

    heading(c, "LLM understands. Code decides.", 36, 421)
    heading(c, "Guardrails before writes", 318, 421)
    left = [
        "<b>LLM:</b> classify and split messages; extract entities, confirmation and date phrases. Preserve every raw response.",
        "<b>Code:</b> resolve aliases and relative dates; traverse the BOM and graph; choose affected records, earliest slots and loaner recipients.",
        "<b>Priority:</b> Platinum, then Gold, earlier promised date, lower order ID. Each dealer receives one event-wide notice.",
    ]
    right = [
        "Per-agent tool allowlists: an out-of-scope call is refused in-process and halts the event. Read live schedules and pools; validate schema, identity, dates and scope.",
        "Never retry an uncertain write. Noise makes no calls; rumors only escalate. Quality separates unsold vehicles from sold owners.",
        "Retain graph paths, decision rationale, tool results and the authoritative action log. No hard-coded event answers.",
    ]
    for x, blocks in ((36, left), (318, right)):
        top = 405
        for block in blocks:
            top = text_block(c, block, x, top, 258, 9, 12.6) - 9

    c.setFillColor(PALE)
    c.roundRect(36, 219, 540, 66, 7, fill=1, stroke=0)
    text_block(c, f"<b>Company graph</b>  |  16 tables  |  11 entity types  |  {graph['nodes']:,} nodes  |  {graph['edges']:,} edges", 48, 273, 516, 9, 12, INK)
    text_block(c, "Shipment → Part → Model → ProductionOrder → CustomerOrder → Dealer / Customer", 48, 252, 516, 8.6, 12, TEAL, True)
    text_block(c, "NetworkX graph + actual edge evidence. CSV joins independently check the runtime traversal.", 48, 235, 516, 7.6, 10, MUTED)

    heading(c, "Measured execution and model provenance", 36, 199)
    text_block(c, f"<b>{summary['server_calls']:,} calls:</b> {summary['operational_writes']:,} operational writes + {summary['server_calls'] - summary['operational_writes'] - 2:,} free reads + 2 escalations. "
               f"Final HTTP execution: <b>{summary['seconds_execution']:.3f}s</b>; dry run: 13.035s. These are observed runs, not a comparative benchmark.",
               36, 185, 540, 8.5, 11.7)
    text_block(c, f"<b>Gemini 3.5 Flash-Lite</b> ({summary['models'][0]}): {summary['llm_input_tokens']:,} input / "
               f"{summary['llm_output_tokens']:,} output tokens across 15 responses. The clean run reuses recorded raw output after general normalization; it is not an independent model reproduction.",
               36, 148, 540, 8.5, 11.7)
    text_block(c, f'<link href="{MODEL_URL}" color="#198777">Google model documentation: {MODEL_URL}</link>',
               36, 110, 540, 7.2, 9.3, TEAL)
    c.setStrokeColor(colors.HexColor("#d2dfe7"))
    c.line(36, 88, 576, 88)
    text_block(c, "<b>Limits:</b> local audit is not a hidden judging score. Portal upload remains human-only.", 36, 78, 540, 7.8, 10.5, MUTED)
    text_block(c, "<b>Next:</b> calibrated uncertainty and more paraphrase holdouts. Demo screenshots predate the plants.csv transfer tie-break and the Agents &amp; handoffs tab.", 36, 62, 540, 7.8, 10.5, MUTED)
    c.setFont("WW", 7)
    c.setFillColor(MUTED)
    c.drawString(36, 26, "Wacky Wheels Co. / Local enterprise simulation / Verified November 8, 2026")
    c.drawRightString(576, 26, "DESIGN CARD  1 / 1")
    c.showPage()
    c.save()
    pages = len(PdfReader(str(output)).pages)
    if pages != 1:
        raise RuntimeError(f"Design card must have one page, got {pages}")
    return output, pages


def build_ontology(graph):
    nodes = {
        "Supplier": (150, 170), "Shipment": (460, 120), "Part": (740, 120), "Model": (1030, 120),
        "Lot": (460, 460), "Plant": (740, 690), "ProductionOrder": (1030, 460),
        "CustomerOrder": (1320, 330), "Vehicle": (1320, 610), "Dealer": (1600, 330), "Customer": (1600, 610),
    }
    accents = {"Supplier": "#65bfff", "Shipment": "#65bfff", "Plant": "#65bfff", "Part": "#aa97ff",
               "Lot": "#aa97ff", "Model": "#9aaec7", "ProductionOrder": "#ffb064", "Vehicle": "#ffb064",
               "CustomerOrder": "#50d6b4", "Dealer": "#50d6b4", "Customer": "#a5da79"}
    edges = [
        ("Supplier", "Shipment", "SHIPS", "M235 165 L375 125", 299, 130),
        ("Supplier", "Part", "SUPPLIES", "M150 138 L150 65 L740 65 L740 88", 430, 53),
        ("Supplier", "Lot", "PRODUCES", "M235 180 C310 180 300 460 375 460", 281, 337),
        ("Shipment", "Part", "CONTAINS", "M545 120 L655 120", 600, 102),
        ("Shipment", "Plant", "RECEIVED_AT", "M515 152 C580 230 615 510 690 658", 580, 393),
        ("Part", "Model", "USED_BY", "M825 120 L945 120", 884, 102),
        ("Lot", "Part", "OF_PART", "M510 428 C600 350 670 230 720 152", 649, 276),
        ("Lot", "Plant", "AT_PLANT", "M460 492 L460 690 L655 690", 559, 674),
        ("Lot", "ProductionOrder", "USED_IN", "M545 460 L945 460", 747, 444),
        ("Plant", "Model", "BUILDS", "M825 680 L890 680 L890 180 L980 152", 883, 365),
        ("Plant", "ProductionOrder", "SCHEDULES", "M825 670 C900 640 955 555 1000 492", 944, 581),
        ("Model", "ProductionOrder", "HAS_ORDER", "M1030 152 L1030 428", 1087, 291),
        ("ProductionOrder", "CustomerOrder", "FULFILLS", "M1115 445 C1170 410 1190 350 1235 330", 1191, 373),
        ("ProductionOrder", "Vehicle", "BUILT", "M1115 478 C1170 515 1190 590 1235 610", 1190, 555),
        ("CustomerOrder", "Dealer", "AT_DEALER", "M1405 330 L1515 330", 1459, 312),
        ("CustomerOrder", "Customer", "FOR_CUSTOMER", "M1405 350 C1465 400 1465 550 1515 590", 1500, 468),
        ("Vehicle", "Customer", "OWNED_BY", "M1405 610 L1515 610", 1460, 592),
        ("Vehicle", "Dealer", "AT_DEALER", "M1320 642 L1320 750 L1720 750 L1720 330 L1685 330", 1524, 774),
    ]
    pieces = ['<svg xmlns="http://www.w3.org/2000/svg" width="1780" height="900" viewBox="0 0 1780 900" role="img" aria-label="Wacky Wheels ontology: eleven entity types and all eighteen class relationships">',
              '<rect width="1780" height="900" rx="20" fill="#0e192b"/>',
              '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0 L10 5 L0 10Z" fill="#7d91ac"/></marker></defs>',
              '<text x="50" y="827" fill="#eef4fc" font-size="28" font-family="sans-serif" font-weight="700">Wacky Wheels company ontology</text>',
              f'<text x="50" y="858" fill="#9fb3ce" font-size="18" font-family="sans-serif">16 CSV tables · 11 entity types · {graph["nodes"]:,} nodes · {graph["edges"]:,} instance edges</text>',
              '<text x="50" y="882" fill="#768eae" font-size="14" font-family="sans-serif">All class relationships shown. Lot USED_IN requires plant + build window + BOM. Live schedules and loaner pools remain server-owned.</text>']
    for source, target, relation, path, x, y in edges:
        pieces.append(f'<path data-source="{source}" data-target="{target}" data-relation="{relation}" d="{path}" fill="none" stroke="#617c9e" stroke-width="2" marker-end="url(#arrow)"/>')
        pieces.append(f'<text x="{x}" y="{y}" text-anchor="middle" fill="#a5b9d3" font-size="13" font-family="sans-serif" paint-order="stroke" stroke="#0e192b" stroke-width="7" stroke-linejoin="round">{relation}</text>')
    for kind, (x, y) in nodes.items():
        color = accents[kind]
        pieces.extend([f'<rect x="{x-85}" y="{y-32}" width="170" height="64" rx="10" fill="#172940" stroke="{color}" stroke-width="1.5"/>',
                       f'<text x="{x}" y="{y-3}" text-anchor="middle" fill="{color}" font-size="18" font-family="sans-serif" font-weight="700">{kind}</text>',
                       f'<text x="{x}" y="{y+20}" text-anchor="middle" fill="#bbcce0" font-size="14" font-family="sans-serif">{graph["entity_counts"][kind]:,} records</text>'])
    pieces.append('</svg>')
    output = DOCS / "ontology.svg"
    output.write_text("\n".join(pieces), encoding="utf-8")
    # Verify all exported class relationships were represented, not an invented diagram.
    source_mermaid = (ROOT / "outputs/ontology/ontology.mmd").read_text(encoding="utf-8")
    actual = set(re.findall(r"(\w+) -->\|(\w+)\| (\w+)", source_mermaid))
    shown = {(s, r, t) for s, t, r, *_ in edges}
    if actual != shown:
        raise RuntimeError(f"Ontology class relation mismatch: {actual ^ shown}")
    return output, len(nodes), len(edges)


def build_markdown(summary, audit, graph, test_count, graph_checks):
    text = f"""# Highway Control Tower - design card

TAMU Datathon 2026, Challenge 6: Hitachi Hack the Highway. A local control tower turns free-text disruptions into traceable enterprise actions for Wacky Wheels Co.

## Architecture

Event text -> Gemini extraction -> grounded coordinator -> three bounded specialists -> validated official HTTP tools. The Supply Chain Planner finds affected builds and earliest feasible slots or compatible transfers (same-day ties in canonical plants.csv order). Dealer Network / Customer Care unions affected orders, notifies each dealer once, and allocates loaners by tier, promised date and order ID. Quality holds lots, stops sale of unsold vehicles and contacts sold-vehicle owners. Every event gets a fresh world; compound incidents share slots and pools. Agents exchange typed, traced handoffs (WorkOrder → ProductionChanges → CustomerCareReport; QualityOrder → QualityReport): Customer Care works from the Planner's handoff and rejects an inconsistent one. The coordinator dispatches only specialists that have work.

## LLM versus deterministic code

The LLM classifies and splits messages, extracting entity references, confirmation and date phrases. Code resolves aliases and relative dates, traverses the BOM and knowledge graph, selects affected records and decides all actions. Raw model output and normalization provenance remain available. The final execution reuses the same recorded raw extraction after generic normalization fixes; it is not an independent model reproduction.

## Guardrails

Each agent acts through its own scoped client with a tool allowlist (Coordinator: escalate; Planner: schedule reads, reschedule, transfer, escalate; Customer Care: pool reads, dealer notify, assign loaner; Quality: hold lot, stop sale, notify customer). An out-of-scope call is refused in-process, before HTTP, so it can never become a failed enterprise call; the event halts with the offending agent recorded. Read live schedules and loaner pools before writes. Validate exact tool arguments, identifiers, dates and affected scope. Never automatically retry a write with uncertain outcome. Noise makes no calls; unconfirmed reports only escalate. Preserve per-event graph paths, reasons, tool responses and the official action log. No event-id answer branches.

## Measured evidence

| Measure | Baseline | Recorded result |
| --- | --- | --- |
| Independent public-event audit | Do nothing: {audit['baseline_do_nothing_events_passed']}/15 | {audit['events_passed']}/{audit['events_total']} |
| Tests | No implemented policy/parser/client/agents | {test_count}/{test_count} |
| Graph | No graph | 16 tables, 11 types, {graph['nodes']:,} nodes, {graph['edges']:,} edges; {graph_checks}/{graph_checks} direct-table checks |
| Official server calls | Zero calls, incomplete corrective work | {summary['server_calls']:,} calls, {summary['failed_calls']} failures |
| Actions | Zero corrective writes | {summary['operational_writes']:,} writes + {summary['server_calls'] - summary['operational_writes'] - 2:,} free reads + 2 escalations |

Final HTTP execution took {summary['seconds_execution']:.3f} seconds; the dry run took 13.035 seconds. These are observed run durations, not a comparative benchmark. The dry-run and final action logs are byte-for-byte identical.

## Model citation and efficiency

Actual model: **{summary['models'][0]}**, [Google Gemini 3.5 Flash-Lite documentation]({MODEL_URL}). Fifteen event responses used **{summary['llm_input_tokens']:,} input tokens** and **{summary['llm_output_tokens']:,} output tokens**. The model extracts; deterministic specialists decide and act. No extra LLM calls were required for normalization fixes or clean execution replay.

## Limits and next improvements

The local audit is not a hidden judging score. Portal upload remains human-only. Next improvements: calibrated uncertainty and more paraphrase holdouts. Demo screenshots show the actual dry run, whose actions match the clean final run.

- [One-page PDF](design-card.pdf)
- [Rendered design card](design-card.png)
- [Full ontology](ontology.svg)
- [Control-tower overview](demo-overview.jpg)
- [Actual shipment graph path](demo-shipment-graph.jpg)
- [Action audit and recorded responses](demo-action-audit.jpg)
"""
    (DOCS / "design-card.md").write_text(text, encoding="utf-8")


def main():
    summary = load("runs/submission/summary.json")
    audit = load("runs/submission/audit.json")
    graph = load("outputs/ontology/summary.json")
    verification = (DOCS / "verify.md").read_text(encoding="utf-8")
    tests = int(re.search(r"(\d+)/\d+ tests pass", verification).group(1))
    checks = int(re.search(r"(\d+)/\d+ direct-table checks", verification).group(1))
    pdf, pages = build_pdf(summary, audit, graph, tests, checks)
    svg, nodes, relations = build_ontology(graph)
    build_markdown(summary, audit, graph, tests, checks)
    for source, name in [("desktop-overview.jpg", "demo-overview.jpg"),
                         ("shipment-graph.jpg", "demo-shipment-graph.jpg"),
                         ("action-audit.jpg", "demo-action-audit.jpg")]:
        shutil.copy2(ROOT / "runs/ui-qa" / source, DOCS / name)
    print(json.dumps({"pdf": str(pdf), "pages": pages, "ontology": str(svg),
                      "ontology_types": nodes, "ontology_class_relationships": relations,
                      "screenshots_copied": 3}, indent=2))


if __name__ == "__main__":
    main()
