
from flask import Flask, request, render_template_string, Response
import requests
import io
import time
from pypdf import PdfReader, PdfWriter

app = Flask(__name__)

BASE_URL = (
    "http://upmines.upsdc.gov.in/"
    "Transporter/PrintTransporterFormVehicleCheckValidOrNot.aspx"
)

MATCHED_PDF = b""

PAGE = """
<!doctype html>
<html lang="hi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>UP Mines PDF Search</title>
<style>
body{font-family:Arial;background:#eef2f7;padding:12px}
main{max-width:900px;margin:auto;background:white;padding:18px;border-radius:14px}
h2{text-align:center;color:#174ea6}
label{display:block;margin-top:14px;font-weight:bold}
input,button{width:100%;padding:12px;margin-top:6px;box-sizing:border-box;border-radius:8px}
button{background:#174ea6;color:white;border:0;margin-top:18px}
.msg{padding:12px;background:#eef5ff;border-radius:8px;overflow-wrap:anywhere}
table{border-collapse:collapse;width:100%;font-size:12px}
th,td{border:1px solid #ddd;padding:7px;text-align:left}
th{background:#174ea6;color:white}
</style>
</head>
<body>
<main>
<h2>UP MINES PDF SEARCH</h2>
<form method="post">
<label>Start eID</label>
<input name="start_id" inputmode="numeric" required>
<label>End eID</label>
<input name="end_id" inputmode="numeric" required>
<label>Destination (ALL bhi likh sakte ho)</label>
<input name="destination" value="ALL" required>
<button type="submit">Search PDF</button>
</form>
{% if message %}<p class="msg">{{ message }}</p>{% endif %}
{% if rows %}
<h3>Matching PDFs: {{ rows|length }}</h3>
<table>
<tr><th>eID</th><th>Destination</th></tr>
{% for row in rows %}
<tr><td>{{ row.eid }}</td><td>{{ row.destination }}</td></tr>
{% endfor %}
</table>
<p><a href="/download-pdf">Download Matching PDF</a></p>
{% endif %}
</main>
</body>
</html>
"""



def fetch_pdf(eid):
    if not eid.isdigit() or len(eid) <= 5:
        return None, None, "Invalid eID"

    try:
        url = BASE_URL + "?eId=" + eid

        response = requests.get(
            url,
            timeout=(10, 60),
            headers={"User-Agent": "Mozilla/5.0"}
        )

        if response.status_code != 200:
            return None, None, "HTTP " + str(response.status_code)

        content = response.content

        if not content.lstrip().startswith(b"%PDF-"):
            return None, None, (
                "PDF nahi mili. Content-Type: "
                + response.headers.get("Content-Type", "unknown")
            )

        reader = PdfReader(io.BytesIO(content))

        if reader.is_encrypted:
            return None, None, "PDF encrypted hai"

        text = "\n".join(
            page.extract_text() or "" for page in reader.pages
        )

        if not text.strip():
            return None, None, "PDF mein selectable text nahi mila"

        return content, text, None

    except requests.exceptions.Timeout:
        return None, None, "UP Mines server timeout"
    except requests.exceptions.RequestException as exc:
        return None, None, "Network error: " + type(exc).__name__
    except Exception as exc:
        return None, None, "PDF error: " + type(exc).__name__



@app.route("/", methods=["GET", "POST"])
def home():
    global MATCHED_PDF

    MATCHED_PDF = b""
    rows = []
    message = ""

    if request.method == "POST":
        start = request.form.get("start_id", "").strip()
        end = request.form.get("end_id", "").strip()
        destination = request.form.get("destination", "ALL").strip().upper()

        if not start.isdigit() or not end.isdigit():
            message = "Sirf numeric eID dalo."
        elif len(start) != len(end) or len(start) <= 5:
            message = "Start aur End eID ki length sahi rakho."
        elif int(end) < int(start):
            message = "End eID, Start eID se chhota hai."
        elif int(end) - int(start) > 4:
            message = "Ek baar mein maximum 5 IDs search karo."
        else:
            writer = PdfWriter()
            checked = failed = matched = 0
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

                normalized_text = " ".join(pdf_text.upper().split())

                if destination == "ALL" or destination in normalized_text:
                    try:
                        writer.append(PdfReader(io.BytesIO(pdf_bytes)))
                        rows.append({
                            "eid": eid,
                            "destination": "ALL" if destination == "ALL" else destination
                        })
                        matched += 1
                    except Exception:
                        failed += 1

                time.sleep(0.2)

            if matched:
                output = io.BytesIO()
                writer.write(output)
                MATCHED_PDF = output.getvalue()
                message = (
                    f"Checked: {checked}; Matching PDFs: {matched}; "
                    f"Failed/unreadable: {failed}."
                )
            else:
                message = (
                    f"Checked: {checked}; Matching PDFs: 0; "
                    f"Failed/unreadable: {failed}."
                )

            if errors:
                message += " Details: " + " | ".join(errors)

    return render_template_string(PAGE, message=message, rows=rows)


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
