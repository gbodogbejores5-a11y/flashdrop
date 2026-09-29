import os, sys, json, math, time, zlib, queue, random, string, threading
import tkinter as tk
from tkinter import filedialog, messagebox
import fdcore as core

try:                                   # glisser-deposer (optionnel)
    from tkinterdnd2 import TkinterDnD, DND_FILES
    HAS_DND = True
except Exception:
    HAS_DND = False

APP_NAME, VERSION = "JRSDrop", core.VERSION

# ---------- couleurs ----------
BG, SIDE, PANEL = "#080D1A", "#0B1226", "#0D1530"
CARD, CARD2, LINE = "#121A33", "#1B2650", "#24306A"
ACCENT, ACCENT2 = "#22D3EE", "#8B5CF6"
TEXT, MUTED, OK, ERR = "#E8ECFF", "#8A94B8", "#34D399", "#F87171"
FONT = "Segoe UI"

ui_q = queue.Queue()


def res(p):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, p)


def mix(c1, c2, f):
    f = max(0.0, min(1.0, f))
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(a[i] * (1 - f) + b[i] * f) for i in range(3))


# ---------- reglages sauvegardes ----------
CFG_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "JRSDrop")
CFG_FILE = os.path.join(CFG_DIR, "config.json")


def load_cfg():
    cfg = {"name": core.NAME, "recv_dir": os.path.join(os.path.expanduser("~"), "Downloads", "JRSDrop"),
           "auto_accept": False, "relay": "", "room": "", "listen_room": False, "send_room": False, "history": [],
           "receive_on": False}
    try:
        with open(CFG_FILE, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save_cfg(cfg):
    try:
        os.makedirs(CFG_DIR, exist_ok=True)
        with open(CFG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def is_tailscale(ip):
    p = ip.split(".")
    return len(p) == 4 and p[0] == "100" and p[1].isdigit() and 64 <= int(p[1]) <= 127


def my_address():
    ts = [i for i in core.MY_IPS if is_tailscale(i)]
    return (ts[0] if ts else (core.MY_IPS[0] if core.MY_IPS else "")), bool(ts)


def hostport(s, default):
    s = s.strip()
    if ":" in s:
        h, p = s.rsplit(":", 1)
        if p.isdigit():
            return h, int(p)
    return s, default


# ---------- widgets ----------
class FlatButton(tk.Label):
    def __init__(self, master, text, command, bg=CARD2, hover=LINE, fg=TEXT,
                 font=(FONT, 10, "bold"), padx=16, pady=8):
        super().__init__(master, text=text, bg=bg, fg=fg, font=font, padx=padx, pady=pady, cursor="hand2")
        self._cmd, self._base, self._hov = command, bg, hover
        self.bind("<Enter>", lambda e: self.config(bg=self._hov))
        self.bind("<Leave>", lambda e: self.config(bg=self._base))
        self.bind("<Button-1>", lambda e: self._cmd())


def card(master, title=None):
    f = tk.Frame(master, bg=CARD, highlightbackground=LINE, highlightthickness=1)
    inner = tk.Frame(f, bg=CARD)
    inner.pack(fill="both", expand=True, padx=14, pady=12)
    if title:
        tk.Label(inner, text=title, bg=CARD, fg=TEXT, font=(FONT, 11, "bold")).pack(anchor="w", pady=(0, 6))
    return f, inner


def entry(master, var=None, width=None):
    return tk.Entry(master, textvariable=var, bg=CARD2, fg=TEXT, insertbackground=TEXT, relief="flat",
                    font=(FONT, 10), highlightthickness=1, highlightbackground=LINE,
                    highlightcolor=ACCENT, **({"width": width} if width else {}))


def check(master, text, var, cmd=None):
    return tk.Checkbutton(master, text=text, variable=var, command=cmd, bg=CARD, fg=TEXT, selectcolor=CARD2,
                          activebackground=CARD, activeforeground=TEXT, font=(FONT, 10), bd=0,
                          highlightthickness=0, cursor="hand2")


RW, RH = 300, 290
CX, CY, R = 150, 132, 118


class App:
    def __init__(self, root, cfg):
        self.root, self.cfg = root, cfg
        root.title(f"{APP_NAME} {VERSION}")
        root.geometry("940x640")
        root.resizable(False, False)
        root.configure(bg=BG)
        try:
            root.iconbitmap(res("assets/icon.ico"))
        except Exception:
            pass

        self.items, self.chosen = [], []
        self.selected, self.born, self.nodes = set(), {}, {}
        self.prog = {}
        self.pshow = self.ptarget = 0.0
        self.t0 = time.time()
        self.send_text = ""

        core.receiving = self.cfg["receive_on"]
        self.hk = core.Hooks()
        self.hk.get_dir = lambda: self.cfg["recv_dir"]
        self.hk.auto_accept = self.cfg["auto_accept"]
        self.hk.ask, self.hk.progress, self.hk.done = self.ask_user, self.on_progress, self.on_done
        self.hk.error, self.hk.relay_state = self.on_error, self.on_relay_state
        self.relay = core.RelayListener(self.hk)

        # --- barre laterale ---
        side = tk.Frame(root, bg=SIDE, width=190)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        logo = tk.Frame(side, bg=SIDE)
        logo.pack(fill="x", padx=18, pady=(22, 20))
        tk.Label(logo, text="\u26a1", bg=SIDE, fg=ACCENT, font=(FONT, 20)).pack(side="left")
        lb = tk.Frame(logo, bg=SIDE)
        lb.pack(side="left", padx=8)
        tk.Label(lb, text=APP_NAME, bg=SIDE, fg=TEXT, font=(FONT, 14, "bold")).pack(anchor="w")
        tk.Label(lb, text=f"version {VERSION}", bg=SIDE, fg=MUTED, font=(FONT, 8)).pack(anchor="w")
        self.navs = {}
        for key, txt in (("send", "\U0001f680   Envoyer"), ("recv", "\U0001f4e5   Recevoir"), ("hist", "\U0001f558   Historique"),
                         ("remote", "\U0001f30d   À distance"), ("set", "\u2699   Réglages")):
            b = tk.Label(side, text=txt, bg=SIDE, fg=MUTED, font=(FONT, 11), anchor="w",
                         padx=22, pady=11, cursor="hand2")
            b.pack(fill="x")
            b.bind("<Button-1>", lambda e, k=key: self.show(k))
            self.navs[key] = b
        self.me_lbl = tk.Label(side, text="", bg=SIDE, fg=MUTED, font=(FONT, 8), justify="left",
                               wraplength=160, anchor="w")
        self.me_lbl.pack(side="bottom", fill="x", padx=18, pady=16)
        self.chip = tk.Label(side, text="", bg=SIDE, fg=MUTED, font=(FONT, 9, "bold"), anchor="w")
        self.chip.pack(side="bottom", fill="x", padx=18)

        # --- zone de contenu ---
        right = tk.Frame(root, bg=BG)
        right.pack(side="left", fill="both", expand=True)
        self.status = tk.Label(right, text="Pour recevoir : onglet « Recevoir » puis bouton Recevoir. Pour envoyer : choisis un PC sur le radar.",
                               bg=BG, fg=MUTED, font=(FONT, 10), anchor="w", wraplength=690, justify="left")
        self.status.pack(side="bottom", fill="x", padx=24, pady=(4, 14))
        self.pages = {k: tk.Frame(right, bg=BG) for k in self.navs}
        self.build_send(self.pages["send"])
        self.build_receive(self.pages["recv"])
        self.build_hist(self.pages["hist"])
        self.build_remote(self.pages["remote"])
        self.build_settings(self.pages["set"])
        self.show("send")
        self.style_recv()

        if HAS_DND:
            try:
                root.drop_target_register(DND_FILES)
                root.dnd_bind("<<Drop>>", lambda e: self.add_paths(list(root.tk.splitlist(e.data))))
            except Exception:
                pass
        if core.receiving and self.cfg["listen_room"] and self.cfg["relay"] and self.cfg["room"]:
            self.start_room()

        self.refresh()
        self.poll()
        self.tick()

    # ---------- pages ----------
    def show(self, k):
        for n, p in self.pages.items():
            p.pack_forget()
            self.navs[n].config(bg=SIDE, fg=MUTED)
        self.pages[k].pack(fill="both", expand=True, padx=24, pady=(20, 0))
        self.navs[k].config(bg=CARD2, fg=TEXT)

    def build_send(self, page):
        top = tk.Frame(page, bg=BG)
        top.pack(fill="x")
        self.cv = tk.Canvas(top, width=RW, height=RH, bg=BG, highlightthickness=0)
        self.cv.pack(side="left")
        self.cv.bind("<Button-1>", self.on_click)
        self.cv.bind("<Motion>", self.on_move)

        fc, fi = card(top, "Fichiers à envoyer")
        fc.pack(side="left", fill="both", expand=True, padx=(12, 0))
        self.lst = tk.Listbox(fi, bg=CARD2, fg=TEXT, bd=0, highlightthickness=0, font=(FONT, 9),
                              activestyle="none", selectbackground=ACCENT2, height=8)
        self.lst.pack(fill="both", expand=True)
        self.files_lbl = tk.Label(fi, text="Glisse des fichiers ici" if HAS_DND else "Aucun fichier choisi",
                                  bg=CARD, fg=MUTED, font=(FONT, 9), anchor="w")
        self.files_lbl.pack(fill="x", pady=(6, 6))
        row = tk.Frame(fi, bg=CARD)
        row.pack(fill="x")
        FlatButton(row, "+ Fichiers", self.pick, padx=10, pady=5, font=(FONT, 9, "bold")).pack(side="left")
        FlatButton(row, "+ Dossier", self.pick_dir, padx=10, pady=5, font=(FONT, 9, "bold")).pack(side="left", padx=6)
        FlatButton(row, "Vider", self.clear, padx=10, pady=5, font=(FONT, 9, "bold")).pack(side="left")

        self.dest_lbl = tk.Label(page, text="", bg=BG, fg=MUTED, font=(FONT, 9), anchor="w")
        self.dest_lbl.pack(fill="x", pady=(6, 4))
        btns = tk.Frame(page, bg=BG)
        btns.pack(fill="x")
        self.send_btn = FlatButton(btns, "\U0001f680  Envoyer", self.send, bg=ACCENT, hover=mix(ACCENT, "#FFFFFF", 0.3),
                                   fg="#04121A", font=(FONT, 13, "bold"), pady=12)
        self.send_btn.pack(side="left", fill="x", expand=True)
        FlatButton(btns, "\u26a1 Test de vitesse", self.bench, pady=12, padx=18).pack(side="left", padx=(10, 0))
        self.pb = tk.Canvas(page, height=10, bg=BG, highlightthickness=0)
        self.pb.pack(fill="x", pady=(14, 4))
        self.stat_lbl = tk.Label(page, text="", bg=BG, fg=ACCENT, font=(FONT, 10, "bold"), anchor="w")
        self.stat_lbl.pack(fill="x")

    def build_receive(self, page):
        tk.Label(page, text="Recevoir des fichiers", bg=BG, fg=TEXT, font=(FONT, 16, "bold")).pack(anchor="w")
        tk.Label(page, text="Clique sur « Recevoir » : ton PC devient visible sur le radar de tes amis et prêt à "
                            "recevoir, même de l'étranger.", bg=BG, fg=MUTED, font=(FONT, 9),
                 wraplength=690, justify="left").pack(anchor="w", pady=(0, 6))
        top = tk.Frame(page, bg=BG)
        top.pack(fill="x")
        self.rcv = tk.Canvas(top, width=260, height=215, bg=BG, highlightthickness=0)
        self.rcv.pack(side="left")
        right = tk.Frame(top, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))
        self.rcv_btn = FlatButton(right, "", self.toggle_receive, font=(FONT, 13, "bold"), pady=12)
        self.rcv_btn.pack(fill="x", pady=(8, 10))
        c0, i0 = card(right, "Ton adresse (à donner à ton ami)")
        c0.pack(fill="x")
        self.addr_lbl = tk.Label(i0, text="", bg=CARD, fg=ACCENT, font=(FONT, 12, "bold"), anchor="w")
        self.addr_lbl.pack(fill="x")
        self.addr_hint = tk.Label(i0, text="", bg=CARD, fg=MUTED, font=(FONT, 9), anchor="w",
                                  justify="left", wraplength=360)
        self.addr_hint.pack(fill="x", pady=(2, 6))
        FlatButton(i0, "Copier mon adresse", self.copy_addr, padx=10, pady=4, font=(FONT, 9, "bold")).pack(anchor="w")
        fr = tk.Frame(page, bg=BG)
        fr.pack(fill="x", pady=(10, 0))
        self.rdir_lbl = tk.Label(fr, text="", bg=BG, fg=MUTED, font=(FONT, 9), anchor="w",
                                 wraplength=520, justify="left")
        self.rdir_lbl.pack(side="left")
        FlatButton(fr, "Ouvrir le dossier", self.open_dir, padx=10, pady=4, font=(FONT, 9, "bold")).pack(side="right")
        self.pb2 = tk.Canvas(page, height=10, bg=BG, highlightthickness=0)
        self.pb2.pack(fill="x", pady=(14, 4))
        self.stat2 = tk.Label(page, text="", bg=BG, fg=ACCENT, font=(FONT, 10, "bold"), anchor="w")
        self.stat2.pack(fill="x")

    def build_hist(self, page):
        tk.Label(page, text="Historique", bg=BG, fg=TEXT, font=(FONT, 16, "bold")).pack(anchor="w", pady=(0, 10))
        c, i = card(page)
        c.pack(fill="both", expand=True)
        self.hlist = tk.Listbox(i, bg=CARD2, fg=TEXT, bd=0, highlightthickness=0, font=("Consolas", 9),
                                activestyle="none", selectbackground=ACCENT2)
        self.hlist.pack(fill="both", expand=True)
        row = tk.Frame(page, bg=BG)
        row.pack(fill="x", pady=10)
        FlatButton(row, "Ouvrir le dossier de réception", self.open_dir).pack(side="left")
        FlatButton(row, "Effacer l'historique", self.clear_hist).pack(side="left", padx=8)
        self.fill_hist()

    def build_remote(self, page):
        tk.Label(page, text="Envoyer à un PC lointain", bg=BG, fg=TEXT, font=(FONT, 16, "bold")).pack(anchor="w")
        tk.Label(page, text="Pour un PC qui n'est pas sur le même Wi-Fi (autre ville, autre pays).",
                 bg=BG, fg=MUTED, font=(FONT, 9)).pack(anchor="w", pady=(0, 10))
        c1, i1 = card(page, "Méthode 1 : adresse directe (Tailscale / IP publique)")
        c1.pack(fill="x", pady=(0, 10))
        tk.Label(i1, text="Ex : 100.91.240.60 (Tailscale)  ou  41.x.x.x:50555 (IP publique + port ouvert)",
                 bg=CARD, fg=MUTED, font=(FONT, 9)).pack(anchor="w")
        self.ip_entry = entry(i1)
        self.ip_entry.pack(fill="x", ipady=5, pady=(6, 0))

        c2, i2 = card(page, "Méthode 2 : salle privée via un serveur relais (sans rien ouvrir)")
        c2.pack(fill="x")
        tk.Label(i2, text="Les 2 PC entrent la même salle. Le relais (relay.py) tourne sur un serveur en ligne.",
                 bg=CARD, fg=MUTED, font=(FONT, 9)).pack(anchor="w")
        r1 = tk.Frame(i2, bg=CARD)
        r1.pack(fill="x", pady=(8, 0))
        tk.Label(r1, text="Relais", bg=CARD, fg=MUTED, font=(FONT, 9), width=9, anchor="w").pack(side="left")
        self.relay_var = tk.StringVar(value=self.cfg["relay"])
        entry(r1, self.relay_var).pack(side="left", fill="x", expand=True, ipady=4)
        r2 = tk.Frame(i2, bg=CARD)
        r2.pack(fill="x", pady=(6, 0))
        tk.Label(r2, text="Code salle", bg=CARD, fg=MUTED, font=(FONT, 9), width=9, anchor="w").pack(side="left")
        self.room_var = tk.StringVar(value=self.cfg["room"])
        entry(r2, self.room_var).pack(side="left", fill="x", expand=True, ipady=4)
        FlatButton(r2, "Générer", self.gen_room, padx=10, pady=4, font=(FONT, 9, "bold")).pack(side="left", padx=(8, 0))
        self.listen_var = tk.BooleanVar(value=self.cfg["listen_room"])
        self.sendroom_var = tk.BooleanVar(value=self.cfg["send_room"])
        check(i2, "Écouter dans cette salle (recevoir depuis l'autre PC)", self.listen_var, self.apply_room).pack(anchor="w", pady=(10, 0))
        check(i2, "Envoyer aussi vers cette salle quand je clique sur Envoyer", self.sendroom_var, self.apply_room).pack(anchor="w")
        self.relay_lbl = tk.Label(i2, text="", bg=CARD, fg=MUTED, font=(FONT, 9), anchor="w")
        self.relay_lbl.pack(fill="x", pady=(6, 0))

    def build_settings(self, page):
        tk.Label(page, text="Réglages", bg=BG, fg=TEXT, font=(FONT, 16, "bold")).pack(anchor="w", pady=(0, 10))
        c, i = card(page)
        c.pack(fill="x")
        tk.Label(i, text="Nom affiché aux autres PC", bg=CARD, fg=MUTED, font=(FONT, 9)).pack(anchor="w")
        self.name_var = tk.StringVar(value=self.cfg["name"])
        entry(i, self.name_var).pack(fill="x", ipady=5, pady=(4, 12))
        tk.Label(i, text="Dossier de réception", bg=CARD, fg=MUTED, font=(FONT, 9)).pack(anchor="w")
        row = tk.Frame(i, bg=CARD)
        row.pack(fill="x", pady=(4, 12))
        self.dir_lbl = tk.Label(row, text=self.cfg["recv_dir"], bg=CARD, fg=TEXT, font=(FONT, 9),
                                anchor="w", wraplength=380, justify="left")
        self.dir_lbl.pack(side="left", fill="x", expand=True)
        FlatButton(row, "Changer", self.change_dir, padx=10, pady=4, font=(FONT, 9, "bold")).pack(side="right")
        FlatButton(row, "Ouvrir", self.open_dir, padx=10, pady=4, font=(FONT, 9, "bold")).pack(side="right", padx=6)
        self.auto_var = tk.BooleanVar(value=self.cfg["auto_accept"])
        check(i, "Accepter automatiquement les fichiers (déconseillé sur un réseau public)", self.auto_var).pack(anchor="w")
        FlatButton(page, "Enregistrer", self.save_settings, bg=ACCENT, hover=mix(ACCENT, "#FFFFFF", 0.3),
                   fg="#04121A").pack(anchor="w", pady=12)
        tk.Label(page, text=f"Ports utilisés : {core.TCP_PORT} (TCP, fichiers) \u2022 {core.UDP_PORT} (UDP, détection)\n"
                            "Fais confiance uniquement aux PC que tu connais : chaque fichier demande ton accord.",
                 bg=BG, fg=MUTED, font=(FONT, 9), justify="left").pack(anchor="w")

    # ---------- retours du noyau (depuis les threads => file d'attente) ----------
    def ask_user(self, info):
        ev, out = threading.Event(), {"ok": False}

        def build():
            self.root.deiconify()
            self.root.lift()
            self.root.bell()
            d = tk.Toplevel(self.root)
            d.title("JRSDrop")
            d.configure(bg=CARD)
            d.resizable(False, False)
            d.attributes("-topmost", True)
            w, h = 430, 230
            d.geometry(f"{w}x{h}+{self.root.winfo_x() + (self.root.winfo_width() - w) // 2}+"
                       f"{self.root.winfo_y() + (self.root.winfo_height() - h) // 2}")
            many = info["count"] > 1
            what = f"{info['count']} fichiers" if many else info["name"]
            sz = info["total"] if many else info["size"]
            tk.Label(d, text="\U0001f4e5  Fichier entrant", bg=CARD, fg=ACCENT, font=(FONT, 13, "bold")).pack(pady=(22, 8))
            tk.Label(d, text=f"{info['from']}  ({info['ip']})\nveut t'envoyer :", bg=CARD, fg=MUTED,
                     font=(FONT, 10)).pack()
            tk.Label(d, text=f"{what}\n{core.fmt_size(sz)}", bg=CARD, fg=TEXT, font=(FONT, 12, "bold"),
                     wraplength=390).pack(pady=8)

            def finish(v):
                if not ev.is_set():
                    out["ok"] = v
                    ev.set()
                try:
                    d.destroy()
                except Exception:
                    pass

            row = tk.Frame(d, bg=CARD)
            row.pack(pady=8)
            FlatButton(row, "Accepter", lambda: finish(True), bg=OK, hover=mix(OK, "#FFFFFF", 0.3),
                       fg="#04121A", padx=26).pack(side="left", padx=6)
            FlatButton(row, "Refuser", lambda: finish(False), padx=26).pack(side="left", padx=6)
            d.protocol("WM_DELETE_WINDOW", lambda: finish(False))
            d.after(85000, lambda: finish(False))

        ui_q.put(build)
        ev.wait(90)
        return out["ok"]

    def on_progress(self, key, pct, speed, eta, label):
        def u():
            if pct <= 0:
                self.prog.pop(key, None)
            else:
                self.prog[key] = (min(pct, 100), speed, eta, label)
        ui_q.put(u)

    def on_done(self, r):
        def u():
            arrow = "\u2193" if r["dir"] == "in" else "\u2191"
            if r["kind"] == "bench":
                self.set_status(f"Test de vitesse ({r['peer']}) : {core.fmt_speed(r['speed'])} "
                                f"= {r['speed'] * 8 / 1e6:.0f} Mbit/s \u2705")
                return
            self.cfg["history"].insert(0, {"t": time.strftime("%d/%m %H:%M"), "dir": r["dir"], "name": r["name"],
                                           "size": r["size"], "speed": r["speed"], "peer": r["peer"], "path": r["path"]})
            del self.cfg["history"][100:]
            save_cfg(self.cfg)
            self.fill_hist()
            verb = "Reçu" if r["dir"] == "in" else "Envoyé"
            self.set_status(f"{arrow} {verb} : {r['name']} ({core.fmt_size(r['size'])}) à {core.fmt_speed(r['speed'])} \u2705")
        ui_q.put(u)

    def on_error(self, msg):
        ui_q.put(lambda: self.set_status(msg))

    def on_relay_state(self, ok, msg=""):
        def u():
            self.relay_lbl.config(text="\u25cf Connecté au relais, en attente" if ok else f"\u25cf Relais injoignable : {msg}",
                                  fg=OK if ok else ERR)
        ui_q.put(u)

    def set_status(self, t):
        col = OK if "\u2705" in t else (ERR if ("Erreur" in t or "refus" in t or "injoignable" in t) else TEXT)
        self.status.config(text=t, fg=col)

    # ---------- actions ----------
    def add_paths(self, paths):
        self.chosen += [p for p in paths if p not in self.chosen]
        self.items = core.expand_paths(self.chosen)
        self.lst.delete(0, "end")
        for p in self.chosen:
            self.lst.insert("end", ("\U0001f4c1 " if os.path.isdir(p) else "\U0001f4c4 ") + os.path.basename(p.rstrip("/\\")))
        total = sum(os.path.getsize(p) for p, _ in self.items if os.path.exists(p))
        self.files_lbl.config(text=f"{len(self.items)} fichier(s) \u2022 {core.fmt_size(total)}", fg=TEXT)

    def pick(self):
        fs = filedialog.askopenfilenames(title="Choisis les fichiers à envoyer")
        if fs:
            self.add_paths(list(fs))

    def pick_dir(self):
        d = filedialog.askdirectory(title="Choisis un dossier à envoyer")
        if d:
            self.add_paths([d])

    def clear(self):
        self.chosen, self.items = [], []
        self.lst.delete(0, "end")
        self.files_lbl.config(text="Aucun fichier choisi", fg=MUTED)

    def open_dir(self):
        try:
            os.makedirs(self.cfg["recv_dir"], exist_ok=True)
            os.startfile(self.cfg["recv_dir"])
        except Exception:
            pass

    def change_dir(self):
        d = filedialog.askdirectory()
        if d:
            self.cfg["recv_dir"] = d
            self.dir_lbl.config(text=d)
            self.style_recv()
            save_cfg(self.cfg)

    def save_settings(self):
        self.cfg["name"] = self.name_var.get().strip() or core.NAME
        self.cfg["auto_accept"] = self.auto_var.get()
        self.hk.auto_accept = self.cfg["auto_accept"]
        core.NAME = self.cfg["name"]
        save_cfg(self.cfg)
        self.set_status("Réglages enregistrés \u2705")

    def clear_hist(self):
        self.cfg["history"] = []
        save_cfg(self.cfg)
        self.fill_hist()

    def fill_hist(self):
        self.hlist.delete(0, "end")
        for h in self.cfg["history"]:
            a = "\u2193 reçu " if h["dir"] == "in" else "\u2191 envoyé"
            self.hlist.insert("end", f"{h['t']}  {a}  {h['name'][:34]:34} {core.fmt_size(h['size']):>9}  "
                                     f"{core.fmt_speed(h['speed']):>11}  {h['peer'][:16]}")

    def toggle_receive(self):
        self.set_receive(not core.receiving)

    def set_receive(self, on):
        core.receiving = on
        self.cfg["receive_on"] = on
        save_cfg(self.cfg)
        if on:
            if self.cfg["listen_room"] and self.cfg["relay"] and len(self.cfg["room"]) >= 4:
                self.start_room()
            self.set_status("Réception activée : tes amis te voient et peuvent t'envoyer des fichiers \u2705")
        else:
            self.relay.stop()
            self.relay_lbl.config(text="", fg=MUTED)
            self.set_status("Réception arrêtée : personne ne peut t'envoyer de fichiers.")
        self.style_recv()

    def style_recv(self):
        on = core.receiving
        col = ERR if on else OK
        b = self.rcv_btn
        b.config(text="\u25a0  Arrêter la réception" if on else "\u25b6  Recevoir", bg=col, fg="#04121A")
        b._base, b._hov = col, mix(col, "#FFFFFF", 0.3)
        self.chip.config(text="\u25cf  Prêt à recevoir" if on else "\u25cb  Réception arrêtée", fg=OK if on else MUTED)
        self.rdir_lbl.config(text="Les fichiers arrivent dans : " + self.cfg["recv_dir"])

    def copy_addr(self):
        a, _ = my_address()
        if a:
            self.root.clipboard_clear()
            self.root.clipboard_append(a)
            self.set_status(f"Adresse copiée : {a} \u2705")

    def gen_room(self):
        self.room_var.set("".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(8)))
        self.apply_room()

    def apply_room(self):
        self.cfg.update(relay=self.relay_var.get().strip(), room=self.room_var.get().strip(),
                        listen_room=self.listen_var.get(), send_room=self.sendroom_var.get())
        save_cfg(self.cfg)
        if core.receiving and self.cfg["listen_room"] and self.cfg["relay"] and len(self.cfg["room"]) >= 4:
            self.start_room()
        else:
            self.relay.stop()
            self.relay_lbl.config(text="", fg=MUTED)

    def start_room(self):
        h, p = hostport(self.cfg["relay"], core.RELAY_PORT)
        self.relay.start(h, p, self.cfg["room"])

    def targets(self):
        t = []
        for ip in sorted(self.selected):
            if ip in core.peers:
                t.append(({"ip": ip}, core.peers[ip][0]))
        m = self.ip_entry.get().strip()
        if m:
            h, p = hostport(m, core.TCP_PORT)
            if h not in [x[0].get("ip") for x in t]:
                t.append(({"ip": h, "port": p}, m))
        if self.sendroom_var.get() and self.room_var.get().strip() and self.relay_var.get().strip():
            rh, rp = hostport(self.relay_var.get(), core.RELAY_PORT)
            t.append(({"room": self.room_var.get().strip(), "relay_host": rh, "relay_port": rp},
                      "salle " + self.room_var.get().strip()))
        return t

    def send(self):
        t = self.targets()
        if not t or not self.items:
            messagebox.showwarning("JRSDrop", "Choisis au moins un PC (radar, adresse ou salle) et au moins un fichier.")
            return
        for tg, label in t:
            threading.Thread(target=core.send_files, args=(tg, label, list(self.items), self.hk), daemon=True).start()

    def bench(self):
        t = self.targets()
        if not t:
            messagebox.showwarning("JRSDrop", "Choisis d'abord un PC (radar, adresse ou salle).")
            return
        self.set_status("Test de vitesse en cours (200 Mo)...")
        for tg, label in t:
            threading.Thread(target=core.bench_send, args=(tg, label, 200, self.hk), daemon=True).start()

    # ---------- radar ----------
    def hit(self, x, y):
        for ip, (nx, ny) in list(self.nodes.items()):
            if (nx - x) ** 2 + (ny - y) ** 2 <= 22 ** 2:
                return ip

    def on_click(self, e):
        if (e.x - CX) ** 2 + (e.y - CY) ** 2 <= 20 ** 2:
            ips = {i for i in core.peers if core.peer_recv.get(i, True)}
            self.selected = set() if (ips and self.selected >= ips) else ips
            return
        ip = self.hit(e.x, e.y)
        if ip:
            if not core.peer_recv.get(ip, True):
                self.set_status(f"{core.peers[ip][0]} n'est pas en mode réception : demande-lui de cliquer sur « Recevoir ».")
                return
            self.selected ^= {ip}

    def on_move(self, e):
        over = self.hit(e.x, e.y) or ((e.x - CX) ** 2 + (e.y - CY) ** 2 <= 20 ** 2)
        self.cv.config(cursor="hand2" if over else "")

    def tick(self):
        now = time.time()
        t = now - self.t0
        if self.pages["send"].winfo_ismapped():
            self.draw_radar(now, t)
            self.draw_progress(t)
        elif self.pages["recv"].winfo_ismapped():
            self.draw_receive(t)
            self.draw_progress(t, self.pb2, self.stat2)
        self.root.after(33, self.tick)

    def draw_radar(self, now, t):
        cv = self.cv
        cv.delete("all")
        cv.create_oval(CX - R, CY - R, CX + R, CY + R, fill=PANEL, outline="")
        a = (t * 110) % 360
        for i in range(26):
            cv.create_arc(CX - R, CY - R, CX + R, CY + R, start=a - (i + 1) * 3, extent=3,
                          fill=mix(ACCENT, PANEL, 0.6 + i / 26 * 0.4), outline="", style="pieslice")
        for r in (R / 3, 2 * R / 3, R):
            cv.create_oval(CX - r, CY - r, CX + r, CY + r, outline=LINE, width=1)
        cv.create_line(CX - R, CY, CX + R, CY, fill=CARD2)
        cv.create_line(CX, CY - R, CX, CY + R, fill=CARD2)
        for k in range(2):
            p = (t * 0.45 + k * 0.5) % 1
            r = 16 + (R - 16) * p
            cv.create_oval(CX - r, CY - r, CX + r, CY + r, outline=mix(ACCENT, PANEL, 0.15 + p * 0.85), width=2)
        cv.create_oval(CX - 15, CY - 15, CX + 15, CY + 15, fill=ACCENT, outline=mix(ACCENT, BG, 0.5), width=4)
        cv.create_text(CX, CY, text="MOI", fill="#04121A", font=(FONT, 7, "bold"))
        self.nodes = {}
        for ip, (name, _) in list(core.peers.items()):
            born = self.born.setdefault(ip, now)
            k = min(1.0, (now - born) / 0.6)
            k = 1 - (1 - k) ** 3
            h = zlib.crc32(ip.encode())
            ang = math.radians(h % 360)
            rad = 48 + ((h >> 8) % 58)
            x = CX + math.cos(ang) * rad
            y = CY + math.sin(ang) * rad * 0.85 + math.sin(t * 2 + (h % 7)) * 3
            self.nodes[ip] = (x, y)
            rv = core.peer_recv.get(ip, True)
            sel = ip in self.selected and rv
            col = "#3A4470" if not rv else (OK if sel else ACCENT2)
            r = 14 * k
            if sel:
                halo = 6 + 3 * math.sin(t * 4)
                cv.create_oval(x - r - halo, y - r - halo, x + r + halo, y + r + halo,
                               outline=mix(col, PANEL, 0.5), width=2)
            cv.create_oval(x - r, y - r, x + r, y + r, fill=col,
                           outline="#FFFFFF" if sel else mix(col, "#FFFFFF", 0.4), width=2)
            if k > 0.6:
                cv.create_text(x, y, text="\u2713" if sel else "PC", fill="#FFFFFF", font=(FONT, 8, "bold"))
                cv.create_text(x, y + 26, text=name[:14] + ("" if rv else " · off"), fill=TEXT if sel else MUTED, font=(FONT, 8))
        n = len(core.peers)
        msg = (f"{n} PC détecté(s) \u2022 {len(self.selected)} choisi(s)" if n
               else "Recherche des PC à proximité" + "." * (int(t * 2) % 4))
        cv.create_text(CX, RH - 8, text=msg, fill=MUTED, font=(FONT, 9))

    def draw_receive(self, t):
        cv = self.rcv
        cv.delete("all")
        cx, cy = 130, 100
        if core.receiving:
            for k in range(3):
                p = (t * 0.5 + k / 3) % 1
                r = 24 + 76 * p
                cv.create_oval(cx - r, cy - r, cx + r, cy + r, outline=mix(OK, BG, 0.1 + p * 0.9), width=2)
            cv.create_oval(cx - 26, cy - 26, cx + 26, cy + 26, fill=OK, outline=mix(OK, BG, 0.5), width=4)
            cv.create_text(cx, cy, text="\u2193", fill="#04121A", font=(FONT, 20, "bold"))
            msg, col = "En attente de fichiers" + "." * (int(t * 2) % 4), OK
        else:
            cv.create_oval(cx - 26, cy - 26, cx + 26, cy + 26, fill=CARD2, outline=LINE, width=3)
            cv.create_text(cx, cy, text="OFF", fill=MUTED, font=(FONT, 10, "bold"))
            msg, col = "Réception désactivée", MUTED
        cv.create_text(cx, 195, text=msg, fill=col, font=(FONT, 10))

    def draw_progress(self, t, pb=None, lbl=None):
        main = pb is None
        pb, lbl = pb or self.pb, lbl or self.stat_lbl
        vals = list(self.prog.values())
        self.ptarget = sum(v[0] for v in vals) / len(vals) if vals else 0
        self.pshow += (self.ptarget - self.pshow) * 0.15
        pb.delete("all")
        w = max(pb.winfo_width(), 10)
        pb.create_rectangle(0, 2, w, 8, fill=CARD2, outline="")
        fw = w * self.pshow / 100
        if fw > 1:
            pb.create_rectangle(0, 2, fw, 8, fill=ACCENT, outline="")
            sx = (t * 220) % (fw + 60) - 60
            x1, x2 = max(0, sx), min(fw, sx + 50)
            if x2 > x1:
                pb.create_rectangle(x1, 2, x2, 8, fill=mix(ACCENT, "#FFFFFF", 0.55), outline="")
        if vals:
            sp = sum(v[1] for v in vals)
            eta = max(v[2] for v in vals)
            names = ", ".join(sorted({v[3] for v in vals}))[:60]
            txt = f"{self.ptarget:.0f}%  \u2022  {core.fmt_speed(sp)}  \u2022  reste {core.fmt_eta(eta)}  \u2022  {names}"
        else:
            txt = ""
        if txt != lbl.cget("text"):
            lbl.config(text=txt)
        if not main:
            return
        n = len(self.targets())
        s = f"\U0001f680  Envoyer à {n} destination(s)" if n else "\U0001f680  Envoyer"
        if s != self.send_text:
            self.send_text = s
            self.send_btn.config(text=s)
            self.dest_lbl.config(text="Choisis des PC sur le radar, ou une adresse / salle dans l'onglet « À distance ».")

    def refresh(self):
        now = time.time()
        for ip in [i for i, (_, ts) in list(core.peers.items()) if now - ts > 8]:
            core.peers.pop(ip, None)
            self.born.pop(ip, None)
            self.selected.discard(ip)
            core.peer_recv.pop(ip, None)
        self.me_lbl.config(text=f"{core.NAME}\n" + "\n".join(core.MY_IPS or ["pas de réseau"]))
        a, ts = my_address()
        if ts:
            self.addr_lbl.config(text="\U0001f30d  " + a)
            self.addr_hint.config(text="Adresse Tailscale : elle marche depuis n'importe quel pays. Ton ami doit aussi avoir "
                                       "Tailscale et partager son PC avec toi (et toi le tien avec lui).")
        else:
            self.addr_lbl.config(text=a or "pas de réseau")
            self.addr_hint.config(text="Adresse du réseau local : elle marche seulement sur le même Wi-Fi. Pour l'étranger, "
                                       "installe Tailscale : ton adresse en 100.x.x.x apparaîtra ici.")
        self.root.after(1000, self.refresh)

    def poll(self):
        try:
            while True:
                fn = ui_q.get_nowait()
                try:
                    fn()
                except Exception:
                    pass
        except queue.Empty:
            pass
        self.root.after(80, self.poll)


if __name__ == "__main__":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AfricaGolden.JRSDrop")
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    cfg = load_cfg()
    core.NAME = cfg["name"] or core.NAME
    core.MY_IPS = core.local_ips()
    root = TkinterDnD.Tk() if HAS_DND else tk.Tk()
    app = App(root, cfg)
    threading.Thread(target=core.announce_loop, daemon=True).start()
    threading.Thread(target=core.listen_loop, args=(app.on_error,), daemon=True).start()
    threading.Thread(target=core.serve_direct, args=(app.hk,), daemon=True).start()
    root.mainloop()