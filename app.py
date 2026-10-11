from flask import Flask, request, render_template_string, Response
import requests
from bs4 import BeautifulSoup
import csv
import io
import re
import time

app = Flask(__name__)

TRANSPORTER_URL = (
    "https://upmines.upsdc.gov.in/"
    "Transporter/historyPrintTransporterFormVehicle.aspx"
)

# e-Form C ka purana route.
# Is route ko portal par verify karna zaroori hai.
EFORM_URL = (
    "https://upmines.upsdc.gov.in/"
    "licensee/PrintLicenseeFormVehicleCheckValidOrNot.aspx"
)

LAST_RESULTS = []

PAGE = """
<!doctype html>
<html lang="hi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>UP Mines Web Bot</title>
<style>
body {
    font-family: Arial, sans-serif;
    background: #eef2f7;
    padding: 12px;
}
main {
    max-width: 950px;
    margin: auto;
    background: white;
    padding: 18px;
    border-radius: 14px;
}
h2 { color: #174ea6; text-align: center; }
label { display: block; margin-top: 13px; font-weight: bold; }
input, select, button {
    width: 100%;
    padding: 12px;
    margin-top: 6px;
    box-sizing: border-box;
    border-radius: 8px;
}
button {
    background: #174ea6;
    color: white;
    border: 0;
    margin-top: 18px;
}
.msg {
    background: #eef5ff;
    padding: 12px;
    border-radius: 8px;
    overflow-wrap: anywhere;
}
.tablebox { overflow-x: auto; margin-top: 18px; }
table { border-collapse: collapse; width: 100%; font-size: 12px; }
th, td { border: 1px solid #ddd; padding: 7px; text-align: left; }
th { background: #174ea6; color: white; }
</style>
</head>
<body>
<main>
<h2>UP MINES WEB BOT</h2>

<form method="post">
<label>Search Type</label>
<select name="kind">
    <option value="transporter">Transporter / ISTP</option>
    <option value="eform">e-Form C (route verify karna hoga)</option>
</select>

<label>Start eID</label>
<input name="start_id" inputmode="numeric"
       placeholder="Starting eID" required>

<label>End eID</label>
<input name="end_id" inputmode="numeric"
       placeholder="Ending eID" required>

<label>Destination</label>
<input name="destination" placeholder="DEORIA ya ALL" value="ALL">

<button type="submit">Search Data</button>
</form>

{% if message %}
<p class="msg">{{ message }}</p>
{% endif %}

{% if rows %}
<p><b>Results found:</b> {{ rows|length }}</p>
<p><a href="/download">Download CSV</a></p>
<div class="tablebox">
<table>
<thead>
<tr>
{% for h in headers %}<th>{{ h }}</th>{% endfor %}
</tr>
</thead>
<tbody>
{% for row in rows %}
<tr>
{% for h in headers %}<td>{{ row[h] }}</td>{% endfor %}
</tr>
{% endfor %}
</tbody>
</table>
</div>
{% endif %}
</main>
</body>
</html>
"""


def get_field(soup, *names):
    """HTML IDs/labels se field ka text nikalna."""
    for name in names:
        pattern = re.compile(re.escape(name), re.I)

        for element in soup.find_all(id=pattern):
            value = element.get("value", "").strip()

            if not value:
                value = element.get_text(" ", strip=True)

            if value:
                return value

    return ""


def fetch_record(kind, eid):
    if kind == "transporter":
        url = TRANSPORTER_URL

        # eID ke aakhiri 5 digits hata kar Id banao.
        params = {
            "i": "2",
            "Id": eid[:-5],
            "eID": eid,
        }

    elif kind == "eform":
        url = EFORM_URL
        params = {"eId": eid}

    else:
        return None, "Invalid search type"

    try:
        response = requests.get(
            url,
            params=params,
            timeout=(5,12),
            headers={"User-Agent": "Mozilla/5.0"}
        )

        if response.status_code != 200:
            return None, "HTTP " + str(response.status_code)

        soup = BeautifulSoup(response.text, "html.parser")

        if kind == "transporter":
            record = {
                "eID": eid,
                "Id": eid[:-5],
                "Serial Number": get_field(
                    soup, "SerialNumber", "Serial_Number"
                ),
                "Mineral": get_field(
                    soup, "lbl_type_of_mining_mineral"
                ),
                "Quantity": get_field(
                    soup, "lbl_qty_to_Transport"
                ),
                "Destination": get_field(
                    soup, "lbl_destination_district"
                ),
                "Generated Date": get_field(
                    soup, "txt_etp_generated_on"
                ),
            }
        else:
            record = {
                "eID": eid,
                "e-Form C No": get_field(
                    soup, "lbl_eForm_cNo"
                ),
                "Serial Number": get_field(
                    soup, "SerialNumber", "Serial_Number"
                ),
                "Mineral": get_field(
                    soup, "lbl_type_of_mining_mineral"
                ),
                "Quantity": get_field(
                    soup, "lbl_qty_to_Transport_Tonne"
                ),
                "Destination": get_field(
                    soup, "lbl_destination_district"
                ),
                "Generated Date": get_field(
                    soup, "txt_eFormC_generated_on"
                ),
            }

        # Agar koi expected field na mile to use success na maano.
        useful_fields = [
            value for key, value in record.items()
            if key not in ("eID", "Id") and value
        ]

        if not useful_fields:
            return None, (
                "Page mila, lekin expected fields nahi mile. "
                "HTML selectors verify karne honge."
            )

        return record, None

    except requests.RequestException as exc:
        return None, "Request error: " + str(exc)


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
            message = "Invalid Search Type."

        elif (
            not start_text.isdigit()
            or not end_text.isdigit()
            or len(start_text) <= 5
            or len(end_text) <= 5
        ):
            message = "Dono eID numeric hone chahiye aur 5 digits se lambe hon."

        elif len(start_text) != len(end_text):
            message = "Start aur End eID ki length same honi chahiye."

        else:
            start_num = int(start_text)
            end_num = int(end_text)

            if end_num < start_num:
                message = "End eID, Start eID se chhota hai."

            elif end_num - start_num > 99:
                message = "Ek baar mein maximum 100 eID check kar sakte ho."

            else:
                LAST_RESULTS = []
                errors = 0

                for number in range(start_num, end_num + 1):
                    eid = str(number).zfill(len(start_text))

                    record, error = fetch_record(kind, eid)

                    if record:
                        record_destination = record.get(
                            "Destination", ""
                        ).strip().upper()

                        if (
                            destination in ("", "ALL")
                            or destination == record_destination
                        ):
                            LAST_RESULTS.append(record)
                    else:
                        errors += 1

                    # Portal par requests ka load kam rakho.
                    time.sleep(0.25)

                rows = LAST_RESULTS

                if rows:
                    headers = list(rows[0].keys())
                    message = (
                        "Search complete. Matching records: "
                        + str(len(rows))
                        + ". Unreadable/failed records: "
                        + str(errors)
                    )
                else:
                    message = (
                        "Koi matching record nahi mila. Failed/unreadable: "
                        + str(errors)
                        + ". URL aur HTML fields verify karne honge."
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
        return "Pehle search karke records nikalo.", 400

    output = io.StringIO()
    headers = list(LAST_RESULTS[0].keys())

    writer = csv.DictWriter(
        output,
        fieldnames=headers,
        extrasaction="ignore"
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
                
