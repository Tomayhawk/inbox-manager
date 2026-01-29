import sqlite3
import mailbox
import os
import datetime
import re
import json
from email.header import decode_header
from email.utils import parsedate_to_datetime

DB_NAME = "local_emails.db"

class EmailBackend:
    def __init__(self):
        self.conn = sqlite3.connect(DB_NAME, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        c = self.conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS emails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid TEXT UNIQUE,
                sender TEXT, sender_name TEXT, sender_addr TEXT, sender_domain TEXT,
                recipient TEXT, subject TEXT,
                date_str TEXT, timestamp REAL, day_of_week TEXT,
                size_bytes INTEGER, link_count INTEGER,
                has_attachment INTEGER, attachment_count INTEGER, attachment_types TEXT, attachment_names TEXT,
                folder TEXT, category TEXT,
                is_starred INTEGER DEFAULT 0, is_read INTEGER DEFAULT 1, is_newsletter INTEGER DEFAULT 0, is_deleted INTEGER DEFAULT 0,
                headers_json TEXT, body TEXT, html_body TEXT, tags TEXT DEFAULT ''
            )
        ''')
        c.execute('CREATE TABLE IF NOT EXISTS folders (name TEXT PRIMARY KEY, type TEXT, icon TEXT)')
        if c.execute("SELECT count(*) FROM folders").fetchone()[0] == 0:
            sys = [('Inbox','system','📥'), ('Starred','system','⭐'), ('Sent','system','✈️'), 
                   ('Drafts','system','📝'), ('Archive','system','🗃️'), ('Spam','system','⚠️'), 
                   ('Bin','system','🗑️'), ('Snoozed','system','💤')]
            c.executemany("INSERT OR IGNORE INTO folders VALUES (?,?,?)", sys)
        
        c.execute('CREATE VIRTUAL TABLE IF NOT EXISTS emails_fts USING fts5(sender, subject, body, tags, content=emails, content_rowid=id)')
        c.execute('CREATE TABLE IF NOT EXISTS search_history (query TEXT PRIMARY KEY, timestamp REAL)')
        self.conn.commit()

    def complex_search(self, f):
        """Master Filter Engine"""
        q = ["SELECT * FROM emails WHERE is_deleted = 0"]
        p = []

        # 1. Scope
        if f.get('folder'):
            if f['folder'] == 'Starred': q.append("AND is_starred = 1")
            elif f['folder'] != 'All Mail': q.append("AND folder = ?"); p.append(f['folder'])
        if f.get('category') and f.get('folder') == 'Inbox': q.append("AND category = ?"); p.append(f['category'])

        # 2. Text (FTS)
        if f.get('q'):
            self.conn.execute("INSERT OR REPLACE INTO search_history VALUES (?, ?)", (f['q'], datetime.datetime.now().timestamp()))
            q.append("AND id IN (SELECT rowid FROM emails_fts WHERE emails_fts MATCH ?)"); p.append(f['q'])
        
        # 3. Content Filters (New Features)
        if f.get('inc_words'): q.append("AND (subject LIKE ? OR body LIKE ?)"); p.extend([f"%{f['inc_words']}%"]*2)
        if f.get('exc_words'): q.append("AND NOT (subject LIKE ? OR body LIKE ?)"); p.extend([f"%{f['exc_words']}%"]*2)
        if f.get('has_link'): q.append("AND link_count > 0")
        if f.get('subj_len') == 'short': q.append("AND length(subject) < 20")
        elif f.get('subj_len') == 'long': q.append("AND length(subject) > 60")

        # 4. People
        if f.get('sender'): q.append("AND sender LIKE ?"); p.append(f"%{f['sender']}%")
        if f.get('domain'): q.append("AND sender_domain LIKE ?"); p.append(f"%{f['domain']}%")
        if f.get('exc_domain'): q.append("AND sender_domain NOT LIKE ?"); p.append(f"%{f['exc_domain']}%")

        # 5. Attributes
        if f.get('read') == 'yes': q.append("AND is_read = 1")
        elif f.get('read') == 'no': q.append("AND is_read = 0")
        if f.get('att') == 'yes': q.append("AND has_attachment = 1")
        elif f.get('att') == 'no': q.append("AND has_attachment = 0")
        if f.get('att_type'): q.append("AND attachment_types LIKE ?"); p.append(f"%{f['att_type']}%")
        if f.get('day'): q.append("AND day_of_week = ?"); p.append(f['day'])

        # 6. Ranges
        if f.get('date_after'): q.append("AND timestamp >= ?"); p.append(f['date_after'])
        if f.get('date_before'): q.append("AND timestamp <= ?"); p.append(f['date_before'])
        if f.get('min_size'): q.append("AND size_bytes >= ?"); p.append(f['min_size'])

        # Sorting
        sort = f.get('sort', 'newest')
        order = "timestamp DESC"
        if sort == 'oldest': order = "timestamp ASC"
        elif sort == 'size': order = "size_bytes DESC"
        elif sort == 'alpha': order = "subject ASC"
        elif sort == 'links': order = "link_count DESC"
        
        q.append(f"ORDER BY {order} LIMIT 2000")
        return [dict(r) for r in self.conn.execute(" ".join(q), tuple(p)).fetchall()]

    # --- ACTIONS ---
    def toggle_flag(self, eid, col):
        curr = self.conn.execute(f"SELECT {col} FROM emails WHERE id=?", (eid,)).fetchone()[0]
        self.conn.execute(f"UPDATE emails SET {col}=? WHERE id=?", (0 if curr else 1, eid))
        self.conn.commit()

    def bulk_op(self, ids, op, val=None):
        if not ids: return
        p = ",".join(["?"]*len(ids))
        if op == 'move': self.conn.execute(f"UPDATE emails SET folder=? WHERE id IN ({p})", (val, *ids))
        elif op == 'delete': self.conn.execute(f"UPDATE emails SET is_deleted=1, folder='Bin' WHERE id IN ({p})", ids)
        elif op == 'read': self.conn.execute(f"UPDATE emails SET is_read=? WHERE id IN ({p})", (val, *ids))
        self.conn.commit()

    def get_stats(self):
        ur = dict(self.conn.execute("SELECT folder, COUNT(*) FROM emails WHERE is_read=0 AND is_deleted=0 GROUP BY folder").fetchall())
        return {'unread': ur}

    # --- IMPORT ---
    def import_mbox(self, path, cb=None):
        if not os.path.exists(path): return
        mbox = mailbox.mbox(path)
        self.conn.execute("BEGIN")
        for i, msg in enumerate(mbox):
            try:
                def clean(h): 
                    return "".join([str(t[0], t[1] or 'utf-8', 'ignore') if isinstance(t[0], bytes) else str(t[0]) for t in decode_header(h or "")])
                
                sub, frm = clean(msg['subject']), clean(msg['from'])
                name, addr = (frm.split("<", 1) + [frm])[:2]
                addr = addr.strip(">")
                dom = re.search(r"@([\w.-]+)", addr)
                dom = dom.group(1).lower() if dom else ""
                
                ts = parsedate_to_datetime(msg['date']).timestamp() if msg['date'] else 0
                day = datetime.datetime.fromtimestamp(ts).strftime("%A") if ts else ""
                
                body, html = "", ""
                atts = []
                if msg.is_multipart():
                    for p in msg.walk():
                        if p.get_content_maintype() == 'multipart': continue
                        if p.get('Content-Disposition'): atts.append(p.get_filename() or "file")
                        else:
                            try: 
                                pl = p.get_payload(decode=True).decode(errors='ignore')
                                if p.get_content_type() == 'text/html': html += pl
                                else: body += pl
                            except: pass
                else:
                    try: 
                        pl = msg.get_payload(decode=True).decode(errors='ignore')
                        if msg.get_content_type() == 'text/html': html = pl
                        else: body = pl
                    except: pass

                # Auto-Categorize
                cat = 'primary'
                lbls = msg.get('X-Gmail-Labels', '')
                if 'Promotions' in lbls: cat = 'promotions'
                elif 'Social' in lbls: cat = 'social'
                elif 'Updates' in lbls: cat = 'updates'

                links = html.count('<a href') + body.count('http')
                
                self.conn.execute('''INSERT OR IGNORE INTO emails 
                    (uid, sender, sender_name, sender_addr, sender_domain, subject, date_str, timestamp, day_of_week,
                     body, html_body, folder, category, has_attachment, attachment_names, attachment_types, 
                     size_bytes, link_count, is_newsletter, headers_json)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (msg.get('Message-ID', f"loc-{i}"), frm, name.strip(), addr, dom, sub, msg['date'], ts, day,
                     body, html, 'Inbox', cat, 1 if atts else 0, ";".join(atts), 
                     ",".join({os.path.splitext(x)[1] for x in atts}), len(msg.as_bytes()), links,
                     1 if msg.get('List-Unsubscribe') else 0, json.dumps(dict(msg.items()))))
                
                if cb and i % 50 == 0: cb(i)
            except: continue
        self.conn.execute("COMMIT")
        return i
