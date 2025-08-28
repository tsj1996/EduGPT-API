import os, io, re, uuid
from flask import Flask, render_template, request, jsonify, send_file, abort
from openai import AzureOpenAI

# Optional for local dev; harmless in Azure
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ---- Azure OpenAI config from environment ----
ENDPOINT   = os.environ["AZURE_OPENAI_ENDPOINT"]          # e.g., https://<resource>.openai.azure.com/
API_KEY    = os.environ["AZURE_OPENAI_API_KEY"]
API_VER    = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")
DEPLOYMENT = os.environ["AZURE_OPENAI_DEPLOYMENT"]        # your deployment name (gpt-4o-mini or similar)

client = AzureOpenAI(api_key=API_KEY, api_version=API_VER, azure_endpoint=ENDPOINT)

# PDF deps
from xhtml2pdf import pisa
from markupsafe import escape

app = Flask(__name__)
GENERATED = {}  # id -> bytes


def html_to_pdf_bytes(html: str) -> bytes:
    buf = io.BytesIO()
    pisa.CreatePDF(io.StringIO(html), dest=buf)
    buf.seek(0)
    return buf.read()


# --------- Defaults (used if user leaves fields blank) ----------
DEFAULTS = {
    "grade": "Grade 9",
    "duration_weeks": "4",
    "driving_question": "How might we design a solution that improves our community’s sustainability?",
    "scenario": "Partner with a local stakeholder to gather authentic constraints and feedback.",
    "modules": [
        "Overview",
        "Learning Objectives",
        "Timeline & Milestones",
        "Activities & Procedures",
        "Assessment Rubric",
        "Deliverables",
        "Materials"
    ],
    # short PBL rules/guardrails used by the prompt
    "pbl_rules": (
        "- Authentic problem with real audience\n"
        "- Student voice/choice where possible\n"
        "- Inquiry & research → iteration → reflection\n"
        "- Explicit public product with rubric\n"
        "- Milestones aligned to timeline; checkpoint evidence\n"
        "- Differentiation/UDL accommodations\n"
        "- Academic standards and success criteria"
    )
}


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate():
    data = request.get_json(force=True)

    # ----- Mandatory -----
    title  = (data.get("title") or "").strip()
    topic  = (data.get("topic") or "").strip()
    if not title or not topic:
        return jsonify({"ok": False, "error": "Title and Topic are required."}), 400

    # ----- Optional with defaults -----
    grade            = (data.get("grade") or DEFAULTS["grade"]).strip()
    duration_weeks   = (data.get("duration_weeks") or DEFAULTS["duration_weeks"]).strip()
    driving_question = (data.get("driving_question") or DEFAULTS["driving_question"]).strip()
    scenario         = (data.get("scenario") or DEFAULTS["scenario"]).strip()
    modules          = data.get("modules") or DEFAULTS["modules"]
    pbl_rules        = DEFAULTS["pbl_rules"]

    # ----- Prompt (imitate assignment-brief style; follow PBL rules) -----
    system_prompt = (
        "You are a precise Project-Based Learning (PBL) plan writer. "
        "Write a teacher-ready assignment brief that mirrors a professional syllabus/assignment sheet: "
        "clear headings, concise bullets, numbered steps, legible rubric, and a milestone timeline. "
        "Return ONLY the requested modules, in the given order, with those exact headings. "
        "Use 4-level analytic rubrics (4=Exceeds, 3=Meets, 2=Developing, 1=Beginning) with short descriptors. "
        "Incorporate the provided inputs verbatim where appropriate."
    )

    # This block nudges the structure/tone toward a classic project description brief (cover, objectives, deliverables, etc.).
    exemplar_style = (
        "Match the tone/structure of a formal course project brief: objective, requirements, "
        "deliverables, professional tone, concise formatting, actionable lists, and clear due items."
    )

    user_brief = f"""
PROJECT BRIEF INPUTS
- Title: {title}
- Topic/Subject: {topic}
- Grade/Level: {grade}
- Duration: {duration_weeks} weeks
- Driving Question: {driving_question}
- Scenario: {scenario}

REQUIRED OUTPUT MODULES (use these exact headings, in this order):
{chr(10).join(f"- {m}" for m in modules)}

PBL RULES (ensure these are reflected):
{pbl_rules}

STYLE TARGET:
{exemplar_style}

OUTPUT RULES:
- Start each module with its heading exactly as listed.
- Provide a week-aligned milestone schedule spanning {duration_weeks} weeks.
- Include materials lists and concrete checks for readiness.
- Keep language teacher-friendly and concise; avoid filler.
- Do not include any section not listed in the modules.
"""

    try:
        resp = client.chat.completions.create(
            model=DEPLOYMENT,
            temperature=0.3,
            max_tokens=2000,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_brief},
            ],
        )
        body_text = resp.choices[0].message.content

        # ----- PDF layout: cover + summary + body -----
        safe_title  = escape(title)
        safe_topic  = escape(topic)
        safe_grade  = escape(grade)
        safe_dur    = escape(duration_weeks)
        safe_dq     = escape(driving_question)
        safe_scn    = escape(scenario)
        mod_list    = "".join(f"<li>{escape(m)}</li>" for m in modules)

        html = f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>{safe_title}</title>
<style>
  body {{ font-family: DejaVu Sans, Arial, sans-serif; font-size: 12pt; line-height: 1.35; }}
  h1, h2 {{ margin: 0.6em 0 0.3em; }}
  h1 {{ font-size: 18pt; }}
  h2 {{ font-size: 14pt; border-bottom: 1px solid #999; padding-bottom: 4px; }}
  table.summary td {{ padding: 4px 8px; vertical-align: top; }}
  .muted {{ color: #555; }}
  pre {{ white-space: pre-wrap; }}
  .pagebreak {{ page-break-before: always; }}
</style>
</head><body>

<h1>{safe_title}</h1>
<h2>Project Summary</h2>
<table class="summary">
  <tr><td><strong>Topic/Subject</strong></td><td>{safe_topic}</td></tr>
  <tr><td><strong>Grade/Level</strong></td><td>{safe_grade}</td></tr>
  <tr><td><strong>Duration</strong></td><td>{safe_dur} week(s)</td></tr>
  <tr><td><strong>Driving Question</strong></td><td>{safe_dq}</td></tr>
  <tr><td><strong>Scenario</strong></td><td>{safe_scn}</td></tr>
  <tr><td><strong>Modules</strong></td><td><ul>{mod_list}</ul></td></tr>
</table>

<div class="pagebreak"></div>

<pre>{escape(body_text)}</pre>
</body></html>"""

        pdf_bytes = html_to_pdf_bytes(html)
        file_id = str(uuid.uuid4())
        GENERATED[file_id] = pdf_bytes

        return jsonify({
            "ok": True,
            "result": body_text,
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
                     as_attachment=True, download_name="pbl_project.pdf")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

