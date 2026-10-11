from flask import Flask, request, render_template_string
import requests
import io
import re
import time
from pypdf import PdfReader

app = Flask(__name__)

BASE_URL = (
    "http://upmines.upsdc.gov.in/"
    "Transporter/PrintTransporterFormVehicleCheckValidOrNot.aspx"
)

# Har search mein adhiktam 50 IDs
MAX_IDS = 50

FIELDS = {
    "ISTP No": [
        r"ISTP\s*No\.?",
    ],
    "Transporter": [
        r"Name\s+Of\s+Transporter",
    ],
    "Transporter ID": [
        r"Transporter\s+Id",
    ],
    "Mineral": [
        r"Name\s+Of\s+Mineral",
    ],
    "Quantity": [
        r"QTY\s+Transported\s+in\s+Cubic\s+Meter",
    ],
    "Destination": [
        r"Destination\s+District",
    ],
    "Distance": [
        r"Distance\s*\(Approx\s+in\s+K\.?M\.?\)",
    ],
    "Generated On": [
        r"Transit\s+Pass\s+Generated\s+On",
    ],
    "Valid Upto": [
        r"Transit\s+Pass\s+Valid\s+Upto",
    ],
    "Origin District": [
        r"Loading\s+From\s*\(Origin\s+District\)",
    ],
    "Origin State": [
        r"Loading\s+From\s*\(Origin\s+State\)",
    ],
    "Origin Pass No": [
        r"Origin\s+Transit\s+Pass\s+No",
    ],
    "Origin Pass Date": [
        r"Origin\s+Transit\s+Pass\s+Generation\s+Date",
    ],
    "Delivery Address": [
        r"Destination\s*\(Delivery\s+Address\)",
    ],
    "Vehicle Number": [
        r"Vehicle\s+Number",
    ],
    "Vehicle Type": [
        r"Type\s+Of\s+Vehicle",
    ],
    "Driver Name": [
        r"Name\s+Of\s+Driver",
    ],
}

PAGE = r"""
<!doctype html>
<html lang="hi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>UP Mines ISTP Checker</title>
<style>
body {
    font-family: Arial, sans-serif;
    background: #eef2f7;
    margin: 0;
    padding: 12px;
    color: #172033;
}
main {
    max-width: 1100px;
    margin: auto;
    background: white;
    padding: 16px;
    border-radius: 14px;
}
h2 { text-align: center; color: #174ea6; }
label { display: block; margin-top: 13px; font-weight: bold; }
input, button {
    width: 100%;
    padding: 12px;
    margin-top: 6px;
    box-sizing: border-box;
    border-radius: 8px;
}
input { border: 1px solid #cbd5e1; }
button {
    background: #174ea6;
    color: white;
    border: 0;
    font-weight: bold;
    margin-top: 18px;
}
.msg {
    padding: 12px;
    background: #eef5ff;
    border-radius: 8px;
    overflow-wrap: anywhere;
}
.table-wrap { overflow-x: auto; }
table {
    border-collapse: collapse;
    width: 100%;
    font-size: 12px;
    margin-top: 12px;
}
th, td {
    border: 1px solid #d5dbe5;
    padding: 8px;
    text-align: left;
    overflow-wrap: anywhere;
}
th { background: #174ea6; color: white; }
small { color: #526174; }
</style>
</head>
<body>
<main>
<h2>UP MINES ISTP CHECKER</h2>

<form method="post">
<label>Start ID</label>
<input name="start_id" inputmode="numeric"
       value="{{ start }}" required>

<label>End ID</label>
<input name="end_id" inputmode="numeric"
       value="{{ end }}" required>

<label>Destinations (comma-separated)</label>
<input name="destinations"
       value="{{ destinations }}"
       placeholder="PURNIA BIHAR, DEORIA, SONBHADRA"
       required>

<button type="submit">Search ISTP</button>
</form>

{% if message %}
<p class="msg">{{ message }}</p>
{% endif %}

{% if stats %}
<p class="msg">
Checked: {{ stats.checked }} |
Matched: {{ stats.matched }} |
Failed/unreadable: {{ stats.failed }}
</p>
{% endif %}

{% if errors %}
<h3>Errors (pehli 10)</h3>
<ul>
{% for error in errors %}
<li>{{ error }}</li>
{% endfor %}
</ul>
{% endif %}

{% if rows %}
<h3>Matching HTML Results: {{ rows|length }}</h3>
<div class="table-wrap">
<table>
<thead>
<tr>
{% for heading in headings %}
<th>{{ heading }}</th>
{% endfor %}
</tr>
</thead>
<tbody>
{% for row in rows %}
<tr>
{% for heading in headings %}
<td>{{ row.get(heading, '') }}</td>
{% endfor %}
</tr>
{% endfor %}
</tbody>
</table>
</div>
{% endif %}

<p><small>
Sirf destination-match wale records dikhaye jaate hain.
Timeout ya unreadable record ko failed mein gina jayega.
</small></p>
</main>
</body>
</html>
"""

def fetch_record(eid):
    if not eid.isdigit() or len(eid) <= 5:
        return None, "Invalid eID"

    try:
        response = requests.get(
            BASE_URL,
            params={"eId": eid},
            timeout=(8, 25),
            headers={"User-Agent": "Mozilla/5.0"}
        )

        if response.status_code != 200:
            return None, "HTTP " + str(response.status_code)

        content = response.content

        if not content.lstrip().startswith(b"%PDF-"):
            return None, (
                "PDF/text response nahi mili; Content-Type: "
                + response.headers.get("Content-Type", "unknown")
            )

        reader = PdfReader(io.BytesIO(content))

        if reader.is_encrypted:
            return None, "Encrypted PDF"

        text = "\n".join(
            page.extract_text() or ""
            for page in reader.pages
        )

        if not text.strip():
            return None, "PDF text unreadable"

        return parse_record(text, eid), None

    except requests.exceptions.Timeout:
        return None, "UP Mines server timeout"
    except requests.exceptions.RequestException as exc:
        return None, "Network error: " + type(exc).__name__
    except Exception as exc:
        return None, "Read error: " + type(exc).__name__


def parse_record(text, eid):
    # PDF text mein line breaks/spaces ko normalize karo
    text = re.sub(r"\s+", " ", text).strip()

    # Numbered field labels ko boundaries ki tarah use karo.
    # Har label ke baad ka text agle label tak uski value hai.
    labels = [
        ("ISTP No", r"1\s*[\.\)]\s*ISTP\s*No\.?"),
        ("Transporter", r"2\s*[\.\)]\s*Name\s+Of\s+Transporter"),
        ("Transporter ID", r"3\s*[\.\)]\s*Transporter\s+Id"),
        ("Mineral", r"7\s*[\.\)]\s*Name\s+Of\s+Mineral"),
        ("Quantity", r"6\s*[\.\)]\s*QTY\s+Transported\s+in\s+Cubic\s+Meter"),
        ("Destination", r"8\s*[\.\)]\s*Destination\s+District"),
        ("Distance", r"9\s*[\.\)]\s*Distance\s*\(Approx\s+in\s+K\.?M\.?\)"),
        ("Generated On", r"11\s*[\.\)]\s*Transit\s+Pass\s+Generated\s+On"),
        ("Valid Upto", r"12\s*[\.\)]\s*Transit\s+Pass\s+Valid\s+Upto"),
        ("Origin District", r"13\s*[\.\)]\s*Loading\s+From\s*\(Origin\s+District\)"),
        ("Origin State", r"14\s*[\.\)]\s*Loading\s+From\s*\(Origin\s+State\)"),
        ("Origin Pass No", r"15\s*[\.\)]\s*Origin\s+Transit\s+Pass\s+No"),
        ("Origin Pass Date", r"16\s*[\.\)]\s*Origin\s+Transit\s+Pass\s+Generation\s+Date"),
        ("Delivery Address", r"17\s*[\.\)]\s*Destination\s*\(Delivery\s+Address\)"),
        ("Vehicle Number", r"1\s*[\.\)]\s*Vehicle\s+Number"),
        ("Vehicle Type", r"2\s*[\.\)]\s*Type\s+Of\s+Vehicle"),
        ("Driver Name", r"3\s*[\.\)]\s*Name\s+Of\s+Driver"),
    ]

    # Find label positions. Sort by position in extracted PDF text.
    found = []
    for name, pattern in labels:
        match = re.search(pattern, text, re.I)
        if match:
            found.append((match.start(), match.end(), name))

    found.sort(key=lambda item: item[0])
    record = {"Searched ID": eid}

    for i, (start, end, name) in enumerate(found):
        next_start = found[i + 1][0] if i + 1 < len(found) else len(text)
        value = text[end:next_start].strip(" \t:.-|")
        record[name] = value

    # Use the searched ID if the PDF did not expose ISTP No.
    record.setdefault("ISTP No", eid)

    # Ensure the record contains a usable destination.
    if not record.get("Destination"):
        # A missing destination means we cannot safely match this record.
        record["Destination"] = ""

    return record


@app.route("/", methods=["GET", "POST"])
def home():
    rows = []
    errors = []
    message = ""
    stats = None

    start = ""
    end = ""
    destinations_input = "ALL"

    if request.method == "POST":
        start = request.form.get("start_id", "").strip()
        end = request.form.get("end_id", "").strip()
        destinations_input = request.form.get(
            "destinations", "ALL"
        ).strip()

        if not start.isdigit() or not end.isdigit():
            message = "Start aur End ID mein sirf numbers dalo."

        elif len(start) != len(end) or len(start) <= 5:
            message = "Start aur End ID ki length same honi chahiye."

        elif int(end) < int(start):
            message = "End ID, Start ID se chhoti nahi ho sakti."

        elif int(end) - int(start) + 1 > MAX_IDS:
            message = (
                f"Ek search mein maximum {MAX_IDS} IDs check kar sakte ho. "
                "Chhoti range se shuru karo."
            )

        else:
            destinations = [
                item.strip().upper()
                for item in destinations_input.split(",")
                if item.strip()
            ]

            if not destinations:
                message = "Kam se kam ek destination dalo."

            else:
                checked = failed = 0

                for number in range(int(start), int(end) + 1):
                    eid = str(number).zfill(len(start))
                    record, error = fetch_record(eid)
                    checked += 1

                    if error:
                        failed += 1
                        if len(errors) < 10:
                            errors.append(f"{eid}: {error}")
                    else:
                        actual_destination = record.get(
                            "Destination", ""
                        ).upper()

                        is_match = (
                            "ALL" in destinations
                            or any(
                                wanted in actual_destination
                                for wanted in destinations
                            )
                        )

                        if is_match and actual_destination:
                            rows.append(record)

                    # Request rate ko limited rakho.
                    time.sleep(0.5)

                stats = {
                    "checked": checked,
                    "matched": len(rows),
                    "failed": failed,
                }

                message = (
                    "Search complete. Matching records HTML mein dikh rahe hain."
                )

    headings = [
        "Searched ID",
        "ISTP No",
        "Transporter",
        "Transporter ID",
        "Mineral",
        "Quantity",
        "Destination",
        "Distance",
        "Generated On",
        "Valid Upto",
        "Origin District",
        "Origin State",
        "Origin Pass No",
        "Origin Pass Date",
        "Delivery Address",
        "Vehicle Number",
        "Vehicle Type",
        "Driver Name",
    ]

    return render_template_string(
        PAGE,
        rows=rows,
        headings=headings,
        message=message,
        errors=errors,
        stats=stats,
        start=start,
        end=end,
        destinations=destinations_input,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
    
from flask import Flask, request, render_template_string
import requests
import io
import re
import time
from pypdf import PdfReader

app = Flask(__name__)

BASE_URL = (
    "http://upmines.upsdc.gov.in/"
    "Transporter/PrintTransporterFormVehicleCheckValidOrNot.aspx"
)

# Har search mein adhiktam 50 IDs
MAX_IDS = 50

FIELDS = {
    "ISTP No": [
        r"ISTP\s*No\.?",
    ],
    "Transporter": [
        r"Name\s+Of\s+Transporter",
    ],
    "Transporter ID": [
        r"Transporter\s+Id",
    ],
    "Mineral": [
        r"Name\s+Of\s+Mineral",
    ],
    "Quantity": [
        r"QTY\s+Transported\s+in\s+Cubic\s+Meter",
    ],
    "Destination": [
        r"Destination\s+District",
    ],
    "Distance": [
        r"Distance\s*\(Approx\s+in\s+K\.?M\.?\)",
    ],
    "Generated On": [
        r"Transit\s+Pass\s+Generated\s+On",
    ],
    "Valid Upto": [
        r"Transit\s+Pass\s+Valid\s+Upto",
    ],
    "Origin District": [
        r"Loading\s+From\s*\(Origin\s+District\)",
    ],
    "Origin State": [
        r"Loading\s+From\s*\(Origin\s+State\)",
    ],
    "Origin Pass No": [
        r"Origin\s+Transit\s+Pass\s+No",
    ],
    "Origin Pass Date": [
        r"Origin\s+Transit\s+Pass\s+Generation\s+Date",
    ],
    "Delivery Address": [
        r"Destination\s*\(Delivery\s+Address\)",
    ],
    "Vehicle Number": [
        r"Vehicle\s+Number",
    ],
    "Vehicle Type": [
        r"Type\s+Of\s+Vehicle",
    ],
    "Driver Name": [
        r"Name\s+Of\s+Driver",
    ],
}

PAGE = r"""
<!doctype html>
<html lang="hi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>UP Mines ISTP Checker</title>
<style>
body {
    font-family: Arial, sans-serif;
    background: #eef2f7;
    margin: 0;
    padding: 12px;
    color: #172033;
}
main {
    max-width: 1100px;
    margin: auto;
    background: white;
    padding: 16px;
    border-radius: 14px;
}
h2 { text-align: center; color: #174ea6; }
label { display: block; margin-top: 13px; font-weight: bold; }
input, button {
    width: 100%;
    padding: 12px;
    margin-top: 6px;
    box-sizing: border-box;
    border-radius: 8px;
}
input { border: 1px solid #cbd5e1; }
button {
    background: #174ea6;
    color: white;
    border: 0;
    font-weight: bold;
    margin-top: 18px;
}
.msg {
    padding: 12px;
    background: #eef5ff;
    border-radius: 8px;
    overflow-wrap: anywhere;
}
.table-wrap { overflow-x: auto; }
table {
    border-collapse: collapse;
    width: 100%;
    font-size: 12px;
    margin-top: 12px;
}
th, td {
    border: 1px solid #d5dbe5;
    padding: 8px;
    text-align: left;
    overflow-wrap: anywhere;
}
th { background: #174ea6; color: white; }
small { color: #526174; }
</style>
</head>
<body>
<main>
<h2>UP MINES ISTP CHECKER</h2>

<form method="post">
<label>Start ID</label>
<input name="start_id" inputmode="numeric"
       value="{{ start }}" required>

<label>End ID</label>
<input name="end_id" inputmode="numeric"
       value="{{ end }}" required>

<label>Destinations (comma-separated)</label>
<input name="destinations"
       value="{{ destinations }}"
       placeholder="PURNIA BIHAR, DEORIA, SONBHADRA"
       required>

<button type="submit">Search ISTP</button>
</form>

{% if message %}
<p class="msg">{{ message }}</p>
{% endif %}

{% if stats %}
<p class="msg">
Checked: {{ stats.checked }} |
Matched: {{ stats.matched }} |
Failed/unreadable: {{ stats.failed }}
</p>
{% endif %}

{% if errors %}
<h3>Errors (pehli 10)</h3>
<ul>
{% for error in errors %}
<li>{{ error }}</li>
{% endfor %}
</ul>
{% endif %}

{% if rows %}
<h3>Matching HTML Results: {{ rows|length }}</h3>
<div class="table-wrap">
<table>
<thead>
<tr>
{% for heading in headings %}
<th>{{ heading }}</th>
{% endfor %}
</tr>
</thead>
<tbody>
{% for row in rows %}
<tr>
{% for heading in headings %}
<td>{{ row.get(heading, '') }}</td>
{% endfor %}
</tr>
{% endfor %}
</tbody>
</table>
</div>
{% endif %}

<p><small>
Sirf destination-match wale records dikhaye jaate hain.
Timeout ya unreadable record ko failed mein gina jayega.
</small></p>
</main>
</body>
</html>
"""

def fetch_record(eid):
    if not eid.isdigit() or len(eid) <= 5:
        return None, "Invalid eID"

    try:
        response = requests.get(
            BASE_URL,
            params={"eId": eid},
            timeout=(8, 25),
            headers={"User-Agent": "Mozilla/5.0"}
        )

        if response.status_code != 200:
            return None, "HTTP " + str(response.status_code)

        content = response.content

        if not content.lstrip().startswith(b"%PDF-"):
            return None, (
                "PDF/text response nahi mili; Content-Type: "
                + response.headers.get("Content-Type", "unknown")
            )

        reader = PdfReader(io.BytesIO(content))

        if reader.is_encrypted:
            return None, "Encrypted PDF"

        text = "\n".join(
            page.extract_text() or ""
            for page in reader.pages
        )

        if not text.strip():
            return None, "PDF text unreadable"

        return parse_record(text, eid), None

    except requests.exceptions.Timeout:
        return None, "UP Mines server timeout"
    except requests.exceptions.RequestException as exc:
        return None, "Network error: " + type(exc).__name__
    except Exception as exc:
        return None, "Read error: " + type(exc).__name__


def parse_record(text, eid):
    # PDF text mein line breaks/spaces ko normalize karo
    text = re.sub(r"\s+", " ", text).strip()

    # Numbered field labels ko boundaries ki tarah use karo.
    # Har label ke baad ka text agle label tak uski value hai.
    labels = [
        ("ISTP No", r"1\s*[\.\)]\s*ISTP\s*No\.?"),
        ("Transporter", r"2\s*[\.\)]\s*Name\s+Of\s+Transporter"),
        ("Transporter ID", r"3\s*[\.\)]\s*Transporter\s+Id"),
        ("Mineral", r"7\s*[\.\)]\s*Name\s+Of\s+Mineral"),
        ("Quantity", r"6\s*[\.\)]\s*QTY\s+Transported\s+in\s+Cubic\s+Meter"),
        ("Destination", r"8\s*[\.\)]\s*Destination\s+District"),
        ("Distance", r"9\s*[\.\)]\s*Distance\s*\(Approx\s+in\s+K\.?M\.?\)"),
        ("Generated On", r"11\s*[\.\)]\s*Transit\s+Pass\s+Generated\s+On"),
        ("Valid Upto", r"12\s*[\.\)]\s*Transit\s+Pass\s+Valid\s+Upto"),
        ("Origin District", r"13\s*[\.\)]\s*Loading\s+From\s*\(Origin\s+District\)"),
        ("Origin State", r"14\s*[\.\)]\s*Loading\s+From\s*\(Origin\s+State\)"),
        ("Origin Pass No", r"15\s*[\.\)]\s*Origin\s+Transit\s+Pass\s+No"),
        ("Origin Pass Date", r"16\s*[\.\)]\s*Origin\s+Transit\s+Pass\s+Generation\s+Date"),
        ("Delivery Address", r"17\s*[\.\)]\s*Destination\s*\(Delivery\s+Address\)"),
        ("Vehicle Number", r"1\s*[\.\)]\s*Vehicle\s+Number"),
        ("Vehicle Type", r"2\s*[\.\)]\s*Type\s+Of\s+Vehicle"),
        ("Driver Name", r"3\s*[\.\)]\s*Name\s+Of\s+Driver"),
    ]

    # Find label positions. Sort by position in extracted PDF text.
    found = []
    for name, pattern in labels:
        match = re.search(pattern, text, re.I)
        if match:
            found.append((match.start(), match.end(), name))

    found.sort(key=lambda item: item[0])
    record = {"Searched ID": eid}

    for i, (start, end, name) in enumerate(found):
        next_start = found[i + 1][0] if i + 1 < len(found) else len(text)
        value = text[end:next_start].strip(" \t:.-|")
        record[name] = value

    # Use the searched ID if the PDF did not expose ISTP No.
    record.setdefault("ISTP No", eid)

    # Ensure the record contains a usable destination.
    if not record.get("Destination"):
        # A missing destination means we cannot safely match this record.
        record["Destination"] = ""

    return record


@app.route("/", methods=["GET", "POST"])
def home():
    rows = []
    errors = []
    message = ""
    stats = None

    start = ""
    end = ""
    destinations_input = "ALL"

    if request.method == "POST":
        start = request.form.get("start_id", "").strip()
        end = request.form.get("end_id", "").strip()
        destinations_input = request.form.get(
            "destinations", "ALL"
        ).strip()

        if not start.isdigit() or not end.isdigit():
            message = "Start aur End ID mein sirf numbers dalo."

        elif len(start) != len(end) or len(start) <= 5:
            message = "Start aur End ID ki length same honi chahiye."

        elif int(end) < int(start):
            message = "End ID, Start ID se chhoti nahi ho sakti."

        elif int(end) - int(start) + 1 > MAX_IDS:
            message = (
                f"Ek search mein maximum {MAX_IDS} IDs check kar sakte ho. "
                "Chhoti range se shuru karo."
            )

        else:
            destinations = [
                item.strip().upper()
                for item in destinations_input.split(",")
                if item.strip()
            ]

            if not destinations:
                message = "Kam se kam ek destination dalo."

            else:
                checked = failed = 0

                for number in range(int(start), int(end) + 1):
                    eid = str(number).zfill(len(start))
                    record, error = fetch_record(eid)
                    checked += 1

                    if error:
                        failed += 1
                        if len(errors) < 10:
                            errors.append(f"{eid}: {error}")
                    else:
                        actual_destination = record.get(
                            "Destination", ""
                        ).upper()

                        is_match = (
                            "ALL" in destinations
                            or any(
                                wanted in actual_destination
                                for wanted in destinations
                            )
                        )

                        if is_match and actual_destination:
                            rows.append(record)

                    # Request rate ko limited rakho.
                    time.sleep(0.5)

                stats = {
                    "checked": checked,
                    "matched": len(rows),
                    "failed": failed,
                }

                message = (
                    "Search complete. Matching records HTML mein dikh rahe hain."
                )

    headings = [
        "Searched ID",
        "ISTP No",
        "Transporter",
        "Transporter ID",
        "Mineral",
        "Quantity",
        "Destination",
        "Distance",
        "Generated On",
        "Valid Upto",
        "Origin District",
        "Origin State",
        "Origin Pass No",
        "Origin Pass Date",
        "Delivery Address",
        "Vehicle Number",
        "Vehicle Type",
        "Driver Name",
    ]

    return render_template_string(
        PAGE,
        rows=rows,
        headings=headings,
        message=message,
        errors=errors,
        stats=stats,
        start=start,
        end=end,
        destinations=destinations_input,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
    
