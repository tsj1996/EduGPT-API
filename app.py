import os, io, re, uuid
from flask import Flask, render_template, request, jsonify, send_file, abort
from openai import AzureOpenAI
from xhtml2pdf import pisa
from markupsafe import escape

# ---------- Azure OpenAI config ----------
# Expect these env vars in your App Service:
#   AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_API_VERSION (default below), AZURE_OPENAI_DEPLOYMENT
ENDPOINT   = os.environ["AZURE_OPENAI_ENDPOINT"]
API_KEY    = os.environ["AZURE_OPENAI_API_KEY"]
API_VER    = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")
DEPLOYMENT = os.environ["AZURE_OPENAI_DEPLOYMENT"]  # your deployment name (e.g., "gpt-4o-mini" or custom)

client = AzureOpenAI(api_key=API_KEY, api_version=API_VER, azure_endpoint=ENDPOINT)

app = Flask(__name__)
GENERATED = {}  # id -> pdf bytes


# ---------- Defaults ----------
DEFAULTS = {
    "grade": "Grade 10",
    "duration_weeks": "4",
    "driving_question": "How might we design and validate a solution that improves a real-world system?",
    "scenario": "Partner with a relevant stakeholder to gather constraints and solicit feedback.",
    "pbl_rules": (
        "- Authentic problem & public audience\n"
        "- Student inquiry, iteration, and reflection\n"
        "- Clear success criteria & rubric\n"
        "- Differentiation/UDL where appropriate\n"
        "- Evidence at milestones (brief overview only)"
    ),
}

# ---------- Helpers ----------
def html_to_pdf_bytes(full_html: str) -> bytes:
    """Render HTML → PDF bytes via xhtml2pdf."""
    buf = io.BytesIO()
    pisa.CreatePDF(io.StringIO(full_html), dest=buf)
    buf.seek(0)
    return buf.read()


_equation_block = re.compile(r"\\\[(.+?)\\\]", re.DOTALL)  # \[ ... \]
_equation_inline = re.compile(r"\$(.+?)\$", re.DOTALL)     # $ ... $

def decorate_equations(html_fragment: str) -> str:
    """
    Convert LaTeX-like equations into styled spans/blocks that look good in PDF.
    (xhtml2pdf cannot render LaTeX; we present equations as monospaced text boxes.)
    """
    def block_sub(m):
        expr = m.group(1).strip()
        return f"<div class='equation-block'><code>{escape(expr)}</code></div>"

    def inline_sub(m):
        expr = m.group(1).strip()
        return f"<span class='equation-inline'><code>{escape(expr)}</code></span>"

    # First block equations, then inline
    out = _equation_block.sub(block_sub, html_fragment)
    out = _equation_inline.sub(inline_sub, out)
    return out


def build_cover_html(title, topic, grade, duration_weeks, driving_question, scenario):
    safe = {
        "title": escape(title or "Project"),
        "topic": escape(topic or "—"),
        "grade": escape(grade or "—"),
        "dur": escape(duration_weeks or "—"),
        "dq": escape(driving_question or "—"),
        "scn": escape(scenario or "—"),
    }
    return f"""
<div class="cover">
  <div class="brandbar"></div>
  <h1>{safe['title']}</h1>
  <h3>Topic: {safe['topic']}</h3>
  <table class="meta">
    <tr><th>Grade/Level</th><td>{safe['grade']}</td></tr>
    <tr><th>Duration</th><td>{safe['dur']} week(s)</td></tr>
    <tr><th>Driving Question</th><td>{safe['dq']}</td></tr>
    <tr><th>Scenario</th><td>{safe['scn']}</td></tr>
  </table>
</div>
<div class="pagebreak"></div>
"""


def build_shell_html(cover_html: str, body_html: str) -> str:
    """Wrap cover + body into a styled, PDF-friendly template."""
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<title>Project Brief</title>
<style>
  /* Page layout & typography (xhtml2pdf-safe CSS) */
  body {{ font-family: DejaVu Sans, Arial, sans-serif; font-size: 11.5pt; line-height: 1.45; margin: 0.8in; color: #222; }}
  h1 {{ font-size: 22pt; margin: 0.1em 0 0.2em; text-align: center; color: #1a2855; }}
  h2 {{ font-size: 15pt; border-bottom: 1px solid #999; padding-bottom: 4px; margin-top: 1.1em; color: #1a2855; }}
  h3 {{ font-size: 12.5pt; margin-top: 0.9em; color: #2b3e7a; }}
  p  {{ margin: 0.4em 0; }}
  ul, ol {{ margin: 0.4em 0 0.4em 1.2em; }}
  table {{ border-collapse: collapse; width: 100%; margin: 0.6em 0; }}
  th, td {{ border: 1px solid #666; padding: 6px; text-align: left; vertical-align: top; }}

  /* Cover */
  .cover {{ text-align: center; margin: 0 auto 0.2in; }}
  .brandbar {{ height: 10px; background: #1a2855; margin-bottom: 12px; }}
  .meta {{ margin: 0.4in auto 0; width: 85%; }}
  .meta th {{ width: 28%; background: #f2f4fa; color: #1a2855; }}

  /* Info boxes */
  .box {{ border: 1px solid #c9cfdf; background: #f5f7fc; padding: 10px; margin: 0.7em 0; }}
  .muted {{ color: #555; }}

  /* Equation presentation (monospace blocks/spans) */
  code {{ font-family: "DejaVu Sans Mono", monospace; font-size: 10.5pt; }}
  .equation-block {{
    border: 1px solid #b8c1e0; background: #eef2ff; padding: 8px; margin: 8px 0;
  }}
  .equation-inline {{
    border: 1px solid #d6dcef; background: #f3f6ff; padding: 1px 3px;
  }}

  /* Page breaks */
  .pagebreak {{ page-break-before: always; }}
</style>
</head>
<body>
{cover_html}
{body_html}
</body>
</html>"""


# ---------- Routes ----------
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate():
    data = request.get_json(force=True)

    # Required
    title = (data.get("title") or "").strip()
    topic = (data.get("topic") or "").strip()
    if not title or not topic:
        return jsonify({"ok": False, "error": "Title and Topic are required."}), 400

    # Optional (with defaults)
    grade            = (data.get("grade") or DEFAULTS["grade"]).strip()
    duration_weeks   = (data.get("duration_weeks") or DEFAULTS["duration_weeks"]).strip()
    driving_question = (data.get("driving_question") or DEFAULTS["driving_question"]).strip()
    scenario         = (data.get("scenario") or DEFAULTS["scenario"]).strip()
    pbl_rules        = DEFAULTS["pbl_rules"]

    # ---------- Strong, style-focused prompt (less schedule, more prompt detail + equations) ----------
    system_prompt = (
        "You are a precise PBL assignment writer. Produce a professional, teacher-ready project handout "
        "in clean HTML (BODY FRAGMENT ONLY). Use <h2>, <h3>, <p>, <ul>, <ol>, <table>, <thead>, <tbody>, "
        "<tr>, <th>, <td>, and <div> (with class names if needed). Do NOT return <html> or <body> tags. "
        "Focus on Introduction/Background and Detailed Requirements. Include relevant analytical formulas/"
        "equations written in LaTeX-like notation using $...$ (inline) or \\[...\\] (block). "
        "Provide a concise milestone overview (single short table) but avoid week-by-week schedules."
    )

    user_brief = f"""
PROJECT BRIEF INPUTS
- Title: {title}
- Topic/Subject: {topic}
- Grade/Level: {grade}
- Duration: {duration_weeks} weeks
- Driving Question: {driving_question}
- Scenario: {scenario}

PBL RULES TO REFLECT
{pbl_rules}

REQUIRED SECTIONS (USE THESE EXACT TITLES AS <h2>):
1) Introduction / Background
2) Objectives
3) Detailed Requirements (with related equations if relevant)
4) Activities & Procedures
5) Deliverables
6) Assessment Rubric (4 levels: 4=Exceeds, 3=Meets, 2=Developing, 1=Beginning)
7) Materials
8) Milestone Overview

STYLE & CONTENT RULES
- BODY FRAGMENT ONLY (no <html> or <body>).
- Use informative paragraphs and bullet/numbered lists.
- Include at least 1–2 equations that fit the topic, written as $...$ or \\[...\\].
- Prefer concrete inputs, checks, and constraints over generic fluff.
- Milestone Overview: a single brief table (no full weekly breakdown).
- Keep tone academic, clear, and immediately usable in class.
"""

    try:
        resp = client.chat.completions.create(
            model=DEPLOYMENT,
            temperature=0.25,
            max_tokens=2100,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_brief},
            ],
        )
        fragment = resp.choices[0].message.content or ""
        fragment = fragment.strip()

        # Decorate equations for nicer PDF presentation
        fragment = decorate_equations(fragment)

        # Build final HTML
        cover_html = build_cover_html(title, topic, grade, duration_weeks, driving_question, scenario)
        full_html  = build_shell_html(cover_html, fragment)

        pdf_bytes = html_to_pdf_bytes(full_html)
        file_id = str(uuid.uuid4())
        GENERATED[file_id] = pdf_bytes

        return jsonify({
            "ok": True,
            "result_html": fragment,  # show in UI preview
            "pdf_id": file_id,
            "pdf_filename": f"{title.replace(' ', '_')}.pdf"
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/download/<file_id>", methods=["GET"])
def download(file_id):
    pdf = GENERATED.get(file_id)
    if not pdf:
        abort(404)
    return send_file(io.BytesIO(pdf), mimetype="application/pdf",
                     as_attachment=True, download_name="project_brief.pdf")


if __name__ == "__main__":
    # Local dev only; Azure will run via gunicorn
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
