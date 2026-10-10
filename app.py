
from flask import Flask, request, render_template_string

app = Flask(__name__)

PAGE = """
<!doctype html>
<html lang="hi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>UP Mines Web Bot</title>
<style>
body { font-family: Arial; background: #eef2f7; padding: 16px; }
main { max-width: 480px; margin: auto; background: white;
padding: 20px; border-radius: 14px; }
h2 { color: #174ea6; text-align: center; }
label { display: block; margin-top: 14px; }
input, select, button {
width: 100%; padding: 12px; margin-top: 7px;
box-sizing: border-box; border-radius: 8px;
}
button { background: #174ea6; color: white; border: 0; }
</style>
</head>
<body>
<main>
<h2>UP MINES WEB BOT</h2>
<form method="get">
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
<input name="destination" placeholder="DEORIA ya ALL">
<button type="submit">Search Data</button>
</form>
{% if submitted %}
<p>Form submit ho gaya. Live UP Mines search abhi connect nahi hai.</p>
{% endif %}
</main>
</body>
</html>
"""

@app.route("/", methods=["GET"])
def home():
    submitted = "start_id" in request.args
    return render_template_string(PAGE, submitted=submitted)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
