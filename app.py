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
ENDPOINT   = os.environ["AZURE_OPENAI_ENDPOINT"]          # e.g. https://<your-resource>.openai.azure.com/
API_KEY    = os.environ["AZURE_OPENAI_API_KEY"]
API_VER    = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")
DEPLOYMENT = os.environ["AZURE_OPENAI_DEPLOYMENT"]        # your deployment name (e.g. gpt-4o-mini)

client = AzureOpenAI(api_key=API_KEY, api_version=API_VER, azure_endpoint=ENDPOINT)

# PDF deps
from PyPDF2 import PdfReader
from xhtml2pdf import pisa
from markupsafe import escape

app = Flask(__name__)

# In-memory store of generated PDFs (simple demo)
GENERATED = {}  # id -> bytes


def extract_pdf_text(file_stream, max_chars=12000):
    """Return lightly-cleaned text from an uploaded PDF (cap to keep prompt small)."""
    try:
        reader = PdfReader(file_stream)
        texts = []
        for page in reader.pages:
            t = page.extract_text() or ""
            texts.append(t)
        raw = "\n".join(texts)
        # light cleanup
        raw = re.sub(r"[ \t]+\n", "\n", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw[:max_chars]
    except Exception:
        return ""


def html_to_pdf_bytes(html: str) -> bytes:
    result = io.BytesIO()
    pisa.CreatePDF(io.StringIO(html), dest=result)
    result.seek(0)
    return result.read()


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate():
    """
    JSON payload when using fetch(); FormData when submitted via form.
    Supports optional PDF 'example' upload to match structure/voice.
    """
    # Detect multipart/form-data (file upload) OR JSON
    example_text = ""
    if request.content_type and "multipart/form-data" in request.content_type:
        # Read simple fields
        subject          = (request.form.get("subject") or "").strip()
        grade            = (request.form.get("grade") or "").strip()
        duration_weeks   = (request.form.get("duration_weeks") or "").strip()
        driving_question = (request.form.get("driving_question") or "").strip()
        scenario         = (request.form.get("scenario") or "").strip()
        topic_mode       = (request.form.get("topic_mode") or "choose").strip()  # 'choose' or 'random'
        modules          = request.form.getlist("modules")
        # Example PDF
        up = request.files.get("example_pdf")
        if up and up.filename.lower().endswith(".pdf"):
            example_text = extract_pdf_text(up.stream)
    else:
        data = request.get_json(force=True)
        subject          = (data.get("subject") or "").strip()
        grade            = (data.get("grade") or "").strip()
        duration_weeks   = (data.get("duration_weeks") or "").strip()
        driving_question = (data.get("driving_question") or "").strip()
        scenario         = (data.get("scenario") or "").strip()
        topic_mode       = (data.get("topic_mode") or "choose").strip()
        modules          = data.get("modules") or []

    # sensible defaults
    if not modules:
        modules = [
            "Overview",
            "Learning Objectives",
            "Timeline & Milestones",
            "Activities & Procedures",
            "Assessment Rubric",
            "Deliverables",
            "Materials"
        ]

    # If user wants random topic, let the model pick a fresh theme BUT keep structure consistent
    topic_line = (
        f"Subject/Topic: {subject}"
        if topic_mode == "choose" and subject
        else "Subject/Topic: (choose a creative, age-appropriate theme that fits the grade level)"
    )

    # Build the mimic prompt using the example text (if provided)
    style_block = ""
    if example_text.strip():
        style_block = (
            "-----\n"
            "STYLE & STRUCTURE EXEMPLAR (analyze and imitate headings, sections order, tone, "
            "level of specificity, and formatting—not the content itself):\n"
            f"{example_text}\n"
            "-----\n"
            "Imitate the structure/voice/section formatting from the exemplar above, but write original content."
        )

    system_prompt = (
        "You are a precise Project-Based Learning (PBL) plan writer. "
        "Match the provided exemplar's section structure, headings style, and professional tone when an exemplar is given. "
        "Return ONLY the requested modules in the given order. "
        "Be classroom-ready, concise, and use numbered steps where appropriate. "
        "For rubrics, give 4 clear levels (4=Exceeds, 3=Meets, 2=Developing, 1=Beginning) with short descriptors."
    )

    user_brief = f"""
PBL Builder Brief
- {topic_line}
- Grade/Level: {grade}
- Duration: {duration_weeks} weeks
- Driving Question: {driving_question}
- Real-World Scenario/Client (optional): {scenario}

Required Output Modules (HEADINGS must match exactly, and appear in this order):
{chr(10).join(f"- {m}" for m in modules)}

Formatting Rules
- Start each module with a clear heading identical to its name.
- Use bullets and numbered steps for procedures.
- Include a milestone schedule aligned to {duration_weeks} weeks.
- Keep tone professional and teacher-friendly.
- No generic filler; provide concrete details (materials lists, checks, success criteria).

{style_block}
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
        text = resp.choices[0].message.content

        # Simple HTML wrapping for PDF export
        safe_title = escape(subject or "PBL Project")
        html = f"""
<!doctype html>
<html><head><meta charset="utf-8">
<title>{safe_title}</title>
<style>
  body {{ font-family: DejaVu Sans, Arial, sans-serif; font-size: 12pt; }}
  h1, h2, h3 {{ margin: 0.6em 0 0.3em; }}
  h1 {{ font-size: 18pt; }}
  h2 {{ font-size: 14pt; }}
  pre {{ white-space: pre-wrap; }}
  ul {{ margin-top: 0; }}
</style>
</head><body>
<h1>{safe_title}</h1>
<pre>{escape(text)}</pre>
</body></html>
        """

        pdf_bytes = html_to_pdf_bytes(html)
        file_id = str(uuid.uuid4())
        GENERATED[file_id] = pdf_bytes

        return jsonify({
            "ok": True,
            "result": text,
            "pdf_id": file_id,
            "pdf_filename": f"{(subject or 'pbl_project').replace(' ', '_')}.pdf"
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/download/<file_id>", methods=["GET"])
def download(file_id):
    pdf = GENERATED.get(file_id)
    if not pdf:
        abort(404)
    return send_file(
        io.BytesIO(pdf),
        mimetype="application/pdf",
        as_attachment=True,
        download_name="pbl_project.pdf"
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

