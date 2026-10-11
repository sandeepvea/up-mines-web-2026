
from flask import Flask, request, render_template_string, Response
import requests
from bs4 import BeautifulSoup
import csv
import io
import re

app = Flask(__name__)

BASE_URL = "https://upmines.upsdc.gov.in"

LAST_RESULTS = []

PAGE = """
<!doctype html>
<html lang="hi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>UP Mines Web Bot</title>
<style>
body {font-family:Arial;background:#eef2f7;padding:12px}
main {max-width:900px;margin:auto;background:white;
padding:18px;border-radius:14px}
h2 {color:#174ea6;text-align:center}
label {display:block;margin-top:12px;font-weight:bold}
input,select,button {
width:100%;padding:12px;margin-top:6px;
box-sizing:border-box;border-radius:8px;border:1px solid #bbb
}
button {background:#174ea6;color:white;border:0;margin-top:18px}
.tablebox {overflow-x:auto;margin-top:18px}
table {border-collapse:collapse;width:100%;font-size:12px}
th,td {border:1px solid #ddd;padding:7px;text-align:left}
th {background:#174ea6;color:white}
.msg {background:#eef5ff;padding:10px;border-radius:8px}
</style>
</head>
<body>
<main>
<h2>UP MINES WEB BOT</h2>

<form method="post">
<label>Search Type</label>
<select name="kind">
<option value="transporter">Transporter / ISTP</option>
<option value="eform">e-Form C</option>
</select>

<label>Start ID</label>
<input name="start_id" placeholder="Starting ID" required>

<label>End ID</label>
<input name="end_id" placeholder="Ending ID" required>

<label>Destination</label>
<input name="destination" placeholder="DEORIA ya ALL" value="ALL">

<button type="submit">Search Data</button>
</form>

{% if message %}
<p class="msg">{{ message }}</p>
{% endif %}

{% if rows %}
<p><b>Results found:</b> {{ rows|length }}</p>
<a href="/download">Download CSV</a>
<div class="tablebox">
<table>
<tr>
{% for h in headers %}<th>{{ h }}</th>{% endfor %}
</tr>
{% for row in rows %}
<tr>
{% for h in headers %}<td>{{ row[h] }}</td>{% endfor %}
</tr>
{% endfor %}
</table>
</div>
{% endif %}
</main>
</body>
</html>
"""


def field(soup, *tokens):
    """Find a value by matching HTML element IDs."""
    for token in tokens:
        for element in soup.find_all(id=re.compile(
            re.escape(token), re.I
        )):
            value = element.get_text(" ", strip=True)
            if not value:
                value = element.get("value", "")
            if value:
                return value.strip()
    return ""


def fetch_record(kind, record_id):
    if kind == "transporter":
        path = (
            "/Transporter/"
            "PrintTransporterFormVehicleCheckValidOrNot.aspx"
        )
    else:
        path = (
            "/licensee/"
            "PrintLicenseeFormVehicleCheckValidOrNot.aspx"
        )

    url = BASE_URL + path

    try:
        response = requests.get(
            url,
            params={"eId": str(record_id)},
            timeout=12,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        if kind == "transporter":
            data = {
                "ID Number": str(record_id),
                "Serial Number": field(
                    soup, "SerialNumber", "Serial_Number"
                ),
                "Mineral": field(
                    soup, "lbl_type_of_mining_mineral"
                ),
                "Quantity": field(
                    soup, "lbl_qty_to_Transport"
                ),
                "Destination": field(
                    soup, "lbl_destination_district"
                ),
                "Generated Date": field(
                    soup, "txt_etp_generated_on"
                ),
            }
        else:
            data = {
                "ID Number": str(record_id),
                "e-Form C No": field(
                    soup, "lbl_eForm_cNo"
                ),
                "Serial Number": field(
                    soup, "SerialNumber", "Serial_Number"
                ),
                "Mineral": field(
                    soup, "lbl_type_of_mining_mineral"
                ),
                "Quantity": field(
                    soup, "lbl_qty_to_Transport_Tonne"
                ),
                "Destination": field(
                    soup, "lbl_destination_district"
                ),
                "Generated Date": field(
                    soup, "txt_eFormC_generated_on"
                ),
                "Valid Upto": field(
                    soup, "ValidUpto", "Valid_Upto",
                    "lbl_valid_upto"
                ),
            }

        # Avoid treating a generic error page as a valid record.
        if not any(
            data.get(key, "").strip()
            for key in ("Serial Number", "Mineral",
                        "Destination", "e-Form C No")
        ):
            return None

        return data

    except requests.RequestException:
        return None


@app.route("/", methods=["GET", "POST"])
def home():
    global LAST_RESULTS

    message = ""
    rows = []
    headers = []

    if request.method == "POST":
        kind = request.form.get("kind", "transporter")
        start_text = request.form.get("start_id", "").strip()
        end_text = request.form.get("end_id", "").strip()
        destination = request.form.get(
            "destination", "ALL"
        ).strip().upper()

        if kind not in ("transporter", "eform"):
            message = "Invalid search type."

        elif not start_text.isdigit() or not end_text.isdigit():
            message = "Start ID aur End ID numeric hone chahiye."

        else:
            start_id = int(start_text)
            end_id = int(end_text)

            if end_id < start_id:
                message = "End ID, Start ID se bada hona chahiye."

            elif end_id - start_id + 1 > 200:
                message = "Ek search mein maximum 200 IDs allowed hain."

            else:
                LAST_RESULTS = []

                for record_id in range(start_id, end_id + 1):
                    record = fetch_record(kind, record_id)

                    if record:
                        record_destination = record.get(
                            "Destination", ""
                        ).strip().upper()

                        if (
                            destination in ("", "ALL")
                            or destination == record_destination
                        ):
                            LAST_RESULTS.append(record)

                rows = LAST_RESULTS

                if rows:
                    headers = list(rows[0].keys())
                    message = (
                        "Search complete. "
                        "CSV download kar sakte ho."
                    )
                else:
                    message = (
                        "Koi matching record nahi mila. "
                        "URL, ID ya website response check karo."
                    )

    return render_template_string(
        PAGE,
        message=message,
        rows=rows,
        headers=headers
    )


@app.route("/download")
def download():
    if not LAST_RESULTS:
        return "Pehle search karo; koi result available nahi hai.", 400

    output = io.StringIO()
    headers = list(LAST_RESULTS[0].keys())

    writer = csv.DictWriter(
        output, fieldnames=headers, extrasaction="ignore"
    )
    writer.writeheader()
    writer.writerows(LAST_RESULTS)

    return Response(
        "\ufeff" + output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition":
            "attachment; filename=up_mines_results.csv"
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
    
