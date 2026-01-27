from flask import Flask, render_template, request, jsonify, send_file
from database import EmailBackend
import io
import csv
import zipfile
import json

app = Flask(__name__)
db = EmailBackend()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/search', methods=['POST'])
def search():
    filters = request.json
    results = db.complex_search(filters)
    
    data = []
    for r in results:
        data.append({
            'id': r['id'],
            'sender_name': r['sender_name'],
            'subject': r['subject'],
            'date': r['date_str'][:16],
            'snippet': (r['body'][:60] + "...") if r['body'] else "...",
            'is_read': r['is_read'],
            'is_starred': r['is_starred'],
            'has_att': r['has_attachment'],
            'tags': r['tags'],
            'category': r['category']
        })
    return jsonify(data)

@app.route('/api/email/<int:eid>')
def get_email(eid):
    email = db.get_email(eid)
    if email:
        content = email['html_body'] if email['html_body'] else f"<pre style='white-space:pre-wrap;'>{email['body']}</pre>"
        return jsonify({
            'sender': email['sender'],
            'sender_addr': email['sender_addr'],
            'recipient': email['recipient'],
            'cc': email['cc'],
            'bcc': email['bcc'],
            'reply_to': email['reply_to'],
            'subject': email['subject'],
            'date': email['date_str'],
            'content': content,
            'labels': email['gmail_labels'],
            'tags': email['tags'],
            'size': f"{email['size_bytes']/1024:.0f} KB",
            'headers': json.loads(email['headers_json'] or "{}")
        })
    return jsonify({'error': 'Not found'})

@app.route('/api/tag', methods=['POST'])
def add_tag():
    db.add_tag(request.json['id'], request.json['tag'])
    return jsonify({'status': 'ok'})

@app.route('/import', methods=['POST'])
def run_import():
    path = request.form.get('path')
    def prog(c, t): print(f"\rImporting: {c}/{t}", end="")
    success, msg = db.import_mbox(path, prog)
    return jsonify({'success': success, 'message': msg})

# --- ADVANCED EXPORT ENGINE ---

@app.route('/api/export/csv', methods=['POST'])
def export_csv():
    filters = request.json.get('filters', {})
    rows = db.complex_search(filters)
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['ID', 'From', 'To', 'Subject', 'Date', 'Size', 'Folder', 'Category', 'Tags'])
    for r in rows:
        cw.writerow([r['id'], r['sender_addr'], r['recipient'], r['subject'], r['date_str'], r['size_bytes'], r['folder'], r['category'], r['tags']])
    output = io.BytesIO(si.getvalue().encode('utf-8'))
    return send_file(output, mimetype="text/csv", as_attachment=True, download_name="email_report.csv")

@app.route('/api/export/json', methods=['POST'])
def export_json():
    """Full raw data dump of filtered results"""
    filters = request.json.get('filters', {})
    rows = db.complex_search(filters)
    # Convert rows (dicts) to JSON string
    json_str = json.dumps(rows, default=str, indent=2)
    output = io.BytesIO(json_str.encode('utf-8'))
    return send_file(output, mimetype="application/json", as_attachment=True, download_name="email_dump.json")

@app.route('/api/export/eml', methods=['POST'])
def export_eml():
    """Exports individual .eml files in a ZIP"""
    filters = request.json.get('filters', {})
    rows = db.complex_search(filters)
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        for r in rows:
            # Reconstruct minimal EML
            eml_content = f"From: {r['sender']}\nTo: {r['recipient']}\nSubject: {r['subject']}\nDate: {r['date_str']}\nContent-Type: text/html\n\n{r['html_body'] or r['body']}"
            safe_sub = "".join([c for c in r['subject'] if c.isalnum()]).strip()[:30]
            zip_file.writestr(f"{safe_sub}_{r['id']}.eml", eml_content)
    zip_buffer.seek(0)
    return send_file(zip_buffer, mimetype="application/zip", as_attachment=True, download_name="eml_export.zip")

@app.route('/api/export/organized', methods=['POST'])
def export_organized():
    filters = request.json.get('filters', {})
    group_by = request.json.get('group_by', 'year')
    rows = db.complex_search(filters)
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        for r in rows:
            folder = "Unsorted"
            if group_by == 'year': folder = r['date_str'][-4:] if r['date_str'] else "Unknown"
            elif group_by == 'domain': folder = r['sender_domain'] or "Unknown"
            elif group_by == 'tag': folder = r['tags'].split(' ')[0] if r['tags'] else "Untagged"
            
            safe_sub = "".join([c for c in r['subject'] if c.isalnum()]).strip()[:30]
            fname = f"{folder}/{safe_sub}_{r['id']}.html"
            content = f"<h1>{r['subject']}</h1><p>From: {r['sender']}</p><hr>{r['html_body'] or r['body']}"
            zip_file.writestr(fname, content)
    zip_buffer.seek(0)
    return send_file(zip_buffer, mimetype="application/zip", as_attachment=True, download_name="organized_website.zip")

if __name__ == '__main__':
    import webbrowser
    webbrowser.open("http://127.0.0.1:5000")
    app.run(debug=True, port=5000)
