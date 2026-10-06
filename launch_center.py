"""Центр управления космическими пусками — desktop-приложение (Python 3, tkinter + SQLite)."""
import sqlite3, hashlib, csv, random, tkinter as tk
from tkinter import ttk, messagebox as mb, filedialog
from datetime import datetime, timedelta

db = sqlite3.connect("launch_center.db")
db.execute("PRAGMA foreign_keys=ON")
def q(sql, a=()):
    r = db.execute(sql, a).fetchall(); db.commit(); return r
def pairs(sql): return q(sql)
now = lambda: datetime.now().strftime("%Y-%m-%d %H:%M")
def pt(s):
    try: return datetime.strptime(s, "%Y-%m-%d %H:%M")
    except (ValueError, TypeError): return None
def pd_(s):
    try: return datetime.strptime(s, "%Y-%m-%d")
    except (ValueError, TypeError): return None

STAGES = ["Доставка и сборка на техническом комплексе", "Транспортировка на стартовый комплекс",
          "Заправка компонентами топлива", "Предстартовый контроль систем"]
STAGE_ICON = ["🚚", "🔧", "⛽", "🛰"]           # значок для каждого из 4 этапов подготовки, в том же порядке, что и STAGES
COL = {"ok": "#1e7b3a", "cur": "#1f5fa8", "wait": "#c9d0da", "bad": "#b3261e", "warn": "#b26a00"}  # цвет узла схемы по состоянию
NEXT = {"запланирован": "подготовка", "подготовка": "готов", "готов": "выполнен", "перенесен": "запланирован"}
PERM = {"Руководитель": {"postpone", "pad", "report", "weather"}, "Диспетчер": {"launch", "stage", "incident", "weather"},
        "Техник по топливу": {"fuel"}, "Аналитик": {"report"}, "Инспектор безопасности": {"report"}}
ROLE = [""]

db.executescript("""
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, fio TEXT, login TEXT UNIQUE, pwd TEXT, role TEXT);
CREATE TABLE IF NOT EXISTS rockets(id INTEGER PRIMARY KEY, type TEXT, specs TEXT);
CREATE TABLE IF NOT EXISTS payloads(id INTEGER PRIMARY KEY, type TEXT, mass REAL, orbit TEXT);
CREATE TABLE IF NOT EXISTS pads(id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE IF NOT EXISTS maintenance(id INTEGER PRIMARY KEY, pad_id INT REFERENCES pads, d1 TEXT, d2 TEXT, kind TEXT);
CREATE TABLE IF NOT EXISTS launches(id INTEGER PRIMARY KEY, rocket_id INT REFERENCES rockets, payload_id INT REFERENCES payloads,
  orbit TEXT NOT NULL, pad_id INT REFERENCES pads, start_time TEXT NOT NULL, status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS stages(id INTEGER PRIMARY KEY, launch_id INT REFERENCES launches, name TEXT, status TEXT, dt TEXT);
CREATE TABLE IF NOT EXISTS batches(id INTEGER PRIMARY KEY, fuel TEXT, volume REAL, remaining REAL, expiry TEXT);
CREATE TABLE IF NOT EXISTS usage(id INTEGER PRIMARY KEY, batch_id INT REFERENCES batches, launch_id INT REFERENCES launches, volume REAL, dt TEXT);
CREATE TABLE IF NOT EXISTS incidents(id INTEGER PRIMARY KEY, launch_id INT REFERENCES launches, channel TEXT, time TEXT, descr TEXT, measures TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS postponements(id INTEGER PRIMARY KEY, launch_id INT REFERENCES launches, reason TEXT, new_date TEXT, dt TEXT);
CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY, role TEXT, txt TEXT, dt TEXT, seen INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY, fio TEXT, role TEXT, action TEXT, dt TEXT);
CREATE TABLE IF NOT EXISTS weather_checks(id INTEGER PRIMARY KEY, launch_id INT REFERENCES launches, source TEXT,
  checked_at TEXT, wind REAL, temp REAL, storm INT, exceeded INT, details TEXT);
""")
if not q("SELECT 1 FROM users"):
    for fio, lg, role in [("Иванов И.И.", "admin", "Руководитель"), ("Петров П.П.", "disp", "Диспетчер"),
                          ("Сидоров С.С.", "fuel", "Техник по топливу"), ("Орлова О.О.", "an", "Аналитик"),
                          ("Кузнецов К.К.", "insp", "Инспектор безопасности")]:
        q("INSERT INTO users(fio,login,pwd,role) VALUES(?,?,?,?)", (fio, lg, hashlib.sha256(lg.encode()).hexdigest(), role))
    for t in ["Союз-2.1а", "Ангара-А5", "Протон-М"]: q("INSERT INTO rockets(type,specs) VALUES(?,'')", (t,))
    for t, m, o in [("Спутник связи", 3200, "ГСО"), ("Метеоспутник", 1500, "ССО"), ("Грузовой корабль", 7000, "НОО")]:
        q("INSERT INTO payloads(type,mass,orbit) VALUES(?,?,?)", (t, m, o))
    for n in ["Площадка 31", "Площадка 1С", "Площадка 81"]: q("INSERT INTO pads(name) VALUES(?)", (n,))

RUK, DSP, FUEL, AN, INSP = "Руководитель", "Диспетчер", "Техник по топливу", "Аналитик", "Инспектор безопасности"

# ---------- Метеорологическая служба космодрома ----------
# Предельные значения (в реальной системе — нормативный документ; здесь заданы константами).
WIND_LIMIT = 15.0          # предельная скорость ветра на высоте, м/с
TEMP_MIN, TEMP_MAX = -30.0, 45.0  # допустимый диапазон температуры, °C

def weather_exceeded(wind, temp, storm):
    """Единый критерий превышения предельных значений — одинаковый и для автоматического запроса,
    и для ручного ввода метеорологом: сравнение с одними и теми же порогами, источник данных на
    сам критерий не влияет (см. пояснение в чате: это решение принято явно, так как в задании
    критерий для ручного ввода не был определён)."""
    reasons = []
    if wind > WIND_LIMIT: reasons.append(f"ветер {wind:g} м/с превышает предел {WIND_LIMIT:g} м/с")
    if not (TEMP_MIN <= temp <= TEMP_MAX): reasons.append(f"температура {temp:g}°C вне диапазона [{TEMP_MIN:g}; {TEMP_MAX:g}]°C")
    if storm: reasons.append("зафиксирована грозовая активность")
    return bool(reasons), reasons

def fetch_external_weather(launch_id):
    """
    Запрос прогноза погоды по высотам к внешней метеорологической службе космодрома.
    Точка интеграции с реальным API — здесь имитируется HTTP-запрос и его возможная недоступность
    (сеть, таймаут, служба не отвечает), чтобы показать оба сценария из задания:
      - служба доступна  -> возвращает (ветер, температура, признак грозы);
      - служба недоступна -> возвращает None, и далее требуется ручной ввод метеорологом.
    """
    try:
        if random.random() < 0.25:  # ~25% случаев — служба недоступна (для демонстрации сценария)
            return None
        return (round(random.uniform(2, 22), 1), round(random.uniform(-25, 35), 1), random.random() < 0.15)
    except Exception:
        return None

def record_weather(launch_id, wind, temp, storm, source):
    """Сохраняет результат метеопроверки (source: 'авто' | 'ручной') и, при превышении
    предельных значений, формирует предупреждение о возможном переносе пуска."""
    exceeded, reasons = weather_exceeded(wind, temp, storm)
    q("INSERT INTO weather_checks(launch_id,source,checked_at,wind,temp,storm,exceeded,details) VALUES(?,?,?,?,?,?,?,?)",
      (launch_id, source, now(), wind, temp, int(storm), int(exceeded), "; ".join(reasons)))
    if exceeded:
        notify((RUK, DSP), f"Пуск {ln(launch_id)}: метеослужба ({source}) сообщает превышение предельных значений — "
                            f"{', '.join(reasons)}. Рекомендуется рассмотреть перенос пуска («Перенести»).")
    return exceeded, reasons
def notify(roles, txt):
    for r in ([roles] if isinstance(roles, str) else roles):
        q("INSERT INTO notes(role,txt,dt,seen) VALUES(?,?,?,0)", (r, txt, now()))
def ln(i):
    r = q("SELECT l.id,r.type,l.start_time FROM launches l JOIN rockets r ON r.id=l.rocket_id WHERE l.id=?", (i,))[0]
    return f"№{r[0]} ({r[1]}, старт {r[2]})"
ADV = {  # уведомления при смене статуса пуска
 "подготовка": [(FUEL, "переведён в подготовку. Далее: спишите топливо (Топливо → Списать на пуск) до этапа заправки."),
                (DSP, "переведён в подготовку, этапы созданы. Далее: последовательно завершайте 4 этапа («Завершить этап»).")],
 "готов": [(RUK, "готов к пуску. Далее: проверьте метеоусловия; при превышении предельных значений перенесите пуск («Перенести»)."),
           (DSP, "готов к пуску. Далее: проведите пуск, следите за телеметрией; при потере сигнала зафиксируйте нештатную ситуацию; после пуска переведите в «выполнен».")],
 "выполнен": [((RUK, AN), "выполнен. Далее: сформируйте отчёты за период (вкладка «Отчёты»).")],
 "запланирован": [(FUEL, "возвращён в план после переноса. Далее: проверьте срок годности партий на новую дату.")]}
STAGE_NOTE = [  # уведомления после завершения каждого этапа
 (DSP, "этап 1/4 «Доставка и сборка» выполнен. Далее: транспортировка на стартовый комплекс."),
 (FUEL, "этап 2/4 «Транспортировка» выполнен. Далее — заправка: спишите топливо на пуск (Топливо → Списать на пуск)."),
 (DSP, "этап 3/4 «Заправка» выполнен. Далее: предстартовый контроль систем."),
 ((DSP, RUK), "этап 4/4 «Предстартовый контроль» выполнен. Далее: переведите пуск в «готов» («Следующий статус»).")]
QUEUE, SHOW = [], [False]
def pump():
    if SHOW[0] or not QUEUE: return
    SHOW[0] = True; w = tk.Toplevel(root); w.overrideredirect(True); w.attributes("-topmost", True); w.configure(bg=DARK)
    tk.Label(w, text="🔔 Уведомление", bg=DARK, fg="#9fd0ff", font=("Segoe UI", 9, "bold"), anchor="w").pack(fill="x", padx=14, pady=(10, 0))
    tk.Label(w, text=QUEUE.pop(0), bg=DARK, fg="white", font=F, wraplength=360, justify="left", anchor="w").pack(fill="x", padx=14, pady=(3, 12))
    w.update_idletasks()
    w.geometry(f"+{root.winfo_rootx() + root.winfo_width() - w.winfo_width() - 24}+{root.winfo_rooty() + root.winfo_height() - w.winfo_height() - 60}")
    def close(_=None):
        if w.winfo_exists(): w.destroy(); SHOW[0] = False; pump()
    for x in (w, *w.winfo_children()): x.bind("<Button-1>", close)
    w.after(9000, close); root.bell()

root = tk.Tk(); root.geometry("1150x720"); root.minsize(950, 600)
BG, ACC, DARK = "#eef2f7", "#2f6690", "#1f3b57"
TAGS = {"выполнен": "ok", "закрыта": "ok", "годна": "ok", "свободна": "ok", "отменен": "bad", "просрочена": "bad",
        "на обслуживании": "bad", "перенесен": "warn", "открыта": "warn", "занята": "warn",
        "подготовка": "info", "в работе": "info", "готов": "info"}
sty = ttk.Style(); sty.theme_use("clam"); root.configure(bg=BG); F = ("Segoe UI", 10)
sty.configure(".", background=BG, font=F, foreground="#22303f")
sty.configure("Treeview", rowheight=28, background="white", fieldbackground="white", borderwidth=0, font=F)
sty.configure("Treeview.Heading", background=ACC, foreground="white", font=("Segoe UI", 10, "bold"), padding=7, relief="flat")
sty.map("Treeview.Heading", background=[("active", DARK)])
sty.map("Treeview", background=[("selected", "#cfe3f5")], foreground=[("selected", "#111")])
sty.configure("TButton", padding=(12, 7), background=ACC, foreground="white", borderwidth=0, focusthickness=0)
sty.map("TButton", background=[("disabled", "#c9d0da"), ("active", DARK)], foreground=[("disabled", "#8b95a3")])
sty.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 4, 0, 0))
sty.configure("TNotebook.Tab", padding=(18, 9), font=("Segoe UI", 10, "bold"), background="#d9e1ec", foreground="#4a5a6d")
sty.map("TNotebook.Tab", background=[("selected", "white")], foreground=[("selected", ACC)])
sty.configure("TCombobox", padding=4); sty.configure("TEntry", padding=4)
sty.configure("Card.TFrame", background="white", relief="solid", borderwidth=1)
sty.configure("Card.TLabel", background="white")
sty.configure("Status.TLabel", background=DARK, foreground="white", padding=(10, 5))

def fmt(digits, mask):
    out, i = "", 0
    for ch in mask:
        if i >= len(digits): break
        if ch == "d": out += digits[i]; i += 1
        else: out += ch
    return out

class MaskEntry(ttk.Entry):
    """Поле с маской: вводятся только цифры, разделители подставляются сами."""
    def __init__(s, p, mask, **kw):
        super().__init__(p, **kw); s.mask, s.n = mask, mask.count("d")
        s.bind("<KeyRelease>", s.fix); s.bind("<<Paste>>", lambda e: s.after(1, s.fix))
    def fix(s, e=None):
        if e is not None and e.keysym in ("Tab", "ISO_Left_Tab", "Left", "Right", "Home", "End", "Shift_L", "Shift_R"): return
        d = "".join(c for c in s.get() if c.isdigit())[:s.n]
        s.delete(0, "end"); s.insert(0, fmt(d, s.mask)); s.icursor("end")

def form(title, fields):
    """fields: (key, label, options[(id,label)] | None, default) -> dict | None"""
    w = tk.Toplevel(root); w.title(title); w.grab_set(); ent, out = {}, []
    for i, (k, lbl, opts, d) in enumerate(fields):
        ttk.Label(w, text=lbl).grid(row=i, column=0, sticky="w", padx=6, pady=3)
        mk = "dddd-dd-dd dd:dd" if "ЧЧ:ММ" in lbl else "dddd-dd-dd" if "ГГГГ" in lbl else None
        if opts is not None: e = ttk.Combobox(w, values=[o[1] for o in opts], state="readonly", width=38)
        else:
            e = MaskEntry(w, mk, width=40) if mk else ttk.Entry(w, width=40); e.insert(0, d)
        e.grid(row=i, column=1, padx=6, pady=3); ent[k] = (e, opts)
    def ok():
        out.append({k: ({l: i for i, l in o}[e.get()] if o is not None and e.get() else e.get().strip()) for k, (e, o) in ent.items()})
        w.destroy()
    ttk.Button(w, text="OK", command=ok).grid(row=len(fields), column=1, sticky="e", padx=6, pady=6)
    root.wait_window(w); return out[0] if out else None

class Grid(ttk.Frame):
    def __init__(s, p, cols, sql, args=()):
        super().__init__(p); s.sql, s.args = sql, args
        s.t = ttk.Treeview(s, columns=cols, show="headings", height=7)
        for c in cols: s.t.heading(c, text=c); s.t.column(c, width=60 if c == "№" else 130)
        sb = ttk.Scrollbar(s, command=s.t.yview); s.t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y"); s.t.pack(side="left", fill="both", expand=True)
        s.t.tag_configure("odd", background="#f3f6fa")
        for k, c in {"ok": "#1e7b3a", "bad": "#b3261e", "warn": "#b26a00", "info": "#1f5fa8"}.items(): s.t.tag_configure(k, foreground=c)
        s.load()
    def load(s):
        s.t.delete(*s.t.get_children())
        for i, r in enumerate(q(s.sql, s.args() if callable(s.args) else s.args)):
            tg = (["odd"] if i % 2 else []) + [TAGS[v] for v in r if v in TAGS][:1]
            s.t.insert("", "end", values=r, tags=tg)
    def sel(s):
        i = s.t.selection(); return s.t.item(i[0])["values"] if i else None

def sid(g): return (g.sel() or [0])[0]
def err(m): mb.showerror("Ошибка", m)

class Diagram(tk.Canvas):
    """
    Наглядная схема пуска: узлы «Регистрация → 4 этапа подготовки → Пуск», соединённые стрелками.
    Цвет и значок узла меняются автоматически по данным из БД:
      серый  = ожидает, синий = текущий шаг, зелёный = выполнен, оранжевый = перенесен, красный = отменен.
    Если по пуску есть открытая нештатная ситуация, текущий узел подменяется значком ⚠
    и мигает красным/оранжевым (тикает раз в 600 мс). Клик по схеме показывает описание инцидента.
    """
    R = 28  # радиус кружка-узла в пикселях

    def __init__(s, p):
        super().__init__(p, height=170, bg="white", highlightthickness=1, highlightbackground="#d9e1ec")
        s.launch_id, s.blink = None, False
        s.bind("<Button-1>", s.click)
        s.tick()

    def show(s, launch_id):
        s.launch_id = launch_id; s.draw()

    def tick(s):
        # раз в 600 мс переключаем фазу мигания и перерисовываем, если схема кому-то показана
        if not s.winfo_exists(): return
        s.blink = not s.blink
        if s.launch_id: s.draw()
        s.after(600, s.tick)

    def click(s, e):
        if not s.launch_id: return
        i = q("SELECT descr,measures,status FROM incidents WHERE launch_id=? AND status!='закрыта' ORDER BY id DESC LIMIT 1", (s.launch_id,))
        if i: mb.showwarning("Нештатная ситуация", f"{i[0][0]}\n\nПринятые меры: {i[0][1] or '—'}\nСтатус: {i[0][2]}")

    def draw(s):
        s.delete("all")
        if not s.launch_id:
            s.create_text(16, 82, anchor="w", fill="#9aa5b1", font=("Segoe UI", 10),
                           text="Выберите пуск в таблице выше — здесь появится схема этапов"); return
        row = q("SELECT status FROM launches WHERE id=?", (s.launch_id,))
        if not row: s.launch_id = None; return
        lstatus = row[0][0]
        stage_rows = q("SELECT status FROM stages WHERE launch_id=? ORDER BY id", (s.launch_id,))
        has_incident = bool(q("SELECT 1 FROM incidents WHERE launch_id=? AND status!='закрыта'", (s.launch_id,)))

        # собираем узлы: регистрация -> 4 этапа -> сам пуск
        nodes = [("📝", "Регистрация", "ok")]
        cur_assigned = lstatus != "подготовка"  # текущий этап помечаем только пока идёт подготовка
        for i in range(4):
            st = stage_rows[i][0] if i < len(stage_rows) else None
            if st == "выполнен": kind = "ok"
            elif not cur_assigned: kind = "cur"; cur_assigned = True
            else: kind = "wait"
            nodes.append((STAGE_ICON[i], f"Этап {i+1}", kind))
        nodes.append(("🔥", "Пуск", {"выполнен": "ok", "отменен": "bad", "перенесен": "warn", "готов": "cur"}.get(lstatus, "wait")))

        if has_incident:  # подменяем текущий узел на мигающий значок нештатной ситуации
            for j, (ic, lb, kind) in enumerate(nodes):
                if kind == "cur": nodes[j] = ("⚠", lb, "bad" if s.blink else "warn"); break

        x, y, gap = 60, 55, 155
        for j, (ic, lb, kind) in enumerate(nodes):
            cx = x + j * gap
            if j: s.create_line(x + (j - 1) * gap + s.R, y, cx - s.R, y, fill="#b7c0cc", width=2, arrow="last")
            s.create_oval(cx - s.R, y - s.R, cx + s.R, y + s.R, fill=COL[kind], outline="")
            s.create_text(cx, y, text=ic, font=("Segoe UI", 18))
            s.create_text(cx, y + s.R + 16, text=lb, font=("Segoe UI", 10), fill="#4a5a6d")
        if has_incident: s.create_text(x, y + s.R + 34, anchor="w", fill="#b3261e",
                                        font=("Segoe UI", 9), text="⚠ Есть нештатная ситуация — нажмите на схему для подробностей")

def pad_ok(pad, start, skip=0):
    t = pt(start)
    if not t: return "Время старта: формат ГГГГ-ММ-ДД ЧЧ:ММ"
    for (s,) in q("SELECT start_time FROM launches WHERE pad_id=? AND id!=? AND status IN ('запланирован','подготовка','готов')", (pad, skip)):
        if abs(pt(s) - t) < timedelta(hours=12): return "Площадка занята другим пуском (интервал менее 12 ч)"
    if q("SELECT 1 FROM maintenance WHERE pad_id=? AND ? BETWEEN d1 AND d2", (pad, start[:10])):
        return "Площадка на обслуживании в эту дату"

REP = {
 "Пуски по типам РН": (("Тип РН", "Кол-во пусков"), "SELECT r.type,COUNT(*) FROM launches l JOIN rockets r ON r.id=l.rocket_id WHERE date(l.start_time) BETWEEN :a AND :b GROUP BY r.type"),
 "Расход топлива": (("Партия", "Тип", "Пуск", "Объём", "Дата"), "SELECT u.batch_id,b.fuel,u.launch_id,u.volume,u.dt FROM usage u JOIN batches b ON b.id=u.batch_id WHERE date(u.dt) BETWEEN :a AND :b ORDER BY u.batch_id"),
 "Нештатные ситуации": (("Время", "Пуск", "Канал", "Описание", "Меры", "Статус"), "SELECT time,launch_id,channel,descr,measures,status FROM incidents WHERE date(time) BETWEEN :a AND :b"),
 "Переносы пусков": (("Причина", "Кол-во переносов"), "SELECT reason,COUNT(*) FROM postponements WHERE date(dt) BETWEEN :a AND :b GROUP BY reason"),
 "Загрузка площадок": (("Площадка", "Подготовок", "Выполнено пусков", "Дней обслуживания"),
  "SELECT p.name,(SELECT COUNT(*) FROM launches l WHERE l.pad_id=p.id AND l.status!='отменен' AND date(l.start_time) BETWEEN :a AND :b),"
  "(SELECT COUNT(*) FROM launches l WHERE l.pad_id=p.id AND l.status='выполнен' AND date(l.start_time) BETWEEN :a AND :b),"
  "(SELECT COALESCE(SUM(MAX(0,julianday(MIN(m.d2,:b))-julianday(MAX(m.d1,:a))+1)),0) FROM maintenance m WHERE m.pad_id=p.id) FROM pads p"),
}
REPORTS_FOR = {INSP: ["Нештатные ситуации"]}  # инспектору доступны только отчёты по инцидентам; остальным ролям — весь список REP

def build(role, fio):
    ROLE[0] = role; root.title(f"Центр управления пусками — {fio} ({role})")
    QUEUE.clear(); SHOW[0] = False

    def audit(action):
        # Все действия инспектора безопасности фиксируются в отдельном аудиторском журнале
        if role == INSP: q("INSERT INTO audit_log(fio,role,action,dt) VALUES(?,?,?,?)", (fio, role, action, now()))
    audit("Вход в систему")

    st = ttk.Label(root, anchor="w", style="Status.TLabel"); st.pack(side="bottom", fill="x")
    def logout():
        audit("Выход из системы")
        for w in root.winfo_children(): w.destroy()
        root.title("Центр управления пусками"); login()
    ttk.Button(st, text="Сменить пользователя", command=logout).pack(side="right")
    def tick():
        if st.winfo_exists(): st.config(text=f"Пользователь: {fio}   |   Роль: {role}   |   {now()}   |   Серые кнопки недоступны вашей роли"); root.after(30000, tick)
    tick()

    # Ограничение видимости вкладок: инспектор безопасности видит только журналы нештатных
    # ситуаций и переносов (плюс уведомления и отчёты по инцидентам) — без доступа к расписанию
    # пусков и подготовке; журнал аудита видит только руководитель.
    def tab_ok(n):
        if role == INSP: return n in ("Нештатные ситуации", "Переносы пусков", "🔔 Уведомления", "Отчёты")
        if n == "🛡 Аудит": return role == RUK
        return True

    nb = ttk.Notebook(root); nb.pack(fill="both", expand=True); G, DGS = [], []
    def page(n):
        f = ttk.Frame(nb, padding=12); nb.add(f, text=n)
        if not tab_ok(n): nb.hide(f)
        return f
    def grid(p, *a): g = Grid(p, *a); g.pack(fill="both", expand=True, pady=(0, 10)); G.append(g); return g
    def R():
        for g in G: g.load()
        for d in DGS: d.draw()

    def on_tab_changed(e):
        name = nb.tab(nb.select(), "text")
        if role == INSP and name in ("Нештатные ситуации", "Переносы пусков", "Отчёты"): audit(f"Просмотр вкладки «{name}»")
    nb.bind("<<NotebookTabChanged>>", on_tab_changed)

    def weather_poll():
        # Фоновая проверка: за 24 часа (окно 23–25 ч) до старта запрашиваем прогноз у внешней
        # метеослужбы; если служба недоступна — просим диспетчера/руководителя ввести данные вручную.
        if not st.winfo_exists(): return
        lo, hi = datetime.now() + timedelta(hours=23), datetime.now() + timedelta(hours=25)
        for lid, start in q("SELECT id,start_time FROM launches WHERE status IN ('запланирован','подготовка','готов')"):
            t = pt(start)
            if t and lo <= t <= hi and not q("SELECT 1 FROM weather_checks WHERE launch_id=?", (lid,)):
                data = fetch_external_weather(lid)
                if data: record_weather(lid, *data, "авто")
                else:
                    q("INSERT INTO weather_checks(launch_id,source,checked_at,wind,temp,storm,exceeded,details) "
                      "VALUES(?,?,?,NULL,NULL,NULL,NULL,'внешняя служба недоступна')", (lid, "недоступна", now()))
                    notify((RUK, DSP), f"Пуск {ln(lid)}: внешняя метеослужба недоступна. Требуется ручной ввод "
                                       f"метеоданных метеорологом (вкладка «Пуски» → «Метеоданные»).")
        root.after(60000, weather_poll)
    weather_poll()

    def bar(p, items):
        f = ttk.Frame(p); f.pack(side="bottom", fill="x", pady=(4, 6), before=p.pack_slaves()[0])
        ttk.Separator(f).pack(fill="x", pady=(0, 6))
        for txt, perm, fn in items:
            b = ttk.Button(f, text=txt, command=fn, width=22); b.pack(side="left", padx=4)
            if perm not in PERM[role]: b.state(["disabled"])

    # ---------- Пуски ----------
    p = page("Пуски")
    L = grid(p, ("№", "Носитель", "Нагрузка", "Орбита", "Площадка", "Старт", "Статус"),
             "SELECT l.id,r.type,pl.type,l.orbit,pd.name,l.start_time,l.status FROM launches l JOIN rockets r ON r.id=l.rocket_id "
             "JOIN payloads pl ON pl.id=l.payload_id JOIN pads pd ON pd.id=l.pad_id ORDER BY l.start_time")
    S = grid(p, ("№", "Этап подготовки", "Статус", "Дата"), "SELECT id,name,status,COALESCE(dt,'') FROM stages WHERE launch_id=?", lambda: (sid(L),))
    dg = Diagram(p); dg.pack(fill="x", pady=(0, 10)); DGS.append(dg)
    W = grid(p, ("№", "Источник", "Время", "Ветер, м/с", "Темп., °C", "Гроза", "Превышение"),
             "SELECT id,source,checked_at,COALESCE(wind,''),COALESCE(temp,''),"
             "CASE storm WHEN 1 THEN 'да' WHEN 0 THEN 'нет' ELSE '—' END,"
             "CASE exceeded WHEN 1 THEN 'да' WHEN 0 THEN 'нет' ELSE '—' END "
             "FROM weather_checks WHERE launch_id=? ORDER BY id DESC", lambda: (sid(L),))
    L.t.bind("<<TreeviewSelect>>", lambda e: (S.load(), W.load(), dg.show(sid(L))))

    def add_launch():
        f = form("Новый пуск", [("r", "Ракета-носитель", pairs("SELECT id,type FROM rockets"), ""),
            ("pl", "Полезная нагрузка", pairs("SELECT id,type FROM payloads"), ""), ("o", "Целевая орбита", None, ""),
            ("pd", "Стартовая площадка", pairs("SELECT id,name FROM pads"), ""), ("t", "Старт (ГГГГ-ММ-ДД ЧЧ:ММ)", None, now())])
        if not f: return
        e = "Заполните все обязательные поля" if not all(f.values()) else pad_ok(f["pd"], f["t"])
        if e: return err(e)
        q("INSERT INTO launches(rocket_id,payload_id,orbit,pad_id,start_time,status) VALUES(?,?,?,?,?,'запланирован')",
          (f["r"], f["pl"], f["o"], f["pd"], f["t"]))
        i = q("SELECT MAX(id) FROM launches")[0][0]
        notify(FUEL, f"Создан пуск {ln(i)}. Далее: проверьте наличие годных партий горючего и окислителя (вкладка «Топливо»); списание — после перевода пуска в «подготовка».")
        notify(RUK, f"Запланирован пуск {ln(i)}. Далее: контролируйте загрузку площадки и график её обслуживания."); R()
    def advance():
        r = L.sel()
        if not r: return
        nxt = NEXT.get(r[6])
        if not nxt: return err("Из статуса «%s» переход невозможен" % r[6])
        if nxt == "подготовка" and not q("SELECT 1 FROM stages WHERE launch_id=?", (r[0],)):
            for n in STAGES: q("INSERT INTO stages(launch_id,name,status) VALUES(?,?,'ожидает')", (r[0], n))
        if nxt == "готов" and q("SELECT 1 FROM stages WHERE launch_id=? AND status!='выполнен'", (r[0],)):
            return err("Не все этапы подготовки выполнены")
        q("UPDATE launches SET status=? WHERE id=?", (nxt, r[0]))
        for ro, t in ADV.get(nxt, []): notify(ro, f"Пуск {ln(r[0])} " + t)
        R()
    def stage():
        r = L.sel()
        if not r: return
        if r[6] != "подготовка": return err("Этапы ведутся только в статусе «подготовка»")
        s = q("SELECT id FROM stages WHERE launch_id=? AND status!='выполнен' ORDER BY id LIMIT 1", (r[0],))
        if s:
            q("UPDATE stages SET status='выполнен',dt=? WHERE id=?", (now(), s[0][0]))
            n = q("SELECT COUNT(*) FROM stages WHERE launch_id=? AND status='выполнен'", (r[0],))[0][0]
            notify(STAGE_NOTE[n - 1][0], f"Пуск {ln(r[0])}: " + STAGE_NOTE[n - 1][1])
            if n == 3 and not q("SELECT 1 FROM usage WHERE launch_id=?", (r[0],)):
                notify(FUEL, f"Пуск {ln(r[0])}: заправка отмечена выполненной, но топливо не списано. Далее: спишите топливо (Топливо → Списать на пуск).")
            R()
    def cancel():
        r = L.sel()
        if r and r[6] not in ("выполнен", "отменен") and mb.askyesno("Отмена", "Отменить пуск?"):
            q("UPDATE launches SET status='отменен' WHERE id=?", (r[0],))
            notify((RUK, FUEL), f"Пуск {ln(r[0])} отменён. Далее: площадка освобождена; проверьте остатки топлива и при необходимости пересмотрите график."); R()
    def postpone():
        r = L.sel()
        if not r: return
        if r[6] in ("выполнен", "отменен"): return err("Пуск нельзя перенести")
        f = form("Перенос пуска", [("d", "Новое время (ГГГГ-ММ-ДД ЧЧ:ММ)", None, r[5]), ("w", "Причина", None, "")])
        if not f: return
        if not f["w"]: return err("Перенос оформляется только с указанием причины")
        pad = q("SELECT pad_id FROM launches WHERE id=?", (r[0],))[0][0]
        e = pad_ok(pad, f["d"], r[0])
        if e: return err(e)
        q("UPDATE launches SET start_time=?,status='перенесен' WHERE id=?", (f["d"], r[0]))
        q("INSERT INTO postponements(launch_id,reason,new_date,dt) VALUES(?,?,?,?)", (r[0], f["w"], f["d"], now()))
        notify((DSP, FUEL), f"Пуск {ln(r[0])} перенесён (причина: {f['w']}). Далее: диспетчер — верните пуск в план («Следующий статус»); техник — проверьте срок годности партий на новую дату."); R()
    def add_weather():
        r = L.sel()
        if not r: return
        if r[6] in ("выполнен", "отменен"): return err("Метеоданные вводятся только для активных пусков")
        f = form("Метеоданные (ручной ввод метеорологом)", [
            ("w", "Скорость ветра на высоте, м/с", None, ""), ("t", "Температура, °C", None, ""),
            ("s", "Грозовая активность", [("0", "Нет"), ("1", "Да")], "")])
        if not f: return
        try: wind, temp, storm = float(f["w"]), float(f["t"]), bool(int(f["s"]))
        except Exception: return err("Укажите числовые значения ветра и температуры, отметьте грозовую активность")
        exceeded, reasons = record_weather(r[0], wind, temp, storm, "ручной")
        mb.showinfo("Метеоданные внесены", "Превышений предельных значений не обнаружено." if not exceeded
                    else "Превышение предельных значений:\n" + "\n".join(reasons)); R()
    bar(p, [("Создать пуск", "launch", add_launch), ("Следующий статус", "launch", advance), ("Завершить этап", "stage", stage),
            ("Перенести", "postpone", postpone), ("Отменить пуск", "launch", cancel), ("Метеоданные", "weather", add_weather)])

    # ---------- Топливо ----------
    p = page("Топливо")
    B = grid(p, ("№", "Тип", "Объём", "Остаток", "Годен до", "Состояние"),
             "SELECT id,fuel,volume,remaining,expiry,CASE WHEN expiry<date('now') THEN 'просрочена' ELSE 'годна' END FROM batches")
    grid(p, ("№", "Партия", "Пуск", "Объём", "Дата"), "SELECT id,batch_id,launch_id,volume,dt FROM usage ORDER BY id DESC")
    def add_batch():
        f = form("Приёмка партии", [("t", "Тип топлива", [("Горючее", "Горючее"), ("Окислитель", "Окислитель")], ""),
                                    ("v", "Объём", None, ""), ("e", "Годен до (ГГГГ-ММ-ДД)", None, "")])
        if not f: return
        try: v = float(f["v"]); assert v > 0 and f["t"] and pd_(f["e"])
        except Exception: return err("Проверьте тип, объём (>0) и срок годности")
        q("INSERT INTO batches(fuel,volume,remaining,expiry) VALUES(?,?,?,?)", (f["t"], v, v, f["e"]))
        notify(DSP, f"Принята партия «{f['t']}», {v:g} ед., годна до {f['e']}. Далее: топливо доступно для списания на пуски в статусе «подготовка»."); R()
    def use_fuel():
        f = form("Списание топлива", [
            ("b", "Партия", pairs("SELECT id,id||' '||fuel||', остаток '||remaining||', до '||expiry FROM batches WHERE expiry>=date('now') AND remaining>0"), ""),
            ("l", "Пуск (в подготовке)", pairs("SELECT id,'Пуск №'||id FROM launches WHERE status='подготовка'"), ""), ("v", "Объём", None, "")])
        if not f: return
        try: v = float(f["v"]); assert v > 0 and f["b"] and f["l"]
        except Exception: return err("Выберите партию и пуск, объём > 0")
        if v > q("SELECT remaining FROM batches WHERE id=?", (f["b"],))[0][0]: return err("Недостаточно топлива в партии")
        q("UPDATE batches SET remaining=remaining-? WHERE id=?", (v, f["b"]))
        q("INSERT INTO usage(batch_id,launch_id,volume,dt) VALUES(?,?,?,?)", (f["b"], f["l"], v, now()))
        notify(DSP, f"Пуск {ln(f['l'])}: списано {v:g} ед. топлива из партии №{f['b']}. Далее: завершите этап заправки, затем предстартовый контроль."); R()
    bar(p, [("Принять партию", "fuel", add_batch), ("Списать на пуск", "fuel", use_fuel)])

    # ---------- Площадки ----------
    p = page("Площадки")
    grid(p, ("№", "Площадка", "Состояние"),
         "SELECT id,name,CASE WHEN EXISTS(SELECT 1 FROM maintenance m WHERE m.pad_id=pads.id AND date('now') BETWEEN d1 AND d2) THEN 'на обслуживании' "
         "WHEN EXISTS(SELECT 1 FROM launches l WHERE l.pad_id=pads.id AND l.status IN ('подготовка','готов')) THEN 'занята' ELSE 'свободна' END FROM pads")
    grid(p, ("№", "Площадка", "С", "По", "Вид работ"), "SELECT m.id,p.name,m.d1,m.d2,m.kind FROM maintenance m JOIN pads p ON p.id=m.pad_id ORDER BY m.d1 DESC")
    def add_mt():
        f = form("Обслуживание", [("p", "Площадка", pairs("SELECT id,name FROM pads"), ""), ("k", "Вид работ", None, "Осмотр"),
                                  ("a", "С (ГГГГ-ММ-ДД)", None, now()[:10]), ("b", "По (ГГГГ-ММ-ДД)", None, now()[:10])])
        if not f: return
        if not (f["p"] and f["k"] and pd_(f["a"]) and pd_(f["b"]) and f["a"] <= f["b"]): return err("Проверьте поля и даты")
        q("INSERT INTO maintenance(pad_id,d1,d2,kind) VALUES(?,?,?,?)", (f["p"], f["a"], f["b"], f["k"]))
        nm = q("SELECT name FROM pads WHERE id=?", (f["p"],))[0][0]
        notify(DSP, f"{nm} на обслуживании с {f['a']} по {f['b']} ({f['k']}). Далее: не планируйте пуски на этот период, пересмотрите пуски на эти даты."); R()
    bar(p, [("Запланировать обслуживание", "pad", add_mt)])

    # ---------- Нештатные ситуации ----------
    p = page("Нештатные ситуации")
    I = grid(p, ("№", "Пуск", "Канал", "Время", "Описание", "Меры", "Статус"), "SELECT id,launch_id,channel,time,descr,measures,status FROM incidents ORDER BY id DESC")
    def add_inc():
        f = form("Нештатная ситуация", [
            ("l", "Пуск", pairs("SELECT l.id,'№'||l.id||' '||r.type||' ('||l.status||')' FROM launches l JOIN rockets r ON r.id=l.rocket_id WHERE l.status IN ('подготовка','готов')"), ""),
            ("c", "Канал телеметрии", None, ""), ("t", "Время (ГГГГ-ММ-ДД ЧЧ:ММ)", None, now()), ("d", "Описание", None, "Потеря сигнала")])
        if not f: return
        if not (all(f.values()) and pt(f["t"])): return err("Заполните поля (время: ГГГГ-ММ-ДД ЧЧ:ММ)")
        q("INSERT INTO incidents(launch_id,channel,time,descr,measures,status) VALUES(?,?,?,?,'','открыта')", (f["l"], f["c"], f["t"], f["d"]))
        notify((DSP, RUK), f"Нештатная ситуация по пуску {ln(f['l'])}: канал {f['c']}, {f['d']}. Далее: диспетчер — укажите принятые меры («Следующий статус»); руководитель — оцените необходимость переноса пуска."); R()
    def inc_next():
        r = I.sel()
        if not r: return
        if r[6] == "открыта":
            f = form("Принятые меры", [("m", "Меры", None, "")])
            if not f: return
            if not f["m"]: return err("Укажите принятые меры")
            q("UPDATE incidents SET measures=?,status='в работе' WHERE id=?", (f["m"], r[0]))
            notify((RUK, DSP), f"Нештатная ситуация №{r[0]}: приняты меры — {f['m']}. Далее: после устранения диспетчер закрывает ситуацию («Следующий статус»).")
        elif r[6] == "в работе":
            q("UPDATE incidents SET status='закрыта' WHERE id=?", (r[0],))
            notify((RUK, AN), f"Нештатная ситуация №{r[0]} закрыта. Далее: она попадёт в отчёт «Нештатные ситуации»; продолжите подготовку или проведение пуска.")
        R()
    bar(p, [("Зафиксировать", "incident", add_inc), ("Следующий статус", "incident", inc_next)])

    # ---------- Переносы пусков (журнал) ----------
    p = page("Переносы пусков")
    grid(p, ("№", "Пуск", "Причина", "Новая дата", "Оформлен"),
         "SELECT id,launch_id,reason,new_date,dt FROM postponements ORDER BY id DESC")

    # ---------- Аудит (только для руководителя) ----------
    p = page("🛡 Аудит")
    grid(p, ("№", "Время", "Сотрудник", "Роль", "Действие"), "SELECT id,dt,fio,role,action FROM audit_log ORDER BY id DESC LIMIT 300")

    # ---------- Уведомления ----------
    p = page("🔔 Уведомления")
    N = grid(p, ("№", "Время", "Уведомление"), "SELECT id,dt,txt FROM notes WHERE role=? ORDER BY id DESC LIMIT 100", (role,))
    N.t.column("Уведомление", width=750)
    def poll():
        if not st.winfo_exists(): return
        for i, t in q("SELECT id,txt FROM notes WHERE role=? AND seen=0 ORDER BY id", (role,)):
            QUEUE.append(t); q("UPDATE notes SET seen=1 WHERE id=?", (i,))
        pump(); N.load(); root.after(3000, poll)
    poll()

    # ---------- Отчёты ----------
    if "report" in PERM[role]:
        keys = REPORTS_FOR.get(role, list(REP))  # инспектору безопасности доступны только отчёты по инцидентам
        p = page("Отчёты"); top = ttk.Frame(p); top.pack(fill="x", pady=4)
        cb = ttk.Combobox(top, values=keys, state="readonly", width=26); cb.current(0); cb.pack(side="left", padx=3)
        a, b = MaskEntry(top, "dddd-dd-dd", width=11), MaskEntry(top, "dddd-dd-dd", width=11); a.insert(0, "2026-01-01"); b.insert(0, "2026-12-31")
        for t, w in (("с", a), ("по", b)): ttk.Label(top, text=t).pack(side="left", padx=(8, 2)); w.pack(side="left", padx=3)
        tv = ttk.Treeview(p, show="headings"); tv.pack(fill="both", expand=True)
        def show():
            if not (pd_(a.get()) and pd_(b.get())): return err("Период: ГГГГ-ММ-ДД"), None
            cols, sql = REP[cb.get()]; tv["columns"] = cols
            for c in cols: tv.heading(c, text=c); tv.column(c, width=150)
            tv.delete(*tv.get_children()); rows = db.execute(sql, {"a": a.get(), "b": b.get()}).fetchall()
            for r in rows: tv.insert("", "end", values=r)
            audit(f"Сформирован отчёт «{cb.get()}» за период {a.get()}–{b.get()}")
            return cols, rows
        def export():
            cols, rows = show()
            fn = rows is not None and filedialog.asksaveasfilename(defaultextension=".csv", initialfile=cb.get() + ".csv")
            if fn:
                with open(fn, "w", newline="", encoding="utf-8-sig") as fh:
                    w = csv.writer(fh, delimiter=";"); w.writerow(cols); w.writerows(rows)
                audit(f"Экспорт отчёта «{cb.get()}» в CSV")
        ttk.Button(top, text="Сформировать", command=show).pack(side="left", padx=3)
        ttk.Button(top, text="Экспорт CSV", command=export).pack(side="left", padx=3)

def login():
    f = ttk.Frame(root, style="Card.TFrame", padding=36); f.place(relx=.5, rely=.42, anchor="center")
    ttk.Label(f, text="🚀 Центр управления пусками", style="Card.TLabel", font=("Segoe UI", 17, "bold"), foreground=ACC).grid(columnspan=2, pady=(0, 4))
    ttk.Label(f, text="Вход в систему", style="Card.TLabel", foreground="#7a8796").grid(columnspan=2, pady=(0, 16))
    e1, e2 = ttk.Entry(f, width=28), ttk.Entry(f, show="*", width=28)
    for i, (t, e) in enumerate([("Логин", e1), ("Пароль", e2)], 2):
        ttk.Label(f, text=t, style="Card.TLabel").grid(row=i, column=0, sticky="e", padx=8, pady=5); e.grid(row=i, column=1, pady=5)
    def go(_=None):
        r = q("SELECT fio,role FROM users WHERE login=? AND pwd=?", (e1.get(), hashlib.sha256(e2.get().encode()).hexdigest()))
        if not r: return err("Неверный логин или пароль")
        root.unbind("<Return>"); f.destroy(); build(r[0][1], r[0][0])
    ttk.Button(f, text="Войти", command=go).grid(row=4, column=0, columnspan=2, sticky="ew", padx=8, pady=(16, 0)); root.bind("<Return>", go); e1.focus()

root.title("Центр управления пусками"); login(); root.mainloop()