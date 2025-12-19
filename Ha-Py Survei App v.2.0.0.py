import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
import sqlite3, os, re, uuid, math, hashlib
from datetime import datetime
from collections import deque
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_CENTER
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
import matplotlib
matplotlib.use('Agg')  # Untuk mode non-interaktif

APP_TITLE = "Hap-Py Survei App"
APP_VERSION = "1.0.0"

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
PHONE_RE = re.compile(r'^[0-9+\-\s()]{11,15}$')

def now_ts(): return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
def gen_id(): return str(uuid.uuid4())
def hash_pw(p): return hashlib.sha256(p.encode('utf-8')).hexdigest()
def valid_email(e): return bool(EMAIL_RE.match(e)) if e else True
def valid_phone(p): return bool(PHONE_RE.match(p)) if p else True

# ==================================================
# DATABASE
# ==================================================
class SimpleDB:
    def __init__(self, path='survey_app.db'):
        self.path = path
        self._init_db()

    def conn(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def _init_db(self):
        with self.conn() as c:
            c.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    is_admin INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            c.execute('''
                CREATE TABLE IF NOT EXISTS surveys (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    customer_name TEXT NOT NULL,
                    customer_email TEXT,
                    customer_phone TEXT,
                    customer_gender TEXT,
                    customer_location TEXT,
                    quality INTEGER,
                    timeliness INTEGER,
                    service INTEGER,
                    overall INTEGER,
                    comments TEXT,
                    owner_username TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            if c.execute("SELECT COUNT(*) FROM users WHERE username='admin'").fetchone()[0] == 0:
                c.execute("INSERT INTO users (username,password,full_name,is_admin) VALUES (?,?,?,?)",
                         ('admin', hash_pw('admin123'), 'Administrator', 1))
            c.commit()

    def authenticate(self, username, password):
        hp = hash_pw(password)
        with self.conn() as c:
            r = c.execute("SELECT id,username,full_name,is_admin FROM users WHERE username=? AND password=?",
                         (username, hp)).fetchone()
            return dict(r) if r else None

    def register_user(self, username, password, full_name):
        hp = hash_pw(password)
        try:
            with self.conn() as c:
                cur = c.execute("INSERT INTO users (username,password,full_name) VALUES (?,?,?)",
                              (username, hp, full_name))
                c.commit()
                return cur.lastrowid
        except sqlite3.IntegrityError:
            return None

    def save_survey(self, s):
        with self.conn() as c:
            c.execute('''
                INSERT INTO surveys
                (id,timestamp,customer_name,customer_email,customer_phone,
                 customer_gender,customer_location,quality,timeliness,
                 service,overall,comments,owner_username)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''', (s['id'], s['timestamp'], s['customer_name'], s['customer_email'],
                  s['customer_phone'], s['customer_gender'], s['customer_location'],
                  s['quality'], s['timeliness'], s['service'], s['overall'],
                  s['comments'], s['owner_username']))
            c.commit()
            return True

    def get_all_surveys(self):
        with self.conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM surveys ORDER BY timestamp DESC").fetchall()]
                
    def update_survey(self, sid, s):
        with self.conn() as c:
            c.execute('''UPDATE surveys SET
                timestamp=?, customer_name=?, customer_email=?, customer_phone=?,
                customer_gender=?, customer_location=?, quality=?, timeliness=?,
                service=?, overall=?, comments=? WHERE id=?
            ''', (s['timestamp'], s['customer_name'], s['customer_email'], s['customer_phone'],
                  s.get('customer_gender',''), s.get('customer_location',''),
                  s['quality'], s['timeliness'], s['service'], s['overall'], s.get('comments',''), sid))
            c.commit()
            return True

    def delete_survey(self, sid):
        with self.conn() as c:
            cur = c.execute("DELETE FROM surveys WHERE id=?", (sid,))
            c.commit()
            return cur.rowcount > 0

    def search_surveys(self, keyword):
        with self.conn() as c:
            kw = f"%{keyword}%"
            cursor = c.execute('''
                SELECT * FROM surveys
                WHERE customer_name LIKE ? OR customer_email LIKE ? OR customer_location LIKE ? OR comments LIKE ?
                ORDER BY timestamp DESC
            ''', (kw, kw, kw, kw))
            return [dict(r) for r in cursor.fetchall()]

    def get_all_users(self):
        with self.conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT id, username, full_name, is_admin FROM users ORDER BY id").fetchall()]

# ------------------ PDF Writer ------------------
def make_pdf_reportlab(path, rows, footer_info=None):
    """Buat PDF dengan desain naratif, 4 responden per halaman"""
    try:
        doc = SimpleDocTemplate(path, pagesize=A4, topMargin=1.5*cm, bottomMargin=1.5*cm,
                                leftMargin=1.5*cm, rightMargin=1.5*cm)
        elements = []
        styles = getSampleStyleSheet()
        
        title_style = ParagraphStyle('MainTitle', parent=styles['Title'], fontSize=16,
                                     alignment=TA_CENTER, spaceAfter=8, textColor=colors.HexColor('#1a237e'))
        detail_style = ParagraphStyle('DetailStyle', parent=styles['Normal'], fontSize=9,
                                       spaceAfter=2, textColor=colors.HexColor('#37474f'), leftIndent=8)
        comment_style = ParagraphStyle('CommentStyle', parent=styles['Normal'], fontSize=9,
                                        spaceAfter=8, textColor=colors.HexColor('#546e7a'), leftIndent=8)
        footer_style = ParagraphStyle('FooterStyle', parent=styles['Normal'], fontSize=7,
                                       textColor=colors.HexColor('#90a4ae'), alignment=TA_CENTER)

        elements.append(Spacer(1, 2))
        elements.append(Paragraph("<b>LAPORAN SURVEY KEPUASAN</b>", title_style))
        elements.append(Spacer(1, 10))
        
        current_date = datetime.now().strftime("%d %B %Y")
        meta_text = f"<b>Tanggal:</b> {current_date} | <b>Oleh:</b> {footer_info.get('user', 'Unknown')} | <b>Responden:</b> {len(rows)}"
        elements.append(Paragraph(meta_text, detail_style))
        elements.append(Spacer(1, 15))

        def get_rating_label(value, max_value=5):
            percentage = (value / max_value) * 100
            if percentage >= 80: return f"<font color='#2e7d32'><b>Sangat Baik</b> ({value}/{max_value})</font>"
            elif percentage >= 60: return f"<font color='#f57c00'><b>Baik</b> ({value}/{max_value})</font>"
            elif percentage >= 40: return f"<font color='#ffb300'><b>Cukup</b> ({value}/{max_value})</font>"
            else: return f"<font color='#c62828'><b>Perlu Perbaikan</b> ({value}/{max_value})</font>"

        def create_survey_element(idx, row):
            survey_date = str(row.get('timestamp', ''))[:16]
            customer_name = str(row.get('customer_name', '')).strip()[:25]
            customer_location = str(row.get('customer_location', '')).strip() or "Tidak disebutkan"
            comments = str(row.get('comments', '')).strip() or "Tidak ada komentar"
            if len(comments) > 120: comments = comments[:117] + "..."
            
            survey_content = f"""
            <para>
            <b>Tanggal:</b> {survey_date}<br/>
            <b>Nama:</b> {customer_name}<br/>
            <b>Lokasi:</b> {customer_location}<br/><br/>
            <b>HASIL PENILAIAN:</b><br/>
            • <b>Kualitas:</b> {get_rating_label(row.get('quality', 0))}<br/>
            • <b>Ketepatan:</b> {get_rating_label(row.get('timeliness', 0))}<br/>
            • <b>Layanan:</b> {get_rating_label(row.get('service', 0))}<br/>
            • <b>Kepuasan:</b> {get_rating_label(row.get('overall', 0), 10)}<br/><br/>
            <b>KOMENTAR:</b><br/>
            <i>"{comments}"</i>
            </para>
            """
            return Paragraph(survey_content, detail_style)

        display_rows = rows[:50]
        if display_rows:
            surveys_per_page = 4
            total_pages = (len(display_rows) + surveys_per_page - 1) // surveys_per_page
            
            for page_num in range(total_pages):
                if page_num > 0: elements.append(PageBreak())
                start_idx = page_num * surveys_per_page
                end_idx = min(start_idx + surveys_per_page, len(display_rows))
                
                for i, survey in enumerate(display_rows[start_idx:end_idx]):
                    survey_idx = start_idx + i + 1
                    elements.append(Paragraph(f"<b>📋 RESPONDEN #{survey_idx}</b>", detail_style))
                    elements.append(create_survey_element(survey_idx, survey))
                    if i < end_idx - start_idx - 1:
                        elements.append(Paragraph("<hr width='100%' size='0.3' color='#e0e0e0'/>"))
                        elements.append(Spacer(1, 3))
                elements.append(Spacer(1, 12))

        elements.append(PageBreak())
        if rows and len(rows) > 0:
            total = len(rows)
            avg_quality = sum(r.get('quality', 0) for r in rows) / total
            avg_timeliness = sum(r.get('timeliness', 0) for r in rows) / total
            avg_service = sum(r.get('service', 0) for r in rows) / total
            avg_overall = sum(r.get('overall', 0) for r in rows) / total
            
            elements.append(Paragraph("<b>ANALISIS STATISTIK</b>", title_style))
            elements.append(Spacer(1, 25))
            
            stats_text = f"""
            <b>📊 STATISTIK UTAMA</b><br/>
            <b>Total Responden:</b> {total} orang<br/>
            <b>Periode:</b> {rows[-1].get('timestamp', '')[:10] if rows else 'N/A'} - {rows[0].get('timestamp', '')[:10] if rows else 'N/A'}<br/><br/>
            <b>📈 RATA-RATA PENILAIAN</b><br/>
            <b>Kualitas:</b> {avg_quality:.2f}/5 ({(avg_quality/5)*100:.1f}%)<br/>
            <b>Ketepatan:</b> {avg_timeliness:.2f}/5 ({(avg_timeliness/5)*100:.1f}%)<br/>
            <b>Layanan:</b> {avg_service:.2f}/5 ({(avg_service/5)*100:.1f}%)<br/>
            <b>Kepuasan:</b> {avg_overall:.2f}/10 ({(avg_overall/10)*100:.1f}%)
            """
            elements.append(Paragraph(stats_text, detail_style))
            elements.append(Spacer(1, 20))

        if len(rows) >= 3:
            recent = rows[:3]
            recent_avg = sum(r.get('overall', 0) for r in recent) / 3
            overall_avg = avg_overall
                
            trend_text = f"""
            <para>
            <font size=10>
            <b>📅 TREN TERKINI</b><br/>
            <b>3 Survey Terbaru:</b> {recent_avg:.2f}/10<br/>
            <b>Seluruh Data:</b> {overall_avg:.2f}/10<br/>
            """
                
            if recent_avg > overall_avg + 0.5:
                trend_text += f"""<font color='#2e7d32'>📈 <b>TREN MENINGKAT</b></font>"""
            elif recent_avg < overall_avg - 0.5:
                trend_text += f"""<font color='#c62828'>📉 <b>TREN MENURUN</b></font>"""
            else:
                trend_text += f"""<font color='#f57c00'>➡️ <b>TREN STABIL</b></font>"""
                
            trend_text += "</font></para>"
            trend_para = Paragraph(trend_text, detail_style)
            elements.append(trend_para)
                
            elements.append(Spacer(1, 15))

        recommendations = """
            <para>
            <font size=10>
            <b>💡 REKOMENDASI</b><br/>
            1. Pertahankan aspek dengan rating tertinggi<br/>
            2. Fokus perbaikan pada aspek terendah<br/>
            3. Tinjau komentar untuk insight spesifik<br/>
            4. Lakukan follow-up pada rating rendah<br/>
            5. Pantau tren kepuasan berkala
            </font>
            </para>
            """
        rec_para = Paragraph(recommendations, detail_style)
        elements.append(rec_para)
            
        elements.append(Spacer(1, 15))

        current_year = datetime.now().year
        footer_text = f"<b>Laporan Survey Kepuasan</b><br/>{APP_TITLE} - versi {APP_VERSION} • © {current_year}"
        elements.append(Paragraph(footer_text, footer_style))
        
        def add_header_footer(canvas, doc):
            canvas.saveState()
            page_num = canvas.getPageNumber()
            if page_num > 1 and page_num <= ((len(display_rows) + 1) // 2 if display_rows else 0):            
                canvas.setFont('Helvetica', 6)
                canvas.setFillColor(colors.HexColor('#90a4ae'))
                canvas.drawString(1.5*cm, 0.8*cm, f"Hal. {page_num}")
                canvas.drawCentredString(doc.width/2 + 1.5*cm, 0.8*cm, f"Total: {len(rows)} responden")
                canvas.restoreState()
        
        doc.build(elements, onFirstPage=add_header_footer, onLaterPages=add_header_footer)
        return True, None
        
    except Exception as e:
        import traceback
        return False, f"Error membuat PDF: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"

# ------------------ MAIN APP CLASS ------------------
class SurveyApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.configure(bg='#e3f2fd')
        
        self.setup_initial_window()
        self.db = SimpleDB()
        self.current_user = None
        self.surveys = []
        self.deleted = deque(maxlen=50)
        self.form_vars = {}
        self.editing_id = None
        
        self.show_login_page()

    def setup_initial_window(self):
        window_width = 400
        window_height = 500
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width // 2) - (window_width // 2)
        y = (screen_height // 2) - (window_height // 2)
        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")
        self.root.deiconify()
        self.root.update()

    def center_window(self, width=None, height=None):
        if width and height:
            self.root.geometry(f"{width}x{height}")
        
        self.root.update_idletasks()
        window_width = self.root.winfo_width()
        window_height = self.root.winfo_height()
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        
        x = (screen_width // 2) - (window_width // 2)
        y = (screen_height // 2) - (window_height // 2)
        self.root.geometry(f"+{x}+{y}")

    def show_login_page(self):
        for w in self.root.winfo_children(): 
            w.destroy()
        
        self.root.configure(bg='#e3f2fd')
        self.root.geometry("400x500")
        self.center_window()
        
        # Main container
        main_container = tk.Frame(self.root, bg='#e3f2fd')
        main_container.pack(expand=True, fill='both', padx=20, pady=20)
        
        # Header
        header_frame = tk.Frame(main_container, bg='#e3f2fd')
        header_frame.pack(pady=(20, 30))
        
        title_label = tk.Label(header_frame, 
                              text="Hap-Py Survei App",
                              font=("Arial", 24, "bold"),
                              fg="#1a237e",
                              bg='#e3f2fd')
        title_label.pack(pady=(0, 10))
        
        subtitle_label = tk.Label(header_frame,
                                 text="Sistem Survey Kepuasan",
                                 font=("Arial", 12),
                                 fg="#0d47a1",
                                 bg='#e3f2fd')
        subtitle_label.pack()
        
        # Form container
        form_container = tk.Frame(main_container, bg='#e3f2fd')
        form_container.pack(expand=True, fill='both')
        
        # Frame untuk form input
        form_frame = tk.Frame(form_container, bg='#ffffff', relief='solid', bd=1)
        form_frame.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.9, relheight=0.6)
        
        # Username
        tk.Label(form_frame, 
                text="Username",
                font=("Arial", 10, "bold"),
                bg='#ffffff',
                fg="#1a237e").place(relx=0.1, rely=0.15, anchor='w')
        
        username_bg = tk.Frame(form_frame, bg='#f5f5f5', relief='sunken', bd=1, height=30)
        username_bg.place(relx=0.1, rely=0.25, relwidth=0.8, height=30)
        
        self.login_username = tk.StringVar()
        username_entry = tk.Entry(form_frame,
                                 textvariable=self.login_username,
                                 font=("Arial", 10),
                                 bg='#f5f5f5',
                                 relief='flat',
                                 bd=0,
                                 highlightthickness=0)
        username_entry.place(relx=0.12, rely=0.25, relwidth=0.76, height=26)
        username_entry.focus()
        
        # Password
        tk.Label(form_frame, 
                text="Password",
                font=("Arial", 10, "bold"),
                bg='#ffffff',
                fg="#1a237e").place(relx=0.1, rely=0.45, anchor='w')
        
        password_bg = tk.Frame(form_frame, bg='#f5f5f5', relief='sunken', bd=1, height=30)
        password_bg.place(relx=0.1, rely=0.55, relwidth=0.8, height=30)
        
        self.login_password = tk.StringVar()
        password_entry = tk.Entry(form_frame,
                                 textvariable=self.login_password,
                                 show='•',
                                 font=("Arial", 10),
                                 bg='#f5f5f5',
                                 relief='flat',
                                 bd=0,
                                 highlightthickness=0)
        password_entry.place(relx=0.12, rely=0.55, relwidth=0.76, height=26)
        
        # Tombol LOGIN
        login_btn_main = tk.Button(form_frame,
                                  text="LOGIN",
                                  font=("Arial", 10, "bold"),
                                  bg='#1a237e',
                                  fg="#ffffff",
                                  relief='solid',
                                  bd=1,
                                  width=20,
                                  height=2,
                                  command=self.do_login)
        login_btn_main.place(relx=0.5, rely=0.85, anchor="center", relwidth=0.5)
        
        # Button container lainnya
        button_frame = tk.Frame(main_container, bg='#e3f2fd')
        button_frame.pack(side='bottom', pady=(0, 20))
        
        register_btn = tk.Button(button_frame,
                                text="Buat Akun Baru",
                                font=("Arial", 10),
                                bg='#ffffff',
                                fg="#1a237e",
                                relief='solid',
                                bd=1,
                                width=15,
                                height=2,
                                command=self.show_register_page)
        register_btn.pack(side='left', padx=5)
        
        guest_btn = tk.Button(button_frame,
                             text="Mode Tamu",
                             font=("Arial", 10),
                             bg='#ffffff',
                             fg="#1a237e",
                             relief='solid',
                             bd=1,
                             width=15,
                             height=2,
                             command=self.guest_mode)
        guest_btn.pack(side='left', padx=5)
        
        # Footer
        footer_frame = tk.Frame(main_container, bg='#e3f2fd')
        footer_frame.pack(side='bottom', pady=(0, 10))
        
        tk.Label(footer_frame,
                text=f"© 2024 Hap-Py Survei App v{APP_VERSION}",
                font=("Arial", 8),
                fg="#666666",
                bg='#e3f2fd').pack()
        
        self.root.bind('<Return>', lambda e: self.do_login())
        self.center_window()

    def show_register_page(self):
        for w in self.root.winfo_children(): 
            w.destroy()
        
        self.root.configure(bg='#e3f2fd')
        self.root.geometry("450x500")
        self.center_window()
        
        main_container = tk.Frame(self.root, bg='#e3f2fd')
        main_container.pack(expand=True, fill='both', padx=20, pady=20)
        
        # Header
        header_frame = tk.Frame(main_container, bg='#e3f2fd')
        header_frame.pack(pady=(10, 20))
        
        title_label = tk.Label(header_frame,
                              text="Buat Akun Baru",
                              font=("Arial", 16, "bold"),
                              fg="#1a237e",
                              bg='#e3f2fd')
        title_label.pack(pady=(0, 5))
        
        separator = tk.Frame(header_frame, height=2, bg='#bbbbbb')
        separator.pack(fill='x', pady=5)
        
        subtitle_label = tk.Label(header_frame,
                                 text="Bergabung dengan sistem survey kami",
                                 font=("Arial", 10),
                                 fg="#666666",
                                 bg='#e3f2fd')
        subtitle_label.pack(pady=(5, 0))
        
        # Form container
        form_container = tk.Frame(main_container, bg='#e3f2fd')
        form_container.pack(expand=True, fill='both')
        
        form_frame = tk.Frame(form_container, bg='#ffffff', relief='solid', bd=1)
        form_frame.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.9, relheight=0.6)
        
        # Fields
        fields = [
            ("Nama Lengkap", "reg_fullname"),
            ("Username", "reg_username"),
            ("Password", "reg_password", True),
            ("Konfirmasi Password", "reg_password2", True)
        ]
        
        for i, field in enumerate(fields):
            label_text, var_name = field[0], field[1]
            is_password = len(field) > 2 and field[2]
            
            tk.Label(form_frame,
                    text=label_text,
                    font=("Arial", 9),
                    bg='#ffffff',
                    fg="#333333").place(relx=0.1, rely=0.1 + i*0.2, anchor='w')
            
            field_bg = tk.Frame(form_frame, bg='#f5f5f5', relief='sunken', bd=1, height=25)
            field_bg.place(relx=0.1, rely=0.15 + i*0.2, relwidth=0.8, height=25)
            
            var = tk.StringVar()
            setattr(self, var_name, var)
            
            entry = tk.Entry(form_frame,
                           textvariable=var,
                           show='•' if is_password else '',
                           font=("Arial", 10),
                           bg='#f5f5f5',
                           relief='flat',
                           bd=0,
                           highlightthickness=0)
            entry.place(relx=0.12, rely=0.15 + i*0.2, relwidth=0.76, height=21)
            
            if i == 0:
                entry.focus()
        
        # Tambahkan indikator panjang password
        self.password_length_label = tk.Label(form_frame,
                                             text="",
                                             font=("Arial", 8),
                                             bg='#ffffff',
                                             fg="#666666")
        self.password_length_label.place(relx=0.1, rely=0.82, anchor='w')
        
        # Fungsi untuk update indikator
        def update_password_length(*args):
            length = len(self.reg_password.get())
            if length == 0:
                self.password_length_label.config(text="Minimal 6 karakter", fg="#666666")
            elif length < 6:
                self.password_length_label.config(text=f"{length}/6 karakter (kurang)", fg="#d32f2f")
            else:
                self.password_length_label.config(text=f"{length}/6 karakter ✓", fg="#388e3c")
        
        # Bind fungsi ke variabel password
        self.reg_password.trace('w', update_password_length)
        
        # Button container
        button_frame = tk.Frame(main_container, bg='#e3f2fd')
        button_frame.pack(side='bottom', pady=(0, 20))
        
        register_btn = tk.Button(button_frame,
                                text="DAFTAR SEKARANG",
                                font=("Arial", 10, "bold"),
                                bg='#1a237e',
                                fg="#ffffff",
                                relief='solid',
                                bd=1,
                                width=20,
                                height=2,
                                command=self.do_register)
        register_btn.pack(side='left', padx=5)
        
        back_btn = tk.Button(button_frame,
                            text="KEMBALI",
                            font=("Arial", 10),
                            bg='#ffffff',
                            fg="#1a237e",
                            relief='solid',
                            bd=1,
                            width=15,
                            height=2,
                            command=self.show_login_page)
        back_btn.pack(side='left', padx=5)
        
        # Footer
        footer_frame = tk.Frame(main_container, bg='#e3f2fd')
        footer_frame.pack(side='bottom', pady=(0, 10))
        
        tk.Label(footer_frame,
                text=f"© 2024 SurveyPro v{APP_VERSION}",
                font=("Arial", 8),
                fg="#666666",
                bg='#e3f2fd').pack()
        
        self.center_window()

    def do_login(self):
        username = self.login_username.get().strip()
        password = self.login_password.get()
        
        if not username or not password:
            messagebox.showerror("Error", "Username dan password harus diisi")
            return
        
        user = self.db.authenticate(username, password)
        if user:
            self.current_user = user
            self.load_surveys()
            self.build_main_app()
        else:
            messagebox.showerror("Error", "Username atau password salah")

    def do_register(self):
        fullname = self.reg_fullname.get().strip()
        username = self.reg_username.get().strip()
        password = self.reg_password.get()
        password2 = self.reg_password2.get()

        errors = []
        if not fullname: errors.append("Nama lengkap harus diisi")
        if not username: errors.append("Username harus diisi")
        if len(username) < 6: errors.append("Username minimal 6 karakter")
        if not password: errors.append("Password harus diisi")
        if len(password) < 6: errors.append("Password minimal 6 karakter")
        if password != password2: errors.append("Password tidak cocok")

        if errors:
            messagebox.showerror("Validasi Error", "\n".join(errors))
            return

        if self.db.register_user(username, password, fullname):
            messagebox.showinfo("Sukses", "Registrasi berhasil! Silakan login.")
            self.show_login_page()
        else:
            messagebox.showerror("Error", "Username sudah digunakan")

    def guest_mode(self):
        self.current_user = {'id': None, 'username': 'guest', 'full_name': 'Guest User', 'is_admin': 0}
        self.load_surveys()
        self.build_main_app()

    def build_main_app(self):
        for w in self.root.winfo_children(): 
            w.destroy()
        
        self.root.unbind('<Return>')
        self.root.geometry("1300x750")
        self.center_window()
        self.root.configure(bg='white')
        
        # Header
        header_frame = tk.Frame(self.root, bg='#1a237e', height=80)
        header_frame.pack(fill='x', side='top')
        header_frame.pack_propagate(False)
        
        title_label = tk.Label(header_frame, 
                              text="Sistem Survei Kepuasan",
                              font=("Arial", 20, "bold"),
                              fg="white",
                              bg='#1a237e')
        title_label.pack(side='left', padx=30, pady=20)
        
        user_frame = tk.Frame(header_frame, bg='#1a237e')
        user_frame.pack(side='right', padx=30, pady=20)
        
        user_text = f"{self.current_user['full_name']}"
        if self.is_admin():
            user_text += " (Admin)"
        
        user_label = tk.Label(user_frame,
                             text=user_text,
                             font=("Arial", 11),
                             fg="white",
                             bg='#1a237e')
        user_label.pack(side='left', padx=(0, 20))
        
        if self.is_admin():
            admin_btn = tk.Button(user_frame,
                                 text="Dashboard Admin",
                                 font=("Arial", 10),
                                 bg='#ffffff',
                                 fg="#1a237e",
                                 relief='solid',
                                 bd=1,
                                 width=15,
                                 command=self.open_admin_dashboard)
            admin_btn.pack(side='left', padx=(0, 10))
        
        logout_btn = tk.Button(user_frame,
                              text="Logout",
                              font=("Arial", 10),
                              bg='#ffffff',
                              fg="#1a237e",
                              relief='solid',
                              bd=1,
                              width=10,
                              command=self.logout)
        logout_btn.pack(side='left')
        
        # Main container
        main_container = tk.Frame(self.root, bg='#f5f5f5')
        main_container.pack(fill='both', expand=True, padx=20, pady=20)
        
        # Kolom kiri: Form Survey
        left_frame = tk.Frame(main_container, bg='white', relief='solid', bd=1)
        left_frame.pack(side='left', fill='both', expand=True, padx=(0, 10))
        
        form_header = tk.Frame(left_frame, bg='#1a237e', height=40)
        form_header.pack(fill='x', side='top')
        form_header.pack_propagate(False)
        
        tk.Label(form_header,
                text="📝 FORM SURVEY BARU",
                font=("Arial", 12, "bold"),
                fg="white",
                bg='#1a237e').pack(pady=10)
        
        form_container = tk.Frame(left_frame, bg='white')
        form_container.pack(fill='both', expand=True, padx=20, pady=20)
        
        # Form fields
        form_fields = [
            ("Nama Pelanggan:", 'name', 'entry'),
            ("Email:", 'email', 'entry'),
            ("Telepon:", 'phone', 'entry'),
            ("Lokasi:", 'location', 'entry'),
            ("Kualitas (1-5):", 'quality', 'spinbox', 1, 5),
            ("Ketepatan (1-5):", 'timeliness', 'spinbox', 1, 5),
            ("Layanan (1-5):", 'service', 'spinbox', 1, 5),
            ("Kepuasan (1-10):", 'overall', 'spinbox', 1, 10)
        ]
        
        for idx, (label, var_name, field_type, *args) in enumerate(form_fields):
            tk.Label(form_container,
                    text=label,
                    font=("Arial", 10),
                    bg='white',
                    fg="#333333",
                    anchor='w').grid(row=idx, column=0, sticky='w', pady=8, padx=(0, 10))
            
            if field_type == 'entry':
                var = tk.StringVar()
                entry_frame = tk.Frame(form_container, bg='#f5f5f5', relief='sunken', bd=1, height=30)
                entry_frame.grid(row=idx, column=1, sticky='ew', pady=8, padx=(0, 0))
                entry_frame.grid_propagate(False)
                
                entry = tk.Entry(entry_frame,
                               textvariable=var,
                               font=("Arial", 10),
                               bg='#f5f5f5',
                               relief='flat',
                               bd=0,
                               highlightthickness=0)
                entry.pack(fill='both', expand=True, padx=5, pady=2)
                self.form_vars[var_name] = var
                
            elif field_type == 'spinbox':
                var = tk.IntVar(value=3 if var_name != 'overall' else 5)
                from_val, to_val = args
                
                spin_frame = tk.Frame(form_container, bg='#f5f5f5', relief='sunken', bd=1, height=30)
                spin_frame.grid(row=idx, column=1, sticky='w', pady=8, padx=(0, 0))
                spin_frame.grid_propagate(False)
                
                spinbox = tk.Spinbox(spin_frame,
                                    from_=from_val,
                                    to=to_val,
                                    textvariable=var,
                                    font=("Arial", 10),
                                    bg='#f5f5f5',
                                    relief='flat',
                                    bd=0,
                                    width=8,
                                    highlightthickness=0)
                spinbox.pack(fill='both', expand=True, padx=5, pady=2)
                self.form_vars[var_name] = var
        
        # Komentar
        tk.Label(form_container,
                text="Komentar:",
                font=("Arial", 10),
                bg='white',
                fg="#333333",
                anchor='w').grid(row=len(form_fields), column=0, sticky='nw', pady=8, padx=(0, 10))
        
        comment_frame = tk.Frame(form_container, bg='#f5f5f5', relief='sunken', bd=1, height=100)
        comment_frame.grid(row=len(form_fields), column=1, sticky='nsew', pady=8, padx=(0, 0))
        comment_frame.grid_propagate(False)
        
        self.comments = scrolledtext.ScrolledText(comment_frame,
                                                 width=30,
                                                 height=5,
                                                 font=("Arial", 10),
                                                 bg='#f5f5f5',
                                                 relief='flat',
                                                 bd=0,
                                                 highlightthickness=0)
        self.comments.pack(fill='both', expand=True, padx=5, pady=5)
        
        # Tombol form
        button_frame = tk.Frame(form_container, bg='white')
        button_frame.grid(row=len(form_fields)+1, column=0, columnspan=2, pady=20, sticky='ew')
        
        button_frame.columnconfigure(0, weight=1)
        button_frame.columnconfigure(1, weight=1)
        button_frame.columnconfigure(2, weight=1)
        
        ttk.Button(button_frame,
                  text="💾 Simpan Survey",
                  command=self.save_survey,
                  width=15).grid(row=0, column=0, padx=2)
        
        ttk.Button(button_frame,
                  text="🔄 Reset Form",
                  command=self.reset_form,
                  width=15).grid(row=0, column=1, padx=2)
        
        ttk.Button(button_frame,
                  text="📥 Sample Data",
                  command=self.import_sample,
                  width=15).grid(row=0, column=2, padx=2)
        
        form_container.columnconfigure(1, weight=1)
        form_container.rowconfigure(len(form_fields), weight=1)
        
        # Kolom kanan
        right_frame = tk.Frame(main_container, bg='white', relief='solid', bd=1)
        right_frame.pack(side='right', fill='both', expand=True, padx=(10, 0))
        
        if self.is_admin():
            # Untuk Admin: Data Survey
            data_header = tk.Frame(right_frame, bg='#1a237e', height=40)
            data_header.pack(fill='x', side='top')
            data_header.pack_propagate(False)
            
            tk.Label(data_header,
                    text="📊 DATA SURVEY (ADMIN)",
                    font=("Arial", 12, "bold"),
                    fg="white",
                    bg='#1a237e').pack(pady=10)
            
            # Search
            search_frame = tk.Frame(right_frame, bg='white', height=50)
            search_frame.pack(fill='x', side='top', pady=(10, 0))
            search_frame.pack_propagate(False)
            
            tk.Label(search_frame,
                    text="Cari Data:",
                    font=("Arial", 10),
                    bg='white',
                    fg="#333333").pack(side='left', padx=(20, 10))
            
            self.search_var = tk.StringVar()
            search_entry = tk.Entry(search_frame,
                                   textvariable=self.search_var,
                                   font=("Arial", 10),
                                   bg='#f5f5f5',
                                   relief='sunken',
                                   bd=1,
                                   width=30)
            search_entry.pack(side='left', padx=(0, 10))
            
            ttk.Button(search_frame,
                      text="🔍 Cari",
                      command=self.refresh_list,
                      width=10).pack(side='left', padx=(0, 5))
            
            ttk.Button(search_frame,
                      text="🔄 Reset",
                      command=self.reset_search,
                      width=10).pack(side='left')
            
            # Treeview
            tree_container = tk.Frame(right_frame, bg='white')
            tree_container.pack(fill='both', expand=True, padx=20, pady=(10, 0))
            
            columns = ["ID", "Tanggal", "Nama", "Email", "Lokasi", "Quality", "Timeliness", "Service", "Overall", "Komentar"]
            
            style = ttk.Style()
            style.configure("Treeview",
                           background="white",
                           foreground="black",
                           rowheight=25,
                           fieldbackground="white")
            style.map('Treeview', background=[('selected', '#1a237e')])
            
            self.tree = ttk.Treeview(tree_container, columns=columns, show='headings', height=15)
            
            column_widths = {
                "ID": 80, "Tanggal": 150, "Nama": 120, "Email": 160,
                "Lokasi": 100, "Quality": 70, "Timeliness": 85,
                "Service": 70, "Overall": 70, "Komentar": 200
            }
            
            for col in columns:
                self.tree.heading(col, text=col)
                width = column_widths.get(col, 100)
                self.tree.column(col, width=width, minwidth=50)
            
            vsb = ttk.Scrollbar(tree_container, orient='vertical', command=self.tree.yview)
            hsb = ttk.Scrollbar(tree_container, orient='horizontal', command=self.tree.xview)
            
            self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
            
            self.tree.grid(row=0, column=0, sticky='nsew')
            vsb.grid(row=0, column=1, sticky='ns')
            hsb.grid(row=1, column=0, sticky='ew')
            
            tree_container.grid_rowconfigure(0, weight=1)
            tree_container.grid_columnconfigure(0, weight=1)
            
            self.tree.bind("<Double-1>", lambda e: self.on_row_double())
            
            # Action buttons
            action_frame = tk.Frame(right_frame, bg='white', height=60)
            action_frame.pack(fill='x', side='bottom', pady=(10, 20))
            action_frame.pack_propagate(False)
            
            action_buttons = [
                ("✏️ Edit", self.edit_selected),
                ("🗑️ Hapus", self.delete_selected),
                ("↩️ Undo", self.undo_delete),
                ("📄 Export PDF", self.export_pdf),
                ("📊 Statistik", self.show_stats),
            ]
            
            for idx, (text, command) in enumerate(action_buttons):
                btn = ttk.Button(action_frame,
                               text=text,
                               command=command,
                               width=15)
                btn.pack(side='left', padx=5)
                
        else:
            # Untuk User Biasa: Akses Terbatas
            restricted_header = tk.Frame(right_frame, bg='#ff9800', height=40)
            restricted_header.pack(fill='x', side='top')
            restricted_header.pack_propagate(False)
            
            tk.Label(restricted_header,
                    text="📛 AKSES TERBATAS",
                    font=("Arial", 12, "bold"),
                    fg="white",
                    bg='#ff9800').pack(pady=10)
            
            message_frame = tk.Frame(right_frame, bg='white')
            message_frame.pack(fill='both', expand=True, padx=40, pady=40)
            
            warning_icon = tk.Label(message_frame,
                                   text="⚠️",
                                   font=("Arial", 48),
                                   fg="#ff9800",
                                   bg='white')
            warning_icon.pack(pady=(20, 20))
            
            message_text = """
Data survey tidak dapat diakses.

Hanya admin yang dapat melihat data.

Anda dapat:
1. Mengisi form survey di sebelah kiri
2. Data yang Anda input akan disimpan
3. Hanya admin yang dapat melihat dan mengelola data

Silakan gunakan form di sebelah kiri untuk mengisi survey.
"""
            
            message_label = tk.Label(message_frame,
                                    text=message_text,
                                    font=("Arial", 11),
                                    fg="#333333",
                                    bg='white',
                                    justify='left')
            message_label.pack()
        
        # Footer
        footer_frame = tk.Frame(self.root, bg='#f0f0f0', height=40)
        footer_frame.pack(fill='x', side='bottom')
        footer_frame.pack_propagate(False)
        
        access_status = "Admin" if self.is_admin() else "User" if self.current_user['username'] != 'guest' else "Guest"
        tk.Label(footer_frame,
                text=f"{APP_TITLE} — versi {APP_VERSION} | Status: {access_status}",
                font=("Arial", 9),
                fg="#666666",
                bg='#f0f0f0').pack(side='left', padx=20, pady=10)
        
        if self.is_admin():
            self.refresh_list()

    def load_surveys(self):
        try:
            self.surveys = self.db.get_all_surveys()
        except Exception as e:
            messagebox.showerror("Error", f"Gagal memuat data: {str(e)}")
            self.surveys = []

    def is_admin(self):
        return self.current_user and int(self.current_user.get('is_admin', 0)) == 1

    def validate_form(self):
        errors = []
        if not self.form_vars['name'].get().strip():
            errors.append("Nama harus diisi")
        
        email = self.form_vars['email'].get().strip()
        if email and not valid_email(email):
            errors.append("Email tidak valid")
        
        phone = self.form_vars['phone'].get().strip()
        if phone and not valid_phone(phone):
            errors.append("Nomor telepon tidak valid")
        
        for field in ['quality', 'timeliness', 'service', 'overall']:
            try:
                value = int(self.form_vars[field].get() or 0)
                if field == 'overall':
                    if value < 1 or value > 10:
                        errors.append("Nilai kepuasan harus 1 - 10")
                else:
                    if value < 1 or value > 5:
                        errors.append(f"Nilai {field} harus 1 - 5")
            except ValueError:
                errors.append(f"Nilai {field} tidak valid")
        
        return errors

    def get_form_payload(self):
        return {
            'id': gen_id(),
            'timestamp': now_ts(),
            'customer_name': self.form_vars['name'].get().strip(),
            'customer_email': self.form_vars['email'].get().strip(),
            'customer_phone': self.form_vars['phone'].get().strip(),
            'customer_gender': '',
            'customer_location': self.form_vars['location'].get().strip(),
            'quality': int(self.form_vars['quality'].get() or 0),
            'timeliness': int(self.form_vars['timeliness'].get() or 0),
            'service': int(self.form_vars['service'].get() or 0),
            'overall': int(self.form_vars['overall'].get() or 0),
            'comments': self.comments.get('1.0', 'end').strip(),
            'owner_username': self.current_user['username'] if self.current_user else ''
        }

    def save_survey(self):
        errors = self.validate_form()
        if errors:
            messagebox.showerror("Validasi Error", "\n".join(errors))
            return

        payload = self.get_form_payload()

        if self.editing_id:
            if not self.is_admin():
                messagebox.showerror("Error", "Hanya admin yang dapat mengedit data")
                return
            payload['timestamp'] = now_ts()
            if self.db.update_survey(self.editing_id, payload):
                messagebox.showinfo("Sukses", "Data berhasil diperbarui")
                self.editing_id = None
                self.load_surveys()
                self.refresh_list()
                self.reset_form()
            else:
                messagebox.showerror("Error", "Gagal memperbarui data")
            return

        if self.db.save_survey(payload):
            messagebox.showinfo("Sukses", "Survey berhasil disimpan")
            self.load_surveys()
            if self.is_admin():
                self.refresh_list()
            self.reset_form()
        else:
            messagebox.showerror("Error", "Gagal menyimpan survey")

    def reset_form(self):
        for key in self.form_vars:
            if isinstance(self.form_vars[key], tk.StringVar):
                self.form_vars[key].set('')
            else:
                self.form_vars[key].set(3 if key != 'overall' else 5)
        if hasattr(self, 'comments'):
            self.comments.delete('1.0', 'end')
        self.editing_id = None

    def import_sample(self):
        import random
        names = ["Sahrini", "Prabu Roro", "Agus Kopling"]
        locations = ["Jonggol", "Benowoo", "Bandung", "Madiunn", "Pati"]
        idx = random.randint(0, len(names) - 1)
        
        self.form_vars['name'].set(names[idx])
        self.form_vars['email'].set(f"{names[idx].split()[0].lower()}@gmail.com")
        self.form_vars['phone'].set("08123456789")
        self.form_vars['location'].set(locations[idx])
        self.form_vars['quality'].set(random.randint(1, 5))
        self.form_vars['timeliness'].set(random.randint(1, 5))
        self.form_vars['service'].set(random.randint(1, 5))
        self.form_vars['overall'].set(random.randint(1, 10))
        
        if hasattr(self, 'comments'):
            self.comments.delete('1.0', 'end')
            self.comments.insert('1.0', "Pelayanan sangat memuaskan, akan saya nikmati sendiri aja.")

    def refresh_list(self):
        if not hasattr(self, 'tree'): return
        
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        search_term = self.search_var.get().strip().lower()
        filtered = []
        
        if self.is_admin():
            for survey in self.surveys:
                match = True
                if search_term:
                    fields = [
                        survey.get('customer_name', '').lower(),
                        survey.get('customer_email', '').lower(),
                        survey.get('customer_location', '').lower(),
                        survey.get('comments', '').lower()
                    ]
                    if not any(search_term in field for field in fields):
                        match = False
                if match:
                    filtered.append(survey)
        
        for survey in filtered:
            comment = (survey.get('comments', '') or '')[:100]
            if len(survey.get('comments', '')) > 100:
                comment += "..."
            
            values = (
                survey.get('id', '')[:8],
                survey.get('timestamp', '')[:19],
                survey.get('customer_name', ''),
                survey.get('customer_email', '') or '',
                survey.get('customer_location', '') or '',
                survey.get('quality') or 0,
                survey.get('timeliness') or 0,
                survey.get('service') or 0,
                survey.get('overall') or 0,
                comment
            )
            self.tree.insert('', 'end', values=values, tags=(survey.get('id', ''),))

    def reset_search(self):
        if hasattr(self, 'search_var'):
            self.search_var.set('')
        self.refresh_list()

    def on_row_double(self):
        self.edit_selected()

    def edit_selected(self):
        if not self.is_admin():
            messagebox.showerror("Error", "Hanya admin yang dapat mengedit data")
            return
        
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("Info", "Pilih data yang akan diedit")
            return
        
        item_id = self.tree.item(selection[0])['tags'][0]
        survey = next((s for s in self.surveys if s['id'] == item_id), None)
        
        if not survey:
            messagebox.showerror("Error", "Data tidak ditemukan")
            return
        
        self.form_vars['name'].set(survey.get('customer_name', ''))
        self.form_vars['email'].set(survey.get('customer_email', ''))
        self.form_vars['phone'].set(survey.get('customer_phone', ''))
        self.form_vars['location'].set(survey.get('customer_location', ''))
        self.form_vars['quality'].set(survey.get('quality', 3))
        self.form_vars['timeliness'].set(survey.get('timeliness', 3))
        self.form_vars['service'].set(survey.get('service', 3))
        self.form_vars['overall'].set(survey.get('overall', 5))
        
        if hasattr(self, 'comments'):
            self.comments.delete('1.0', 'end')
            self.comments.insert('1.0', survey.get('comments', ''))
        
        self.editing_id = survey['id']
        messagebox.showinfo("Edit Mode", "Data dimuat ke form. Ubah lalu klik Simpan Survey.")

    def delete_selected(self):
        if not self.is_admin():
            messagebox.showerror("Error", "Hanya admin yang dapat menghapus data")
            return
        
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("Info", "Pilih data yang akan dihapus")
            return
        
        item_id = self.tree.item(selection[0])['tags'][0]
        survey = next((s for s in self.surveys if s['id'] == item_id), None)
        
        if not survey:
            messagebox.showerror("Error", "Data tidak ditemukan")
            return
        
        if not messagebox.askyesno("Konfirmasi", "Apakah Anda yakin ingin menghapus data ini?"):
            return
        
        if self.db.delete_survey(item_id):
            self.deleted.append(survey)
            messagebox.showinfo("Sukses", "Data berhasil dihapus")
            self.load_surveys()
            self.refresh_list()
        else:
            messagebox.showerror("Error", "Gagal menghapus data")

    def undo_delete(self):
        if not self.deleted:
            messagebox.showinfo("Info", "Tidak ada data yang bisa di-undo")
            return
        
        survey = self.deleted.pop()
        try:
            if self.db.save_survey(survey):
                messagebox.showinfo("Sukses", "Data berhasil dikembalikan")
                self.load_surveys()
                self.refresh_list()
            else:
                messagebox.showerror("Error", "Gagal mengembalikan data")
        except Exception as e:
            messagebox.showerror("Error", f"Gagal mengembalikan: {str(e)}")

    def export_pdf(self):
        if not self.is_admin():
            messagebox.showerror("Error", "Hanya admin yang dapat mengekspor data")
            return
        
        if not self.surveys:
            messagebox.showwarning("Peringatan", "Tidak ada data untuk diekspor")
            return
        
        filename = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF Files", "*.pdf"), ("All Files", "*.*")],
            title="Simpan sebagai PDF"
        )
        
        if not filename: return
        
        try:
            footer_info = {'user': self.current_user['full_name'], 'total_records': len(self.surveys)}
            success, error = make_pdf_reportlab(filename, self.surveys, footer_info=footer_info)
            
            if success:
                total_surveys = min(50, len(self.surveys))
                surveys_per_page = 4
                total_pages = ((total_surveys + surveys_per_page - 1) // surveys_per_page) + 1
                
                if messagebox.askyesno("✅ PDF Berhasil Dibuat", 
                    f"Laporan PDF berhasil dibuat!\n\nTotal Responden: {len(self.surveys)}\nTotal Halaman: {total_pages}\n\nApakah Anda ingin membuka file PDF?"):
                    try:
                        import platform, subprocess
                        system = platform.system()
                        if system == 'Windows': 
                            os.startfile(filename)
                        elif system == 'Darwin': 
                            subprocess.run(['open', filename])
                        else: 
                            subprocess.run(['xdg-open', filename])
                    except: 
                        pass
            else:
                messagebox.showerror("❌ Gagal Membuat PDF", f"Terjadi kesalahan:\n\n{error}")
        except Exception as e:
            messagebox.showerror("❌ Error", f"Terjadi kesalahan tidak terduga:\n\n{str(e)}")

    def show_stats(self):
        if not self.is_admin():
            messagebox.showerror("Error", "Hanya admin yang dapat melihat statistik")
            return
        
        if not self.surveys:
            messagebox.showinfo("Statistik", "Belum ada data survey")
            return
        
        # Hitung statistik dasar
        total = len(self.surveys)
        avg_quality = sum(s.get('quality', 0) for s in self.surveys) / total
        avg_timeliness = sum(s.get('timeliness', 0) for s in self.surveys) / total
        avg_service = sum(s.get('service', 0) for s in self.surveys) / total
        avg_overall = sum(s.get('overall', 0) for s in self.surveys) / total
        
        # Hitung distribusi lokasi (ambil 10 lokasi terbanyak)
        locations = {}
        for survey in self.surveys:
            loc = survey.get('customer_location', 'Tidak diketahui').strip()
            if not loc:
                loc = 'Tidak diketahui'
            locations[loc] = locations.get(loc, 0) + 1
        
        # Urutkan berdasarkan jumlah (descending)
        sorted_locations = sorted(locations.items(), key=lambda x: x[1], reverse=True)
        top_locations = sorted_locations[:10]
        
        # Buat window statistik baru
        stats_window = tk.Toplevel(self.root)
        stats_window.title("📈 Statistik Survey dengan Chart")
        stats_window.geometry("1000x700")
        
        # Posisikan di tengah layar
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (1000 // 2)
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (700 // 2)
        stats_window.geometry(f"1000x700+{x}+{y}")
        
        # Frame utama untuk mengatur tata letak
        main_frame = tk.Frame(stats_window)
        main_frame.pack(fill='both', expand=True, padx=10, pady=10)
        
        # Frame untuk tombol di bagian atas (ditengah)
        button_frame = tk.Frame(main_frame)
        button_frame.pack(fill='x', pady=(0, 20))
        
        # Tengahkan tombol-tombol
        button_container = tk.Frame(button_frame)
        button_container.pack(expand=True)
        
        # Hanya menyisakan tombol Tutup
        ttk.Button(button_container, text="Tutup", 
                command=stats_window.destroy).pack(side='left', padx=5)
        
        # Notebook untuk tab berbeda
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill='both', expand=True)
        
        # Tab 1: Ringkasan Statistik (DITENGAHKAN)
        summary_tab = ttk.Frame(notebook)
        notebook.add(summary_tab, text="📊 Ringkasan")
        
        # Buat frame container untuk menengahkan konten
        summary_container = tk.Frame(summary_tab, bg='white')
        summary_container.pack(fill='both', expand=True)
        
        # Frame untuk menengahkan konten ringkasan
        center_frame = tk.Frame(summary_container, bg='white')
        center_frame.place(relx=0.5, rely=0.5, anchor="center")
        
        # Ringkasan teks (diformat dengan better alignment)
        summary_text = f"""
        {'='*50}
        📊 STATISTIK SURVEY KEPUASAN
        {'='*50}
        
        {'INFORMASI UMUM:':<30}
        • Total Survey   : {total:>4}
        • Periode Data   : {self.surveys[-1].get('timestamp', '')[:10] if self.surveys else 'N/A':>10} hingga {self.surveys[0].get('timestamp', '')[:10] if self.surveys else 'N/A':>10}
        
        {'RATA-RATA PENILAIAN:':<30}
        • Kualitas       : {avg_quality:>6.2f}/5    ({avg_quality/5*100:>6.1f}%)
        • Ketepatan      : {avg_timeliness:>6.2f}/5    ({avg_timeliness/5*100:>6.1f}%)
        • Layanan        : {avg_service:>6.2f}/5    ({avg_service/5*100:>6.1f}%)
        • Kepuasan       : {avg_overall:>6.2f}/10   ({avg_overall/10*100:>6.1f}%)
        
        {'-'*50}
        {'DISTRIBUSI LOKASI (TOP 5):':<30}
        """
        
        for loc, count in sorted_locations[:5]:
            percentage = (count / total) * 100
            loc_display = loc[:25] + "..." if len(loc) > 25 else loc
            summary_text += f"• {loc_display:<25} : {count:>3} ({percentage:>5.1f}%)\n"
        
        if len(sorted_locations) > 5:
            other_count = total - sum(count for _, count in sorted_locations[:5])
            other_percentage = (other_count / total) * 100
            summary_text += f"• {'Lain-lain':<25} : {other_count:>3} ({other_percentage:>5.1f}%)\n"
        
        summary_text += f"{'='*50}"
        
        # Buat label dengan font monospace untuk alignment yang baik
        summary_label = tk.Label(center_frame, text=summary_text, font=("Courier", 10), 
                                justify='left', bg='white', padx=20, pady=20)
        summary_label.pack()
        
        # Tab 2: Chart Rata-rata Penilaian
        ratings_tab = ttk.Frame(notebook)
        notebook.add(ratings_tab, text="📈 Rata-rata Penilaian")
        
        # Container untuk menengahkan chart
        chart1_container = tk.Frame(ratings_tab)
        chart1_container.pack(fill='both', expand=True)
        
        # Buat figure untuk chart rata-rata penilaian
        fig1 = Figure(figsize=(8, 5), dpi=100)
        ax1 = fig1.add_subplot(111)
        
        categories = ['Kualitas', 'Ketepatan', 'Layanan', 'Kepuasan']
        values = [avg_quality, avg_timeliness, avg_service, avg_overall]
        max_values = [5, 5, 5, 10]
        percentages = [(v/max_val)*100 for v, max_val in zip(values, max_values)]
        
        colors = ['#4CAF50', '#2196F3', '#FF9800', '#9C27B0']
        
        # Buat bar chart
        bars = ax1.bar(categories, values, color=colors, alpha=0.8)
        
        for bar, value, percentage in zip(bars, values, percentages):
            height = bar.get_height()
            ax1.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                    f'{value:.2f}\n({percentage:.1f}%)',
                    ha='center', va='bottom', fontsize=9)
        
        ax1.set_ylabel('Nilai Rata-rata', fontweight='bold')
        ax1.set_title('RATA-RATA PENILAIAN SURVEY', fontweight='bold', pad=20)
        ax1.set_ylim(0, max(max_values) * 1.2)
        ax1.grid(True, alpha=0.3, linestyle='--')
        
        for i, max_val in enumerate(max_values):
            ax1.axhline(y=max_val, xmin=i/len(categories), xmax=(i+1)/len(categories), 
                    color='red', linestyle=':', alpha=0.5, linewidth=1)
        
        ax1.text(0.02, 0.98, f'Total Survey: {total}', transform=ax1.transAxes,
                fontsize=9, verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
        
        fig1.tight_layout()
        
        canvas1 = FigureCanvasTkAgg(fig1, master=chart1_container)
        canvas1.draw()
        canvas1.get_tk_widget().pack(expand=True)
        
        toolbar1 = NavigationToolbar2Tk(canvas1, chart1_container)
        toolbar1.update()
        toolbar1.pack(side='bottom', fill='x')
        
        # Tab 3: Chart Distribusi Lokasi
        locations_tab = ttk.Frame(notebook)
        notebook.add(locations_tab, text="🗺️ Distribusi Lokasi")
        
        # Container untuk menengahkan chart
        chart2_container = tk.Frame(locations_tab)
        chart2_container.pack(fill='both', expand=True)
        
        fig2 = Figure(figsize=(9, 6), dpi=100)
        ax2 = fig2.add_subplot(111)
        
        if top_locations:
            loc_names = [loc[:20] + '...' if len(loc) > 20 else loc for loc, _ in top_locations]
            loc_counts = [count for _, count in top_locations]
            
            cmap = plt.cm.Blues
            colors2 = [cmap(i/len(loc_names)) for i in range(len(loc_names))]
            
            bars2 = ax2.barh(loc_names, loc_counts, color=colors2, alpha=0.8)
            
            for bar, count in zip(bars2, loc_counts):
                width = bar.get_width()
                ax2.text(width + max(loc_counts)*0.01, bar.get_y() + bar.get_height()/2,
                        f'{count} ({(count/total*100):.1f}%)',
                        va='center', fontsize=9)
            
            ax2.set_xlabel('Jumlah Responden', fontweight='bold')
            ax2.set_title('DISTRIBUSI RESPONDEN BERDASARKAN LOKASI', fontweight='bold', pad=20)
            ax2.grid(True, alpha=0.3, axis='x', linestyle='--')
            
            other_count = total - sum(loc_counts)
            if other_count > 0:
                ax2.text(0.98, 0.02, f'Lainnya: {other_count} responden',
                        transform=ax2.transAxes, fontsize=9,
                        horizontalalignment='right',
                        bbox=dict(boxstyle='round', facecolor='lightgray', alpha=0.7))
        else:
            ax2.text(0.5, 0.5, 'Tidak ada data lokasi',
                    horizontalalignment='center', verticalalignment='center',
                    transform=ax2.transAxes, fontsize=12)
        
        fig2.tight_layout()
        
        # Embed chart ke Tkinter
        canvas2 = FigureCanvasTkAgg(fig2, master=chart2_container)
        canvas2.draw()
        canvas2.get_tk_widget().pack(expand=True)
        
        # Toolbar untuk interaksi
        toolbar2 = NavigationToolbar2Tk(canvas2, chart2_container)
        toolbar2.update()
        toolbar2.pack(side='bottom', fill='x')

    def open_admin_dashboard(self):
        if not self.is_admin():
            messagebox.showerror("Error", "Hanya admin yang dapat membuka dashboard")
            return
        
        dashboard = tk.Toplevel(self.root)
        dashboard.title("Dashboard Admin")
        dashboard.geometry("700x500")
        
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (700 // 2)
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (500 // 2)
        dashboard.geometry(f"700x500+{x}+{y}")
        
        notebook = ttk.Notebook(dashboard)
        notebook.pack(fill='both', expand=True, padx=10, pady=10)
        
        users_tab = ttk.Frame(notebook)
        notebook.add(users_tab, text="👥 Users")
        
        users = self.db.get_all_users()
        tree = ttk.Treeview(users_tab, columns=["ID", "Username", "Nama", "Admin"], show='headings', height=15)
        for col in ["ID", "Username", "Nama", "Admin"]:
            tree.heading(col, text=col)
            tree.column(col, width=100)
        
        for user in users:
            tree.insert('', 'end', values=(user['id'], user['username'], user['full_name'], 
            "Ya" if user['is_admin'] else "Tidak"))
        
        tree.pack(fill='both', expand=True, padx=10, pady=10)

    def logout(self):
        if messagebox.askyesno("Konfirmasi", "Apakah Anda yakin ingin logout?"):
            self.current_user = None
            self.show_login_page()

def main():
    root = tk.Tk()
    try:
        root.iconbitmap('icon.ico')
    except:
        pass
    
    root.withdraw()
    root.update_idletasks()
    app = SurveyApp(root)
    root.deiconify()
    root.mainloop()

if __name__ == '__main__':
    main() 