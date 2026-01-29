import sys
import os
import json
import csv
import zipfile
from datetime import datetime, timedelta

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QListWidget, QListWidgetItem, QLineEdit, QPushButton, QSplitter, 
                             QLabel, QFrame, QMenu, QDialog, QFormLayout, QComboBox, QMessageBox, 
                             QFileDialog, QAbstractItemView, QCheckBox, QSpinBox, QTabWidget,
                             QCompleter, QProgressBar, QGridLayout, QRadioButton, QButtonGroup, QDateEdit)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import Qt, QUrl, QSize, QDate
from PyQt6.QtGui import QAction, QIcon, QCursor, QColor, QFont, QKeySequence, QShortcut
from PyQt6.QtPrintSupport import QPrinter, QPrintDialog

from database import EmailBackend

# --- STYLE ---
CSS = """
    QMainWindow { background: #1e1e1e; color: #ccc; }
    QWidget { background: #1e1e1e; color: #ccc; font-family: 'Segoe UI'; font-size: 13px; }
    QLineEdit, QComboBox, QSpinBox, QDateEdit { background: #2d2d2d; border: 1px solid #3e3e3e; color: white; padding: 5px; border-radius: 4px; }
    QListWidget { background: #252526; border: none; outline: none; }
    QListWidget::item:selected { background: #37373d; border-left: 3px solid #0078d4; color: white; }
    QListWidget::item:hover { background: #2a2d2e; }
    QPushButton { background: #3c3c3c; border: none; padding: 6px 12px; border-radius: 4px; color: #fff; }
    QPushButton:hover { background: #4c4c4c; }
    QPushButton#Primary { background: #0078d4; }
    QFrame#Header, QFrame#Meta { background: #252526; border-bottom: 1px solid #333; }
    QSplitter::handle { background: #333; }
    QTabWidget::pane { border: 1px solid #333; }
    QTabBar::tab { background: #2d2d2d; padding: 8px 12px; color: #ccc; }
    QTabBar::tab:selected { background: #1e1e1e; border-top: 2px solid #0078d4; }
"""

class ExportDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Export Studio")
        self.resize(400, 300)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Format Selection
        layout.addWidget(QLabel("<b>1. File Format</b>"))
        self.fmt_grp = QButtonGroup()
        formats = [("HTML Website (Browsable)", "html"), ("EML Archive (Raw)", "eml"), 
                   ("JSON Dump (Data)", "json"), ("CSV Report (Excel)", "csv"),
                   ("Attachments Only (Files)", "files")]
        for lbl, val in formats:
            rb = QRadioButton(lbl)
            layout.addWidget(rb)
            self.fmt_grp.addButton(rb)
            rb.setProperty("val", val)
        self.fmt_grp.buttons()[0].setChecked(True)

        layout.addSpacing(10)

        # Structure Selection
        layout.addWidget(QLabel("<b>2. Folder Structure (Grouping)</b>"))
        self.struct_combo = QComboBox()
        self.struct_combo.addItems(["Flat (No Folders)", "By Year", "By Year-Month", 
                                    "By Sender Domain", "By Sender Name", 
                                    "By Day of Week", "By Attachment Type"])
        layout.addWidget(self.struct_combo)

        layout.addSpacing(20)
        
        btns = QHBoxLayout()
        b_ex = QPushButton("Export"); b_ex.setObjectName("Primary"); b_ex.clicked.connect(self.accept)
        b_ca = QPushButton("Cancel"); b_ca.clicked.connect(self.reject)
        btns.addStretch(); btns.addWidget(b_ca); btns.addWidget(b_ex)
        layout.addLayout(btns)

    def get_settings(self):
        fmt = [b for b in self.fmt_grp.buttons() if b.isChecked()][0].property("val")
        struct = self.struct_combo.currentText()
        return fmt, struct

class FilterDialog(QDialog):
    def __init__(self, parent, filters):
        super().__init__(parent)
        self.setWindowTitle("Advanced Filters")
        self.f = filters
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        
        # General Tab
        t_gen = QWidget(); f_gen = QFormLayout(t_gen)
        self.q = QLineEdit(self.f.get('q',''))
        self.inc = QLineEdit(self.f.get('inc_words',''))
        self.exc = QLineEdit(self.f.get('exc_words',''))
        self.subj_len = QComboBox(); self.subj_len.addItems(["Any", "Short (<20 chars)", "Long (>60 chars)"])
        f_gen.addRow("Search:", self.q)
        f_gen.addRow("Include Words:", self.inc)
        f_gen.addRow("Exclude Words:", self.exc)
        f_gen.addRow("Subject Length:", self.subj_len)
        tabs.addTab(t_gen, "General")

        # People Tab
        t_ppl = QWidget(); f_ppl = QFormLayout(t_ppl)
        self.sender = QLineEdit(self.f.get('sender',''))
        self.domain = QLineEdit(self.f.get('domain',''))
        self.exc_dom = QLineEdit(self.f.get('exc_domain',''))
        f_ppl.addRow("From (Name):", self.sender)
        f_ppl.addRow("From Domain:", self.domain)
        f_ppl.addRow("Exclude Domain:", self.exc_dom)
        tabs.addTab(t_ppl, "People")

        # Tech Tab
        t_tech = QWidget(); f_tech = QFormLayout(t_tech)
        self.date_after = QDateEdit(QDate.currentDate().addYears(-1)); self.date_after.setCalendarPopup(True)
        self.date_before = QDateEdit(QDate.currentDate()); self.date_before.setCalendarPopup(True)
        self.day = QComboBox(); self.day.addItems(["Any", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])
        self.size = QSpinBox(); self.size.setSuffix(" MB"); self.size.setRange(0, 500)
        self.att_type = QLineEdit(self.f.get('att_type','')); self.att_type.setPlaceholderText("pdf, jpg, zip...")
        
        f_tech.addRow("After:", self.date_after)
        f_tech.addRow("Before:", self.date_before)
        f_tech.addRow("Day of Week:", self.day)
        f_tech.addRow("Min Size:", self.size)
        f_tech.addRow("Attachment Type:", self.att_type)
        tabs.addTab(t_tech, "Technical")

        layout.addWidget(tabs)
        
        # Checks
        checks = QHBoxLayout()
        self.chk_att = QCheckBox("Has Attachment"); self.chk_att.setChecked(self.f.get('att')=='yes')
        self.chk_link = QCheckBox("Has Links"); self.chk_link.setChecked(self.f.get('has_link')==True)
        self.chk_read = QCheckBox("Unread Only"); self.chk_read.setChecked(self.f.get('read')=='no')
        checks.addWidget(self.chk_att); checks.addWidget(self.chk_link); checks.addWidget(self.chk_read)
        layout.addLayout(checks)

        btns = QHBoxLayout()
        b_ok = QPushButton("Apply Filters"); b_ok.setObjectName("Primary"); b_ok.clicked.connect(self.accept)
        btns.addStretch(); btns.addWidget(b_ok)
        layout.addLayout(btns)

    def get_data(self):
        f = {'q': self.q.text(), 'inc_words': self.inc.text(), 'exc_words': self.exc.text(), 
             'sender': self.sender.text(), 'domain': self.domain.text(), 'exc_domain': self.exc_dom.text(),
             'att_type': self.att_type.text()}
        
        if self.day.currentIndex() > 0: f['day'] = self.day.currentText()
        if self.size.value() > 0: f['min_size'] = str(self.size.value() * 1024 * 1024)
        if self.subj_len.currentIndex() == 1: f['subj_len'] = 'short'
        if self.subj_len.currentIndex() == 2: f['subj_len'] = 'long'
        
        # Dates - simplistic usage
        f['date_after'] = self.date_after.date().startOfDay().toSecsSinceEpoch()
        f['date_before'] = self.date_before.date().endOfDay().toSecsSinceEpoch()

        if self.chk_att.isChecked(): f['att'] = 'yes'
        if self.chk_link.isChecked(): f['has_link'] = True
        if self.chk_read.isChecked(): f['read'] = 'no'
        
        return f

class InboxManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = EmailBackend()
        self.curr_folder = "Inbox"
        self.curr_cat = "primary"
        self.filters = {}
        self.is_compact = False
        
        self.setWindowTitle("InboxManager Ultimate")
        self.resize(1400, 900)
        self.setStyleSheet(CSS)
        self.setup_ui()
        self.refresh_sidebar()
        self.refresh_list()

    def setup_ui(self):
        root = QWidget(); self.setCentralWidget(root)
        layout = QVBoxLayout(root); layout.setSpacing(0); layout.setContentsMargins(0,0,0,0)

        # Header
        head = QFrame(); head.setObjectName("Header"); head.setFixedHeight(55)
        hl = QHBoxLayout(head)
        hl.addWidget(QLabel("<b>InboxManager</b>", styleSheet="font-size:16px; margin-right:15px;"))
        
        self.search = QLineEdit(); self.search.setPlaceholderText("Global Search..."); self.search.setFixedWidth(400)
        self.search.returnPressed.connect(self.quick_search)
        self.search.setCompleter(QCompleter(self.db.conn.execute("SELECT query FROM search_history ORDER BY timestamp DESC LIMIT 10").fetchall()))
        hl.addWidget(self.search)
        
        b_filt = QPushButton("Advanced Filters"); b_filt.clicked.connect(self.open_filters); hl.addWidget(b_filt)
        hl.addStretch()
        
        for lbl, fn in [("Import", self.import_mbox), ("Export Studio", self.open_export), ("Compact View", self.toggle_compact)]:
            b = QPushButton(lbl); b.clicked.connect(fn); hl.addWidget(b)
        layout.addWidget(head)

        # Splitter
        split = QSplitter(Qt.Orientation.Horizontal); split.setHandleWidth(1)
        layout.addWidget(split)

        # Sidebar
        self.sidebar = QListWidget(); self.sidebar.setFixedWidth(220)
        self.sidebar.itemClicked.connect(self.nav_click)
        split.addWidget(self.sidebar)

        # List
        mid = QWidget(); ml = QVBoxLayout(mid); ml.setContentsMargins(0,0,0,0); ml.setSpacing(0)
        self.tabs = QWidget(); tl = QHBoxLayout(self.tabs); tl.setContentsMargins(0,0,0,0)
        for c in ["Primary", "Promotions", "Social", "Updates"]:
            b = QPushButton(c); b.setCheckable(True); b.clicked.connect(lambda _, x=c.lower(): self.set_cat(x)); tl.addWidget(b)
        ml.addWidget(self.tabs)
        
        self.elist = QListWidget()
        self.elist.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.elist.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.elist.customContextMenuRequested.connect(self.context_menu)
        self.elist.itemClicked.connect(self.load_mail)
        ml.addWidget(self.elist)
        split.addWidget(mid)

        # Detail
        self.detail = QWidget(); dl = QVBoxLayout(self.detail); dl.setContentsMargins(0,0,0,0); dl.setSpacing(0)
        self.meta = QFrame(); self.meta.setObjectName("Meta"); self.meta.setVisible(False)
        mlo = QVBoxLayout(self.meta)
        self.lbl_sub = QLabel(); self.lbl_sub.setStyleSheet("font-size:18px; font-weight:bold; color:white;")
        self.lbl_from = QLabel(); self.lbl_from.setStyleSheet("font-weight:bold; color:#ccc;")
        mlo.addWidget(self.lbl_sub); mlo.addWidget(self.lbl_from)
        
        dl.addWidget(self.meta)
        self.web = QWebEngineView(); self.web.setStyleSheet("background:white;")
        dl.addWidget(self.web)
        split.addWidget(self.detail)
        split.setSizes([220, 450, 730])

    # --- LOGIC ---
    def refresh_sidebar(self):
        self.sidebar.clear()
        stats = self.db.get_stats()['unread']
        for name, icon in self.db.conn.execute("SELECT name, icon FROM folders ORDER BY type DESC, name ASC"):
            u = f" ({stats[name]})" if stats.get(name) else ""
            i = QListWidgetItem(f"{icon} {name}{u}")
            i.setData(Qt.ItemDataRole.UserRole, name)
            self.sidebar.addItem(i)

    def nav_click(self, item):
        self.curr_folder = item.data(Qt.ItemDataRole.UserRole)
        self.tabs.setVisible(self.curr_folder == "Inbox")
        self.refresh_list()

    def set_cat(self, c):
        self.curr_cat = c
        self.refresh_list()

    def quick_search(self):
        self.filters = {'q': self.search.text()}
        self.refresh_list()

    def open_filters(self):
        d = FilterDialog(self, self.filters)
        if d.exec():
            self.filters = d.get_data()
            self.refresh_list()

    def refresh_list(self):
        self.elist.clear()
        f = self.filters.copy()
        f.update({'folder': self.curr_folder, 'category': self.curr_cat if self.curr_folder=="Inbox" else None})
        
        for e in self.db.complex_search(f):
            i = QListWidgetItem()
            i.setData(Qt.ItemDataRole.UserRole, e['id'])
            
            # Icons
            star = "⭐" if e['is_starred'] else ""
            att = "📎" if e['has_attachment'] else ""
            read = "" if e['is_read'] else "●"
            
            # Content
            if self.is_compact:
                txt = f"{read} {e['sender_name'][:20]} | {e['subject'][:40]} | {e['date_str'][:10]}"
            else:
                txt = f"{read} {star}{e['sender_name'] or e['sender']}\n{att} {e['subject']}\n{e['date_str'][:16]}"
            
            i.setText(txt)
            if not e['is_read']: i.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            self.elist.addItem(i)

    def load_mail(self, item):
        eid = item.data(Qt.ItemDataRole.UserRole)
        d = self.db.conn.execute("SELECT * FROM emails WHERE id=?", (eid,)).fetchone()
        
        # Mark Read
        if not d['is_read']:
            self.db.bulk_op([str(eid)], 'read', 1)
            item.setFont(QFont())
            item.setText(item.text().replace("●", ""))
            self.refresh_sidebar()

        self.meta.setVisible(True)
        self.lbl_sub.setText(d['subject'])
        self.lbl_from.setText(f"{d['sender_name']} <{d['sender_addr']}> | {d['date_str']}")
        
        body = d['html_body'] or f"<pre>{d['body']}</pre>"
        self.web.setHtml(f"<style>body{{font-family:sans-serif;padding:20px;color:#222;}} a{{color:blue}}</style>{body}")

    def toggle_compact(self):
        self.is_compact = not self.is_compact
        self.refresh_list()

    # --- ACTIONS ---
    def context_menu(self, pos):
        m = QMenu()
        ids = [str(i.data(Qt.ItemDataRole.UserRole)) for i in self.elist.selectedItems()]
        
        m.addAction("Mark Read", lambda: self.bulk_act(ids, 'read', 1))
        m.addAction("Mark Unread", lambda: self.bulk_act(ids, 'read', 0))
        m.addAction("Delete", lambda: self.bulk_act(ids, 'delete'))
        
        sub = m.addMenu("Move to...")
        for row in self.db.conn.execute("SELECT name FROM folders"):
            sub.addAction(row[0], lambda f=row[0]: self.bulk_act(ids, 'move', f))
            
        m.exec(self.elist.mapToGlobal(pos))

    def bulk_act(self, ids, op, val=None):
        self.db.bulk_op(ids, op, val)
        self.refresh_list()
        self.refresh_sidebar()

    def import_mbox(self):
        p, _ = QFileDialog.getOpenFileName(self, "Import", "", "MBOX (*.mbox)")
        if p:
            self.db.import_mbox(p, lambda c: print(f"\r{c}", end=""))
            self.refresh_list()
            self.refresh_sidebar()

    # --- EXPORT LOGIC ---
    def open_export(self):
        d = ExportDialog(self)
        if d.exec():
            fmt, struct = d.get_settings()
            self.run_export(fmt, struct)

    def run_export(self, fmt, struct):
        path, _ = QFileDialog.getSaveFileName(self, "Export", f"export.{'zip' if fmt in ['eml','files','html'] else fmt}")
        if not path: return
        
        f = self.filters.copy()
        f.update({'folder': self.curr_folder, 'category': self.curr_cat if self.curr_folder=="Inbox" else None})
        rows = self.db.complex_search(f)
        
        try:
            if fmt == 'csv':
                with open(path, 'w', newline='', encoding='utf-8') as f:
                    w = csv.writer(f)
                    w.writerow(['Sender', 'Subject', 'Date', 'Size'])
                    for r in rows: w.writerow([r['sender'], r['subject'], r['date_str'], r['size_bytes']])
            
            elif fmt == 'json':
                with open(path, 'w') as f: json.dump(rows, f, default=str, indent=2)
            
            elif fmt in ['eml', 'html', 'files']:
                with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
                    for r in rows:
                        # GROUPING LOGIC
                        folder = "Unsorted"
                        if "Year" in struct: folder = r['date_str'][-4:] if r['date_str'] else "Unknown"
                        if "Year-Month" in struct: 
                            try: folder = datetime.fromtimestamp(r['timestamp']).strftime("%Y-%m")
                            except: folder = "Unknown"
                        elif "Domain" in struct: folder = r['sender_domain'] or "Unknown"
                        elif "Name" in struct: folder = r['sender_name'] or "Unknown"
                        elif "Day" in struct: folder = r['day_of_week'] or "Unknown"
                        
                        safe = "".join([c for c in r['subject'] if c.isalnum()]).strip()[:40]
                        
                        if fmt == 'files' and r['has_attachment']:
                            # Fake file generation for demo, real implementation extracts blobs
                            z.writestr(f"{folder}/{safe}_attachments.txt", f"Files: {r['attachment_names']}")
                        elif fmt == 'eml':
                            z.writestr(f"{folder}/{safe}.eml", f"Subject: {r['subject']}\n\n{r['body']}")
                        elif fmt == 'html':
                            z.writestr(f"{folder}/{safe}.html", f"<h1>{r['subject']}</h1>{r['html_body'] or r['body']}")

            QMessageBox.information(self, "Success", f"Exported {len(rows)} items.")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = InboxManager()
    window.show()
    sys.exit(app.exec())
