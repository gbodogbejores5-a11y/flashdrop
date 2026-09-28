import socket, threading, json, os, struct, time, queue, math, zlib
import tkinter as tk
from tkinter import filedialog, messagebox

APP_NAME = "FlashDrop"
VERSION = "2.0"
TCP_PORT = 50555          # port des transferts de fichiers
UDP_PORT = 50556          # port de découverte des PC
CHUNK = 1024 * 1024       # blocs de 1 Mo
NAME = socket.gethostname()

# ---------- Couleurs et police ----------
BG = "#0A0F1F"
PANEL = "#0D1530"
CARD = "#121A33"
CARD2 = "#1B2650"
LINE = "#24306A"
ACCENT = "#22D3EE"
ACCENT2 = "#8B5CF6"
TEXT = "#E8ECFF"
MUTED = "#8A94B8"
OK = "#34D399"
ERR = "#F87171"
FONT = "Segoe UI"

peers = {}                # ip -> (nom, dernier_signe_de_vie)
ui_q = queue.Queue()      # file d'attente pour parler à l'interface depuis les threads
MY_IPS = []
APP = None
recv_dir = os.path.join(os.path.expanduser("~"), "Downloads", "FlashDrop")
os.makedirs(recv_dir, exist_ok=True)


# ---------- BLOC 1 : outils ----------
def local_ips():
    """Toutes les adresses IPv4 de ce PC (sauf 127.x)."""
    try:
        return [i for i in socket.gethostbyname_ex(NAME)[2] if not i.startswith("127.")]
    except Exception:
        return []


def recv_exact(sock, n):
    """Lit exactement n octets (TCP peut couper en morceaux)."""
    buf = b""
    while len(buf) < n:
        part = sock.recv(n - len(buf))
        if not part:
            raise ConnectionError("Connexion coupée")
        buf += part
    return buf


def fmt_size(n):
    for u in ["o", "Ko", "Mo", "Go"]:
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} To"


def mix(c1, c2, f):
    """Mélange deux couleurs #rrggbb (f=0 -> c1, f=1 -> c2). Sert aux dégradés et aux fondus."""
    f = max(0.0, min(1.0, f))
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(a[i] * (1 - f) + b[i] * f) for i in range(3))


# ---------- BLOC 2 : découverte des PC (UDP broadcast) ----------
def announce_loop():
    """Toutes les 2 s, on crie 'je suis là' sur chaque carte réseau."""
    global MY_IPS
    msg = json.dumps({"app": "flashdrop", "name": NAME}).encode()
    while True:
        MY_IPS = local_ips()
        for ip in MY_IPS:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                s.bind((ip, 0))
                s.sendto(msg, ("255.255.255.255", UDP_PORT))
                s.close()
            except Exception:
                pass
        time.sleep(2)


def listen_loop(set_status):
    """On écoute les 'je suis là' des autres PC."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("", UDP_PORT))
    except Exception as e:
        set_status(f"Erreur découverte des PC : {e}")
        return
    while True:
        try:
            data, (ip, _) = s.recvfrom(1024)
            if ip in MY_IPS:
                continue
            d = json.loads(data)
            if d.get("app") == "flashdrop":
                peers[ip] = (str(d.get("name", ip)), time.time())
        except Exception:
            pass


# ---------- BLOC 3 : réception ----------
def ask_user(text):
    """Pose une question à l'utilisateur depuis un thread (via la file d'attente)."""
    ev, res = threading.Event(), {"ok": False}

    def _ask():
        try:
            if APP:
                APP.root.deiconify()
                APP.root.lift()
                APP.root.bell()
            res["ok"] = messagebox.askyesno("FlashDrop", text)
        finally:
            ev.set()

    ui_q.put(_ask)
    ev.wait(60)
    return res["ok"]


def unique_path(folder, name):
    """Évite d'écraser un fichier existant : photo.jpg -> photo (1).jpg"""
    base, ext = os.path.splitext(name)
    path, i = os.path.join(folder, name), 1
    while os.path.exists(path):
        path = os.path.join(folder, f"{base} ({i}){ext}")
        i += 1
    return path


def handle_incoming(conn, addr, set_status, set_progress):
    key = "in-" + addr[0] + ":" + str(addr[1])
    with conn:
        try:
            conn.settimeout(120)
            n = struct.unpack("!I", recv_exact(conn, 4))[0]
            if n > 65536:
                return
            meta = json.loads(recv_exact(conn, n))
            name = os.path.basename(meta["name"])   # sécurité : pas de chemin
            size = int(meta["size"])
            ok = ask_user(f"{meta.get('from', addr[0])} veut t'envoyer :\n{name} ({fmt_size(size)})\n\nAccepter ?")
            conn.sendall(b"1" if ok else b"0")
            if not ok:
                return
            dest = unique_path(recv_dir, name)
            got = 0
            with open(dest, "wb") as f:
                while got < size:
                    b = conn.recv(min(CHUNK, size - got))
                    if not b:
                        raise ConnectionError("Transfert interrompu")
                    f.write(b)
                    got += len(b)
                    set_progress(key, got * 100 / max(size, 1))
            conn.sendall(b"1")   # confirmation finale pour l'expéditeur
            set_status(f"Reçu : {os.path.basename(dest)} ✅")
        except Exception as e:
            set_status(f"Erreur réception : {e}")
        finally:
            set_progress(key, 0)


def server_loop(set_status, set_progress):
    try:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("", TCP_PORT))
        srv.listen(10)
    except Exception as e:
        set_status(f"Erreur : port {TCP_PORT} déjà utilisé (FlashDrop est peut-être déjà ouvert) : {e}")
        return
    while True:
        conn, addr = srv.accept()
        threading.Thread(target=handle_incoming, args=(conn, addr, set_status, set_progress), daemon=True).start()


# ---------- BLOC 4 : envoi (vers UN PC, appelé en parallèle pour plusieurs) ----------
def send_files(ip, label, paths, set_status, set_progress):
    key = "out-" + ip
    for p in paths:
        try:
            size = os.path.getsize(p)
            name = os.path.basename(p)
            set_status(f"→ {label} : {name} (en attente d'acceptation)")
            with socket.create_connection((ip, TCP_PORT), timeout=10) as s:
                hdr = json.dumps({"name": name, "size": size, "from": NAME}).encode()
                s.sendall(struct.pack("!I", len(hdr)) + hdr)
                s.settimeout(120)
                if recv_exact(s, 1) != b"1":
                    set_status(f"{label} a refusé {name}")
                    continue
                sent = 0
                with open(p, "rb") as f:
                    while True:
                        b = f.read(CHUNK)
                        if not b:
                            break
                        s.sendall(b)
                        sent += len(b)
                        set_progress(key, sent * 100 / max(size, 1))
                recv_exact(s, 1)   # attend la confirmation de fin
            set_status(f"Envoyé à {label} : {name} ✅")
        except Exception as e:
            set_status(f"Erreur envoi vers {label} : {e}")
    set_progress(key, 0)


# ---------- BLOC 5 : interface ----------
class FlatButton(tk.Label):
    """Bouton moderne : plat, coloré, avec effet au survol."""

    def __init__(self, master, text, command, bg=CARD2, hover=LINE, fg=TEXT,
                 font=(FONT, 10, "bold"), padx=16, pady=8):
        super().__init__(master, text=text, bg=bg, fg=fg, font=font, padx=padx, pady=pady, cursor="hand2")
        self._cmd, self._base, self._hov = command, bg, hover
        self.bind("<Enter>", lambda e: self.config(bg=self._hov))
        self.bind("<Leave>", lambda e: self.config(bg=self._base))
        self.bind("<Button-1>", lambda e: self._cmd())


# dimensions du radar
RW, RH = 520, 276
CX, CY, R = 260, 132, 118


class App:
    def __init__(self, root):
        self.root = root
        root.title(f"{APP_NAME} {VERSION} - transfert PC à PC")
        root.geometry("560x720")
        root.resizable(False, False)
        root.configure(bg=BG)

        self.files = []
        self.selected = set()     # IP des PC cochés sur le radar
        self.born = {}            # ip -> moment d'apparition (pour l'animation d'entrée)
        self.nodes = {}           # ip -> (x, y) sur le radar (pour les clics)
        self.prog = {}            # clé de transfert -> pourcentage
        self.pshow = 0.0          # valeur affichée de la barre (animée en douceur)
        self.ptarget = 0.0
        self.t0 = time.time()
        self.send_text = ""

        # --- en-tête ---
        head = tk.Frame(root, bg=BG)
        head.pack(fill="x", padx=20, pady=(16, 4))
        tk.Label(head, text="⚡", bg=BG, fg=ACCENT, font=(FONT, 26)).pack(side="left")
        box = tk.Frame(head, bg=BG)
        box.pack(side="left", padx=8)
        tk.Label(box, text=APP_NAME, bg=BG, fg=TEXT, font=(FONT, 18, "bold")).pack(anchor="w")
        self.me_lbl = tk.Label(box, text="", bg=BG, fg=MUTED, font=(FONT, 9))
        self.me_lbl.pack(anchor="w")
        FlatButton(head, "📶 Point d'accès", self.open_hotspot, padx=12, pady=6).pack(side="right")

        # --- radar ---
        self.cv = tk.Canvas(root, width=RW, height=RH, bg=BG, highlightthickness=0)
        self.cv.pack(padx=20, pady=(6, 0))
        self.cv.bind("<Button-1>", self.on_click)
        self.cv.bind("<Motion>", self.on_move)
        tk.Label(root, text="Clique sur un PC du radar pour le choisir (clique sur « MOI » pour tout choisir)",
                 bg=BG, fg=MUTED, font=(FONT, 8)).pack()

        # --- fichiers ---
        card = tk.Frame(root, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        card.pack(fill="x", padx=20, pady=10)
        inner = tk.Frame(card, bg=CARD)
        inner.pack(fill="x", padx=14, pady=12)
        self.files_lbl = tk.Label(inner, text="📂  Aucun fichier choisi", bg=CARD, fg=TEXT,
                                  font=(FONT, 11), anchor="w")
        self.files_lbl.pack(side="left", fill="x", expand=True)
        FlatButton(inner, "Choisir des fichiers", self.pick, padx=14, pady=6).pack(side="right")

        # --- bouton envoyer ---
        self.send_btn = FlatButton(root, "🚀  Envoyer", self.send, bg=ACCENT,
                                   hover=mix(ACCENT, "#FFFFFF", 0.3), fg="#04121A",
                                   font=(FONT, 13, "bold"), pady=12)
        self.send_btn.pack(fill="x", padx=20, pady=4)

        # --- progression + statut ---
        self.pb = tk.Canvas(root, height=10, bg=BG, highlightthickness=0)
        self.pb.pack(fill="x", padx=20, pady=(10, 2))
        self.status = tk.Label(root, text="Prêt. Lance FlashDrop sur l'autre PC pour le voir apparaître.",
                               bg=BG, fg=MUTED, font=(FONT, 10), wraplength=510, justify="left", anchor="w")
        self.status.pack(fill="x", padx=20, pady=4)

        # --- IP manuelle ---
        row = tk.Frame(root, bg=BG)
        row.pack(fill="x", padx=20, pady=4)
        tk.Label(row, text="IP manuelle", bg=BG, fg=MUTED, font=(FONT, 9)).pack(side="left")
        self.ip_entry = tk.Entry(row, bg=CARD2, fg=TEXT, insertbackground=TEXT, relief="flat",
                                 font=(FONT, 10), highlightthickness=1,
                                 highlightbackground=LINE, highlightcolor=ACCENT)
        self.ip_entry.pack(side="left", fill="x", expand=True, padx=8, ipady=4)

        # --- dossier de réception ---
        row2 = tk.Frame(root, bg=BG)
        row2.pack(fill="x", padx=20, pady=4)
        self.dir_lbl = tk.Label(row2, text="", bg=BG, fg=MUTED, font=(FONT, 9),
                                anchor="w", wraplength=330, justify="left")
        self.dir_lbl.pack(side="left", fill="x", expand=True)
        FlatButton(row2, "Ouvrir", self.open_dir, padx=10, pady=4, font=(FONT, 9, "bold")).pack(side="right", padx=(6, 0))
        FlatButton(row2, "Changer", self.change_dir, padx=10, pady=4, font=(FONT, 9, "bold")).pack(side="right")
        self.dir_lbl.config(text=f"Reçus dans : {recv_dir}")

        self.refresh()
        self.poll()
        self.tick()

    # --- mises à jour depuis les threads (toujours via la file d'attente) ---
    def set_status(self, t):
        def _u():
            col = OK if "✅" in t else (ERR if ("Erreur" in t or "refus" in t) else TEXT)
            self.status.config(text=t, fg=col)
        ui_q.put(_u)

    def set_progress(self, key, v):
        def _u():
            if v <= 0:
                self.prog.pop(key, None)
            else:
                self.prog[key] = min(v, 100)
            self.ptarget = (sum(self.prog.values()) / len(self.prog)) if self.prog else 0
        ui_q.put(_u)

    # --- actions des boutons ---
    def open_hotspot(self):
        try:
            os.startfile("ms-settings:network-mobilehotspot")
        except Exception:
            messagebox.showinfo("FlashDrop", "Ouvre : Paramètres → Réseau et Internet → Point d'accès mobile.")

    def open_dir(self):
        try:
            os.startfile(recv_dir)
        except Exception:
            pass

    def pick(self):
        fs = filedialog.askopenfilenames(title="Choisis les fichiers à envoyer")
        if fs:
            self.files = list(fs)
            total = sum(os.path.getsize(f) for f in self.files if os.path.exists(f))
            self.files_lbl.config(text=f"📂  {len(self.files)} fichier(s) • {fmt_size(total)}")

    def change_dir(self):
        global recv_dir
        d = filedialog.askdirectory()
        if d:
            recv_dir = d
            self.dir_lbl.config(text=f"Reçus dans : {recv_dir}")

    def targets(self):
        t = []
        for ip in sorted(self.selected):
            if ip in peers:
                t.append((ip, peers[ip][0]))
        m = self.ip_entry.get().strip()
        if m and m not in [x[0] for x in t]:
            t.append((m, m))
        return t

    def send(self):
        t = self.targets()
        if not t or not self.files:
            messagebox.showwarning("FlashDrop", "Choisis au moins un PC (sur le radar ou par IP) et au moins un fichier.")
            return
        for ip, label in t:   # un thread par PC => envois en parallèle
            threading.Thread(target=send_files, args=(ip, label, self.files, self.set_status, self.set_progress),
                             daemon=True).start()

    # --- radar : clics ---
    def hit(self, x, y):
        for ip, (nx, ny) in list(self.nodes.items()):
            if (nx - x) ** 2 + (ny - y) ** 2 <= 22 ** 2:
                return ip
        return None

    def on_click(self, e):
        if (e.x - CX) ** 2 + (e.y - CY) ** 2 <= 20 ** 2:      # clic sur "MOI" : tout / rien
            ips = set(peers.keys())
            self.selected = set() if (ips and self.selected >= ips) else ips
            return
        ip = self.hit(e.x, e.y)
        if ip:
            if ip in self.selected:
                self.selected.discard(ip)
            else:
                self.selected.add(ip)

    def on_move(self, e):
        over = self.hit(e.x, e.y) or ((e.x - CX) ** 2 + (e.y - CY) ** 2 <= 20 ** 2)
        self.cv.config(cursor="hand2" if over else "")

    # --- animation (30 images/seconde) ---
    def tick(self):
        now = time.time()
        t = now - self.t0
        cv = self.cv
        cv.delete("all")

        # disque du radar + faisceau qui tourne (dégradé de 26 petites parts)
        cv.create_oval(CX - R, CY - R, CX + R, CY + R, fill=PANEL, outline="")
        a = (t * 110) % 360
        for i in range(26):
            cv.create_arc(CX - R, CY - R, CX + R, CY + R, start=a - (i + 1) * 3, extent=3,
                          fill=mix(ACCENT, PANEL, 0.6 + i / 26 * 0.4), outline="", style="pieslice")

        # cercles et croix
        for r in (R / 3, 2 * R / 3, R):
            cv.create_oval(CX - r, CY - r, CX + r, CY + r, outline=LINE, width=1)
        cv.create_line(CX - R, CY, CX + R, CY, fill=CARD2)
        cv.create_line(CX, CY - R, CX, CY + R, fill=CARD2)

        # ondes qui partent du centre
        for k in range(2):
            p = (t * 0.45 + k * 0.5) % 1
            r = 16 + (R - 16) * p
            cv.create_oval(CX - r, CY - r, CX + r, CY + r,
                           outline=mix(ACCENT, PANEL, 0.15 + p * 0.85), width=2)

        # mon PC au centre
        cv.create_oval(CX - 15, CY - 15, CX + 15, CY + 15, fill=ACCENT, outline=mix(ACCENT, BG, 0.5), width=4)
        cv.create_text(CX, CY, text="MOI", fill="#04121A", font=(FONT, 7, "bold"))

        # les autres PC
        self.nodes = {}
        for ip, (name, _) in list(peers.items()):
            born = self.born.setdefault(ip, now)
            k = min(1.0, (now - born) / 0.6)
            k = 1 - (1 - k) ** 3                      # animation d'apparition en douceur
            h = zlib.crc32(ip.encode())
            ang = math.radians(h % 360)
            rad = 48 + ((h >> 8) % 58)
            x = CX + math.cos(ang) * rad
            y = CY + math.sin(ang) * rad * 0.85 + math.sin(t * 2 + (h % 7)) * 3
            self.nodes[ip] = (x, y)
            sel = ip in self.selected
            col = OK if sel else ACCENT2
            r = 14 * k
            if sel:
                halo = 6 + 3 * math.sin(t * 4)
                cv.create_oval(x - r - halo, y - r - halo, x + r + halo, y + r + halo,
                               outline=mix(col, PANEL, 0.5), width=2)
            cv.create_oval(x - r, y - r, x + r, y + r, fill=col,
                           outline="#FFFFFF" if sel else mix(col, "#FFFFFF", 0.4), width=2)
            if k > 0.6:
                cv.create_text(x, y, text="✓" if sel else "PC", fill="#FFFFFF", font=(FONT, 8, "bold"))
                cv.create_text(x, y + 26, text=name[:18], fill=TEXT if sel else MUTED, font=(FONT, 8))

        # texte du bas
        if peers:
            msg = f"{len(peers)} PC détecté(s) • {len(self.selected)} choisi(s)"
        else:
            msg = "Recherche des PC à proximité" + "." * (int(t * 2) % 4)
        cv.create_text(CX, RH - 8, text=msg, fill=MUTED, font=(FONT, 9))

        # barre de progression animée
        self.pshow += (self.ptarget - self.pshow) * 0.15
        pb = self.pb
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

        # texte du bouton envoyer
        n = len(self.targets())
        txt = f"🚀  Envoyer à {n} PC" if n else "🚀  Envoyer"
        if txt != self.send_text:
            self.send_text = txt
            self.send_btn.config(text=txt)

        self.root.after(33, self.tick)

    def refresh(self):
        """Toutes les secondes : retire les PC disparus et met à jour l'en-tête."""
        now = time.time()
        for ip in [i for i, (_, ts) in list(peers.items()) if now - ts > 8]:
            peers.pop(ip, None)
            self.born.pop(ip, None)
            self.selected.discard(ip)
        self.me_lbl.config(text=f"{NAME}  •  {', '.join(MY_IPS) or 'pas de réseau'}")
        self.root.after(1000, self.refresh)

    def poll(self):
        """Exécute les actions demandées par les threads (thread-safe)."""
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
    MY_IPS = local_ips()
    root = tk.Tk()
    app = App(root)
    APP = app
    threading.Thread(target=announce_loop, daemon=True).start()
    threading.Thread(target=listen_loop, args=(app.set_status,), daemon=True).start()
    threading.Thread(target=server_loop, args=(app.set_status, app.set_progress), daemon=True).start()
    root.mainloop()