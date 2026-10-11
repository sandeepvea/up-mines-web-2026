
from flask import Flask, request, render_template_string, Response
import requests
import io
import re
import time
from pypdf import PdfReader, PdfWriter

app = Flask(__name__)

BASE_URL = (
    "https://upmines.upsdc.gov.in/"
    "Transporter/historyPrintTransporterFormVehicle.aspx"
)

# Is memory mein matching PDF aur results rahenge.
MATCHED_PDF = b""
RESULTS = []

PAGE = """
<!doctype html>
<html lang="hi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>UP Mines PDF Search</title>
<style>
body {font-family:Arial;background:#eef2f7;padding:12px}
main {max-width:900px;margin:auto;background:white;
padding:18px;border-radius:14px}
h2 {text-align:center;color:#174ea6}
label {display:block;margin-top:14px;font-weight:bold}
input,button {width:100%;padding:12px;margin-top:6px;
box-sizing:border-box;border-radius:8px}
button {background:#174ea6;color:white;border:0;margin-top:18px}
.msg {padding:12px;background:#eef5ff;border-radius:8px;
overflow-wrap:anywhere}
.tablebox {overflow-x:auto}
table {border-collapse:collapse;width:100%;font-size:12px}
th,td {border:1px solid #ddd;padding:7px;text-align:left}
th {background:#174ea6;color:white}
</style>
</head>
<body>
<main>
<h2>UP MINES PDF SEARCH</h2>

<form method="post">
<label>Start eID</label>
<input name="start_id" inputmode="numeric"
placeholder="Starting eID" required>

<label>End eID</label>
<input name="end_id" inputmode="numeric"
placeholder="Ending eID" required>

<label>Destination</label>
<input name="destination" value="ALL"
placeholder="DEORIA ya ALL" required>

<button type="submit">Search PDF</button>
</form>

{% if message %}
<p class="msg">{{ message }}</p>
{% endif %}

{% if rows %}
<h3>Matching PDF Records: {{ rows|length }}</h3>
<div class="tablebox">
<table>
<tr><th>eID</th><th>Id</th><th>Destination Match</th></tr>
{% for row in rows %}
<tr>
<td>{{ row.eid }}</td>
<td>{{ row.id }}</td>
<td>{{ row.destination }}</td>
</tr>
{% endfor %}
</table>
</div>
<p><a href="/download-pdf">Download Matching PDF</a></p>
{% endif %}
</main>
</body>
</html>
"""


def fetch_pdf(eid):
    if not eid.isdigit() or len(eid) <= 5:
        return None, None, "Invalid eID"

    # eID ke last 5 digits hata kar Id.
    record_id = eid[:-5]

    params = {
        "i": "2",
        "Id": record_id,
        "eID": eid,
    }

    try:
        response = requests.get(
            BASE_URL,
            params=params,
            timeout=(4, 8),
            headers={"User-Agent": "Mozilla/5.0"}
        )

        if response.status_code != 200:
            return None, None, (
                "HTTP " + str(response.status_code)
            )

        content = response.content

        # Sirf actual PDF accept karo.
        if not content.lstrip().startswith(b"%PDF-"):
            return None, None, (
                "Server ne PDF nahi bheji; "
                "HTML/error/login response ho sakta hai."
            )

        reader = PdfReader(io.BytesIO(content))

        if reader.is_encrypted:
            return None, None, "PDF encrypted hai"

        text = "\n".join(
            page.extract_text() or ""
            for page in reader.pages
        )

        if not text.strip():
            return None, None, (
                "PDF mein selectable text nahi mila; OCR ki zarurat ho sakti hai."
            )

        return content, text, None

    except Exception as exc:
        return None, None, type(exc).__name__


@app.route("/", methods=["GET", "POST"])
def home():
    global MATCHED_PDF, RESULTS

    message = ""
    rows = []

    if request.method == "POST":
        start = request.form.get("start_id", "").strip()
        end = request.form.get("end_id", "").strip()
        destination = request.form.get(
            "destination", "ALL"
        ).strip().upper()

        RESULTS = []
        MATCHED_PDF = b""

        if (
            not start.isdigit()
            or not end.isdigit()
            or len(start) <= 5
            or len(start) != len(end)
        ):
            message = "Start aur End eID sahi format mein dalo."

        elif int(end) < int(start):
            message = "End eID, Start eID se chhota hai."

        elif int(end) - int(start) > 4:
            message = (
                "Ek baar mein maximum 5 IDs test karo. "
                "Pehle chhoti range se confirm karo."
            )

        else:
            writer = PdfWriter()
            checked = 0
            failed = 0
            matched = 0
            errors = []

            for number in range(int(start), int(end) + 1):
                eid = str(number).zfill(len(start))
                pdf_bytes, pdf_text, error = fetch_pdf(eid)
                checked += 1

                if error:
                    failed += 1
                    if len(errors) < 3:
                        errors.append(eid + ": " + error)
                    continue

                # Destination ko case-insensitive match karo.
                if (
                    destination == "ALL"
                    or destination in pdf_text.upper()
                ):
                    try:
                        reader = PdfReader(io.BytesIO(pdf_bytes))
                        writer.append(reader)

                        RESULTS.append({
                            "eid": eid,
                            "id": eid[:-5],
                            "destination": (
                                "ALL / PDF matched"
                                if destination == "ALL"
                                else destination
                            )
                        })
                        matched += 1
                    except Exception:
                        failed += 1

                # Server par requests ka load kam rakho.
                time.sleep(0.2)

            if matched:
                output = io.BytesIO()
                writer.write(output)
                MATCHED_PDF = output.getvalue()
                rows = RESULTS
                message = (
                    f"Checked: {checked}; "
                    f"Matching PDFs: {matched}; "
                    f"Failed/unreadable: {failed}."
                )
            else:
                message = (
                    f"Checked: {checked}; Matching PDFs: 0; "
                    f"Failed/unreadable: {failed}."
                )

            if errors:
                message += " Details: " + " | ".join(errors)

    return render_template_string(
        PAGE,
        message=message,
        rows=rows
    )


@app.route("/download-pdf")
def download_pdf():
    if not MATCHED_PDF:
        return "Pehle matching PDF search karo.", 404

    return Response(
        MATCHED_PDF,
        mimetype="application/pdf",
        headers={
            "Content-Disposition":
            "attachment; filename=up_mines_matching_results.pdf"
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
    
