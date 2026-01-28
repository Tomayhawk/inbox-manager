import sys
import json
import os
import csv
import zipfile
from datetime import datetime

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QListWidget, QListWidgetItem, QLineEdit, 
                             QPushButton, QSplitter, QLabel, QFrame, QMenu, 
                             QDialog, QFormLayout, QComboBox, QMessageBox, 
                             QFileDialog, QAbstractItemView, QDateEdit,
                             QTabWidget, QGridLayout, QSpinBox)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import Qt, QUrl, QDate, QSize
from PyQt6.QtGui import QAction, QIcon, QCursor, QColor, QFont

from database import EmailBackend

# --- MODERN DARK THEME ---
THEME = """
    /* Main Backgrounds */
    QMainWindow, QDialog { background-color: #1f1f1f; color: #e0e0e0; }
    QWidget { background-color: #1f1f1f; color: #e0e0e0; font-family: 'Segoe UI', Roboto, sans-serif; font-size: 13px; }
    
    /* Header */
    QFrame#Header { background-color: #181818; border-bottom: 1px solid #333; }
    QLabel#Logo { font-size: 16px; font-weight: 600; color: #fff; margin-left: 10px; }
    
    /* Search Bar */
    QLineEdit#Search { 
        background-color: #2d2d2d; border: 1px solid #3e3e3e; border-radius: 6px; 
        color: white; padding: 6px 12px; font-size: 14px; 
    }
    QLineEdit#Search:focus { border: 1px solid #0078d4; background-color: #333; }
    
    /* Buttons */
    QPushButton { 
        background-color: #2d2d2d; border: 1px solid #3e3e3e; border-radius: 4px; 
        color: #ddd; padding: 6px 14px; font-weight: 500; 
    }
    QPushButton:hover { background-color: #383838; border-color: #555; }
    QPushButton:pressed { background-color: #1f1f1f; }
    QPushButton#Primary { background-color: #0078d4; border: 1px solid #0078d4; color: white; }
    QPushButton#Primary:hover { background-color: #006cc1; }
    
    /* Sidebar List */
    QListWidget#Sidebar { 
        background-color: #1f1f1f; border: none; outline: none; padding-top: 10px; 
    }
    QListWidget#Sidebar::item { 
        padding: 8px 12px; border-radius: 0 16px 16px 0; margin-right: 12px; 
        color: #d0d0d0; 
    }
    QListWidget#Sidebar::item:hover { background-color: #2d2d2d; }
    QListWidget#Sidebar::item:selected { 
        background-color: #37373d; color: white; font-weight: 600; border-left: 3px solid #0078d4;
    }

    /* Email List */
    QListWidget#EmailList { 
        background-color: #252526; border-right: 1px solid #333; border-top: 1px solid #333; 
    }
    QListWidget#EmailList::item { 
        border-bottom: 1px solid #333; padding: 12px 16px; 
    }
    QListWidget#EmailList::item:selected { 
        background-color: #37373d; border-left: 3px solid #0078d4; 
    }
    QListWidget#EmailList::item:hover { background-color: #2a2d2e; }

    /* Detail View */
    QFrame#Meta { background-color: #252526; border-bottom: 1px solid #333; padding: 20px; }
    QLabel#Subject { font-size: 20px; font-weight: 500; color: white; }
    QLabel#Sender { font-size: 14px; font-weight: 600; color: #fff; }
    QLabel#Date { font-size: 12px; color: #999; }

    /* Splitter */
    QSplitter::handle { background-color: #333; }
    
    /* Inputs in Dialogs */
    QComboBox, QSpinBox, QDateEdit { background: #333; border: 1px solid #444; color: white; padding: 5px; }
"""

class AdvancedFilterDialog(QDialog):
    def __init__(self, parent=None, filters=None):
        super().__init__(parent)
        self.setWindowTitle("Advanced Filters")
        self.resize(500, 450)
        self.f = filters or {}
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        
        self.inp_sender = QLineEdit(self.f.get('sender', ''))
        self.inp_subject = QLineEdit(self.f.get('subject', ''))
        self.inp_q = QLineEdit(self.f.get('q', ''))
        
        self.cmb_att = QComboBox()
        self.cmb_att.addItems(["Any", "Yes", "No"])
        if self.f.get('has_attachment'): 
            self.cmb_att.setCurrentText(self.f['has_attachment'].capitalize())

        self.cmb_sort = QComboBox()
        self.cmb_sort.addItems(["Date (Newest)", "Date (Oldest)", "Size (Largest)"])
        
        form.addRow("Search Text:", self.inp_q)
        form.addRow("From:", self.inp_sender)
        form.addRow("Subject:", self.inp_subject)
        form.addRow("Has Attachment:", self.cmb_att)
        form.addRow("Sort By:", self.cmb_sort)
        
        layout.addLayout(form)
        
        btns = QHBoxLayout()
        b_cancel = QPushButton("Cancel")
        b_cancel.clicked.connect(self.reject)
        b_apply = QPushButton("Apply")
        b_apply.setObjectName("Primary")
        b_apply.clicked.connect(self.accept)
        
        btns.addStretch()
        btns.addWidget(b_cancel)
        btns.addWidget(b_apply)
        layout.addLayout(btns)

    def get_data(self):
        d = {}
        if self.inp_q.text(): d['q'] = self.inp_q.text()
        if self.inp_sender.text(): d['sender'] = self.inp_sender.text()
        if self.inp_subject.text(): d['subject'] = self.inp_subject.text()
        
        att = self.cmb_att.currentText().lower()
        if att != 'any': d['has_attachment'] = att
        
        s = self.cmb_sort.currentIndex()
        if s == 0: d['sort'] = 'date_desc'
        elif s == 1: d['sort'] = 'date_asc'
        elif s == 2: d['sort'] = 'size_desc'
        
        return d

class InboxManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = EmailBackend()
        self.current_view_mode = 'folder' # or 'category'
        self.current_target = 'inbox'
        self.filters = {}

        self.setWindowTitle("InboxManager")
        self.resize(1300, 850)
        self.setStyleSheet(THEME)

        self.setup_ui()
        self.refresh_list()

    def setup_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(0)

        # 1. HEADER
        header = QFrame()
        header.setObjectName("Header")
        header.setFixedHeight(60)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(15, 0, 15, 0)
        
        logo = QLabel("InboxManager")
        logo.setObjectName("Logo")
        hl.addWidget(logo)
        
        hl.addSpacing(40)
        
        self.search_bar = QLineEdit()
        self.search_bar.setObjectName("Search")
        self.search_bar.setPlaceholderText("Search emails...")
        self.search_bar.setFixedWidth(500)
        self.search_bar.returnPressed.connect(self.quick_search)
        hl.addWidget(self.search_bar)
        
        btn_adv = QPushButton("Filters")
        btn_adv.setFixedWidth(70)
        btn_adv.clicked.connect(self.open_filters)
        hl.addWidget(btn_adv)
        
        hl.addStretch()
        
        btn_import = QPushButton("Import")
        btn_import.clicked.connect(self.import_mbox)
        hl.addWidget(btn_import)
        
        btn_export = QPushButton("Export")
        btn_export.clicked.connect(self.export_menu)
        hl.addWidget(btn_export)
        
        layout.addWidget(header)

        # 2. BODY
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        layout.addWidget(splitter)

        # -- LEFT: SIDEBAR --
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(230)
        
        # Define Items (Label, InternalKey, Mode)
        # Mode: 'folder' or 'category'
        self.nav_items = [
            ("Inbox", "inbox", "folder"),
            ("Starred", "starred", "folder"),
            ("Snoozed", "snoozed", "folder"),
            ("Important", "important", "folder"),
            ("Sent", "sent", "folder"),
            ("Scheduled", "scheduled", "folder"),
            ("Drafts", "drafts", "folder"),
            ("All Mail", "all", "folder"),
            ("Spam", "spam", "folder"),
            ("Bin", "bin", "folder"),
            # Divider visual hack not needed in QListWidget really
            ("--- Categories ---", None, None), 
            ("Social", "social", "category"),
            ("Updates", "updates", "category"),
            ("Promotions", "promotions", "category"),
            ("Forums", "forums", "category"),
            ("Purchases", "purchases", "category")
        ]
        
        for label, key, mode in self.nav_items:
            item = QListWidgetItem(label)
            if key is None: 
                item.setFlags(Qt.ItemFlag.NoItemFlags) # Divider
                item.setForeground(QColor("#666"))
                font = item.font()
                font.setBold(True)
                font.setPointSize(10)
                item.setFont(font)
            else:
                item.setData(Qt.ItemDataRole.UserRole, (key, mode))
            self.sidebar.addItem(item)
            
        self.sidebar.setCurrentRow(0)
        self.sidebar.itemClicked.connect(self.nav_clicked)
        splitter.addWidget(self.sidebar)

        # -- MIDDLE: LIST --
        self.email_list = QListWidget()
        self.email_list.setObjectName("EmailList")
        self.email_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.email_list.itemClicked.connect(self.load_email)
        splitter.addWidget(self.email_list)

        # -- RIGHT: DETAIL --
        detail_widget = QWidget()
        dv = QVBoxLayout(detail_widget)
        dv.setContentsMargins(0,0,0,0)
        dv.setSpacing(0)
        
        # Meta
        self.meta = QFrame()
        self.meta.setObjectName("Meta")
        self.meta.setVisible(False)
        ml = QVBoxLayout(self.meta)
        
        self.lbl_subj = QLabel("Subject")
        self.lbl_subj.setObjectName("Subject")
        self.lbl_subj.setWordWrap(True)
        
        row2 = QHBoxLayout()
        self.lbl_from = QLabel("Sender")
        self.lbl_from.setObjectName("Sender")
        self.lbl_date = QLabel("Date")
        self.lbl_date.setObjectName("Date")
        
        row2.addWidget(self.lbl_from)
        row2.addStretch()
        row2.addWidget(self.lbl_date)
        
        ml.addWidget(self.lbl_subj)
        ml.addSpacing(10)
        ml.addLayout(row2)
        dv.addWidget(self.meta)
        
        self.browser = QWebEngineView()
        self.browser.setStyleSheet("background: white;")
        dv.addWidget(self.browser)
        
        splitter.addWidget(detail_widget)
        splitter.setSizes([230, 450, 700])

    # --- LOGIC ---

    def nav_clicked(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data: return # Divider clicked
        
        target, mode = data
        self.current_target = target
        self.current_view_mode = mode
        self.refresh_list()

    def quick_search(self):
        self.filters = {'q': self.search_bar.text()}
        self.refresh_list()

    def open_filters(self):
        dlg = AdvancedFilterDialog(self, self.filters)
        if dlg.exec():
            self.filters = dlg.get_data()
            self.refresh_list()

    def refresh_list(self):
        self.email_list.clear()
        
        # Build Query
        f = self.filters.copy()
        f['view_mode'] = self.current_view_mode
        f['target'] = self.current_target
        
        rows = self.db.complex_search(f)
        
        if not rows:
            return

        for r in rows:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, r['id'])
            
            sender = r['sender_name'] or r['sender']
            date = r['date_str'][:16]
            subj = r['subject']
            
            # 3-line format
            txt = f"{sender}\n{subj}\n{date}"
            item.setText(txt)
            
            if r['is_read'] == 0:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                
            self.email_list.addItem(item)

    def load_email(self, item):
        eid = item.data(Qt.ItemDataRole.UserRole)
        data = self.db.get_email(eid)
        if not data: return
        
        self.meta.setVisible(True)
        self.lbl_subj.setText(data['subject'])
        self.lbl_from.setText(f"{data['sender_name']} <{data['sender_addr']}>")
        self.lbl_date.setText(data['date_str'])
        
        raw = data['html_body'] or f"<pre>{data['body']}</pre>"
        
        # Font Injection
        html = f"""
        <html><head><style>
            body {{ font-family: 'Segoe UI', sans-serif; padding: 20px; color: #202124; margin:0; }}
            a {{ color: #1a73e8; }}
            pre {{ background: #f1f3f4; padding: 10px; font-family: Consolas; }}
        </style></head><body>{raw}</body></html>
        """
        self.browser.setHtml(html)

    # --- ACTIONS ---

    def import_mbox(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select MBOX", "", "MBOX Files (*.mbox)")
        if path:
            def prog(c, t): print(f"Importing {c}/{t}")
            success, msg = self.db.import_mbox(path, prog)
            QMessageBox.information(self, "Import", msg)
            self.refresh_list()

    def export_menu(self):
        menu = QMenu(self)
        menu.addAction("Export CSV Report", lambda: self.do_export('csv'))
        menu.addAction("Export JSON Dump", lambda: self.do_export('json'))
        menu.addAction("Export EML (ZIP)", lambda: self.do_export('eml'))
        menu.addAction("Export Organized HTML (ZIP)", lambda: self.do_export('html'))
        menu.exec(QCursor.pos())

    def do_export(self, mode):
        # 1. Get Data
        f = self.filters.copy()
        f['view_mode'] = self.current_view_mode
        f['target'] = self.current_target
        rows = self.db.complex_search(f)
        
        if not rows:
            QMessageBox.warning(self, "Export", "No emails to export.")
            return

        # 2. File Dialog
        ext = 'csv' if mode == 'csv' else 'json' if mode == 'json' else 'zip'
        path, _ = QFileDialog.getSaveFileName(self, "Save Export", f"export.{ext}", f"Files (*.{ext})")
        if not path: return
        
        try:
            if mode == 'csv':
                with open(path, 'w', newline='', encoding='utf-8') as f:
                    cw = csv.writer(f)
                    cw.writerow(['ID', 'Sender', 'Subject', 'Date', 'Folder', 'Category'])
                    for r in rows:
                        cw.writerow([r['id'], r['sender_addr'], r['subject'], r['date_str'], r['folder'], r['category']])
            
            elif mode == 'json':
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(rows, f, default=str, indent=2)
            
            elif mode == 'eml':
                with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
                    for r in rows:
                        safe = "".join([c for c in r['subject'] if c.isalnum()]).strip()[:30]
                        fname = f"{safe}_{r['id']}.eml"
                        content = f"From: {r['sender']}\nTo: {r['recipient']}\nSubject: {r['subject']}\n\n{r['html_body'] or r['body']}"
                        z.writestr(fname, content)
            
            elif mode == 'html':
                with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
                    for r in rows:
                        folder = r['date_str'][-4:] if r['date_str'] else "Unknown"
                        safe = "".join([c for c in r['subject'] if c.isalnum()]).strip()[:30]
                        fname = f"{folder}/{safe}_{r['id']}.html"
                        html = f"<h1>{r['subject']}</h1><hr>{r['html_body'] or r['body']}"
                        z.writestr(fname, html)
            
            QMessageBox.information(self, "Success", f"Exported {len(rows)} emails.")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = InboxManager()
    window.show()
    sys.exit(app.exec())
