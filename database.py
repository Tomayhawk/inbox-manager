import sqlite3
import mailbox
import os
import datetime
import re
from email.header import decode_header
from email.utils import parsedate_to_datetime

DB_NAME = "local_emails.db"

class EmailBackend:
    def __init__(self):
        self.conn = sqlite3.connect(DB_NAME, check_same_thread=False)
        self.create_tables()

    def create_tables(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS emails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid TEXT UNIQUE,
                
                sender TEXT, sender_name TEXT, sender_addr TEXT, sender_domain TEXT,
                recipient TEXT, cc TEXT, bcc TEXT, reply_to TEXT,
                
                subject TEXT,
                date_str TEXT, timestamp REAL, day_of_week TEXT,
                
                size_bytes INTEGER, link_count INTEGER,
                
                has_attachment INTEGER, attachment_count INTEGER, 
                attachment_types TEXT, attachment_names TEXT,
                
                folder TEXT, category TEXT,
                is_starred INTEGER, is_read INTEGER, is_newsletter INTEGER,
                gmail_labels TEXT,
                
                headers_json TEXT, -- Store raw interesting headers
                body TEXT, html_body TEXT, tags TEXT DEFAULT ''
            )
        ''')
        cursor.execute('''
            CREATE VIRTUAL TABLE IF NOT EXISTS emails_fts USING fts5(
                sender, recipient, subject, body, gmail_labels, tags, content=emails, content_rowid=id
            )
        ''')
        self.conn.commit()

    def _parse_date(self, date_str):
        try:
            if not date_str: return 0, "Unknown"
            dt = parsedate_to_datetime(date_str)
            return dt.timestamp(), dt.strftime("%A") 
        except:
            return 0, "Unknown"

    def _extract_domain(self, email_addr):
        match = re.search(r"@([\w.-]+)", str(email_addr))
        return match.group(1).lower() if match else ""

    def _parse_gmail_labels(self, labels_str):
        # Default State
        folder = 'all'
        category = 'primary'
        is_starred = 0
        is_read = 1 
        
        if not labels_str: 
            return folder, category, is_starred, is_read
            
        labels = [l.strip() for l in labels_str.split(',')]
        
        # 1. Folders
        if 'Inbox' in labels: folder = 'inbox'
        elif 'Sent' in labels: folder = 'sent'
        elif 'Trash' in labels: folder = 'bin'
        elif 'Spam' in labels: folder = 'spam'
        elif 'Drafts' in labels: folder = 'drafts'
        elif 'Important' in labels: folder = 'important'
        elif 'Starred' in labels: folder = 'starred'
        
        # 2. Categories
        # Gmail categories are mutually exclusive in UI, but labels might overlap.
        # Priority: Promo > Social > Updates > Forums > Purchases > Primary
        if 'Category Promotions' in labels: category = 'promotions'
        elif 'Category Social' in labels: category = 'social'
        elif 'Category Updates' in labels: category = 'updates'
        elif 'Category Forums' in labels: category = 'forums'
        elif 'Category Purchases' in labels: category = 'purchases'
        else: category = 'primary' 
        
        # 3. Flags
        if 'Starred' in labels: is_starred = 1
        if 'Unread' in labels: is_read = 0
        
        return folder, category, is_starred, is_read

    def complex_search(self, f):
        cursor = self.conn.cursor()
        query = ["SELECT * FROM emails WHERE 1=1"]
        params = []

        # --- 1. VIEW CONTEXT ---
        if f.get('folder') and f['folder'] != 'all':
            if f['folder'] == 'starred': query.append("AND is_starred = 1")
            else: 
                query.append("AND folder = ?")
                params.append(f['folder'])
                
        if f.get('category') and f.get('folder') == 'inbox':
            query.append("AND category = ?")
            params.append(f['category'])

        # --- 2. TEXT & FTS ---
        if f.get('q'):
            query.append("AND id IN (SELECT rowid FROM emails_fts WHERE emails_fts MATCH ?)")
            params.append(f.get('q'))
        if f.get('includes'):
            query.append("AND id IN (SELECT rowid FROM emails_fts WHERE emails_fts MATCH ?)")
            params.append(f'"{f["includes"]}"')
        if f.get('excludes'):
            query.append("AND id IN (SELECT rowid FROM emails_fts WHERE emails_fts MATCH ?)")
            params.append(f'NOT "{f["excludes"]}"')

        # --- 3. PEOPLE ---
        if f.get('sender'):
            query.append("AND sender LIKE ?")
            params.append(f"%{f['sender']}%")
        if f.get('recipient'):
            query.append("AND (recipient LIKE ? OR cc LIKE ? OR bcc LIKE ?)")
            p = f"%{f['recipient']}%"
            params.extend([p, p, p])
        if f.get('domain'):
            query.append("AND sender_domain LIKE ?")
            params.append(f"%{f['domain']}%")

        # --- 4. ATTRIBUTES ---
        if f.get('subject'):
            query.append("AND subject LIKE ?")
            params.append(f"%{f['subject']}%")
        
        if f.get('has_attachment') == 'yes': query.append("AND has_attachment = 1")
        elif f.get('has_attachment') == 'no': query.append("AND has_attachment = 0")
            
        if f.get('is_read') == 'yes': query.append("AND is_read = 1")
        elif f.get('is_read') == 'unread': query.append("AND is_read = 0")

        if f.get('is_newsletter') == 'yes': query.append("AND is_newsletter = 1")

        # --- 5. RANGES ---
        if f.get('date_start'):
            ts = datetime.datetime.strptime(f['date_start'], "%Y-%m-%d").timestamp()
            query.append("AND timestamp >= ?")
            params.append(ts)
        if f.get('date_end'):
            ts = datetime.datetime.strptime(f['date_end'], "%Y-%m-%d").timestamp()
            query.append("AND timestamp <= ?")
            params.append(ts)
            
        if f.get('size_min'): # in MB
            query.append("AND size_bytes >= ?")
            params.append(float(f['size_min']) * 1024 * 1024)
        if f.get('size_max'):
            query.append("AND size_bytes <= ?")
            params.append(float(f['size_max']) * 1024 * 1024)

        # --- 6. ADVANCED ---
        if f.get('att_type'):
            query.append("AND attachment_types LIKE ?")
            params.append(f"%{f['att_type']}%")
        if f.get('att_name'):
            query.append("AND attachment_names LIKE ?")
            params.append(f"%{f['att_name']}%")

        # Sorting
        sort_map = {
            "date_desc": "timestamp DESC",
            "date_asc": "timestamp ASC",
            "size_desc": "size_bytes DESC",
            "sender_asc": "sender ASC",
            "att_desc": "attachment_count DESC"
        }
        order = sort_map.get(f.get('sort'), "timestamp DESC")
        query.append(f"ORDER BY {order} LIMIT 1000")

        cursor.execute(" ".join(query), tuple(params))
        cols = [col[0] for col in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]

    def get_email(self, email_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM emails WHERE id = ?", (email_id,))
        row = cursor.fetchone()
        if row:
            cols = [col[0] for col in cursor.description]
            return dict(zip(cols, row))
        return None
        
    def add_tag(self, email_id, new_tag):
        cursor = self.conn.cursor()
        cursor.execute("SELECT tags FROM emails WHERE id = ?", (email_id,))
        res = cursor.fetchone()
        if res:
            curr = res[0] if res[0] else ""
            if new_tag not in curr:
                new_val = (curr + " " + new_tag).strip()
                cursor.execute("UPDATE emails SET tags = ? WHERE id = ?", (new_val, email_id))
                self.conn.commit()

    def import_mbox(self, mbox_path, progress_callback=None):
        if not os.path.isfile(mbox_path): return False, "File not found."

        try:
            mbox = mailbox.mbox(mbox_path)
            total = len(mbox)
            count = 0
            self.conn.execute("BEGIN TRANSACTION")

            for message in mbox:
                count += 1
                try:
                    def clean(h):
                        if not h: return ""
                        val = ""
                        try:
                            for part, enc in decode_header(h):
                                if isinstance(part, bytes): val += part.decode(enc or "utf-8", errors="ignore")
                                else: val += part
                        except: val = str(h)
                        return val.replace('"', '').strip()

                    uid = message.get("Message-ID", f"local-{count}")
                    subject = clean(message["subject"]) or "(No Subject)"
                    sender = clean(message["from"])
                    recipient = clean(message["to"])
                    cc = clean(message.get("cc", ""))
                    bcc = clean(message.get("bcc", ""))
                    reply_to = clean(message.get("reply-to", ""))
                    
                    # Name/Addr Split
                    sender_name, sender_addr = sender, sender
                    if "<" in sender:
                        parts = sender.split("<")
                        sender_name = parts[0].strip()
                        sender_addr = parts[1].replace(">", "").strip()
                    
                    date_str = message["date"]
                    timestamp, day_name = self._parse_date(date_str)
                    sender_domain = self._extract_domain(sender_addr)
                    is_newsletter = 1 if message.get('List-Unsubscribe') else 0
                    
                    gmail_labels_raw = message.get('X-Gmail-Labels', '')
                    folder, category, is_starred, is_read = self._parse_gmail_labels(gmail_labels_raw)
                    
                    # Body & Attachments
                    body_text = ""
                    body_html = ""
                    attachments = []
                    
                    if message.is_multipart():
                        for part in message.walk():
                            if part.get_content_maintype() == 'multipart': continue
                            c_disp = part.get('Content-Disposition')
                            if c_disp is None:
                                try:
                                    payload = part.get_payload(decode=True)
                                    if payload:
                                        decoded = payload.decode(errors="ignore")
                                        if part.get_content_type() == "text/html": body_html += decoded
                                        else: body_text += decoded
                                except: pass
                            else:
                                fname = part.get_filename()
                                if fname: attachments.append(fname)
                    else:
                        try:
                            payload = message.get_payload(decode=True)
                            if payload:
                                decoded = payload.decode(errors="ignore")
                                if message.get_content_type() == "text/html": body_html = decoded
                                else: body_text = decoded
                        except: pass
                    
                    link_count = body_html.count('<a href') + body_text.count('http://')
                    size_bytes = len(message.as_bytes())
                    has_att = 1 if attachments else 0
                    att_count = len(attachments)
                    att_types = ",".join(list(set([os.path.splitext(x)[1].lower() for x in attachments])))
                    att_names = "; ".join(attachments)

                    # Capture raw headers for "Detail View"
                    # Only grabbing specific useful ones to save space, or all? 
                    # Let's grab specific interesting ones
                    raw_headers = {
                        "Message-ID": uid,
                        "Delivered-To": message.get("Delivered-To", ""),
                        "Return-Path": message.get("Return-Path", ""),
                        "MIME-Version": message.get("MIME-Version", ""),
                        "Content-Type": message.get("Content-Type", ""),
                        "X-Mailer": message.get("X-Mailer", ""),
                        "X-Gmail-Labels": gmail_labels_raw
                    }
                    import json
                    headers_json = json.dumps(raw_headers)

                    self.conn.execute('''
                        INSERT OR IGNORE INTO emails 
                        (uid, sender, sender_name, sender_addr, sender_domain, recipient, cc, bcc, reply_to,
                         subject, date_str, timestamp, day_of_week,
                         size_bytes, link_count, has_attachment, attachment_count, attachment_types, attachment_names,
                         folder, category, is_starred, is_read, is_newsletter, gmail_labels, headers_json,
                         body, html_body)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ''', (uid, sender, sender_name, sender_addr, sender_domain, recipient, cc, bcc, reply_to,
                          subject, date_str, timestamp, day_name,
                          size_bytes, link_count, has_att, att_count, att_types, att_names,
                          folder, category, is_starred, is_read, is_newsletter, gmail_labels_raw, headers_json,
                          body_text, body_html))

                except Exception as e:
                    continue

                if progress_callback and count % 100 == 0: progress_callback(count, total)

            self.conn.execute("INSERT INTO emails_fts(emails_fts) VALUES('rebuild')")
            self.conn.execute("COMMIT")
            return True, f"Imported {count} emails."

        except Exception as e:
            self.conn.execute("ROLLBACK")
            return False, str(e)
