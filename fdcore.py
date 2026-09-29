#!/usr/bin/env python3
"""JRSDrop core : protocole, decouverte, envoi, reception, relais. Sans interface.
Utilise par jrsdrop.py (Windows, interface) et jrsdrop_cli.py (Linux, terminal)."""
import socket, threading, json, os, struct, time, subprocess, itertools, uuid, shutil

VERSION = "3.0"
TCP_PORT = 50555          # transferts de fichiers
UDP_PORT = 50556          # decouverte des PC (reseau local)
RELAY_PORT = 50600        # port par defaut du serveur relais (mode distance)
CHUNK = 4 * 1024 * 1024          # blocs de 4 Mo
SOCKBUF = 8 * 1024 * 1024        # gros tampons reseau (vitesse sur internet longue distance)
NAME = socket.gethostname()
DEVICE_ID = uuid.uuid4().hex[:8]
peers = {}                # ip -> (nom, dernier signe de vie)
MY_IPS = []
receiving = True          # False = mode reception coupe : on refuse tout envoi
peer_recv = {}            # ip -> ce PC est-il en mode reception ?

_ids = itertools.count(1)
_batches = {}             # id de lot -> (accepte, heure)
_blk = threading.Lock()


# ---------- outils ----------
def local_ips():
    ips = set()
    try:
        ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    if os.name != "nt":
        try:
            out = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=3).stdout
            ips.update(i for i in out.split() if "." in i and ":" not in i)
        except Exception:
            pass
    return sorted(i for i in ips if not i.startswith(("127.", "169.254.")))


def recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        part = sock.recv(n - len(buf))
        if not part:
            raise ConnectionError("Connexion coupée")
        buf += part
    return buf


def tune(s):
    """Agrandit les tampons reseau pour ne jamais brider la vitesse."""
    for o in (socket.SO_SNDBUF, socket.SO_RCVBUF):
        try:
            s.setsockopt(socket.SOL_SOCKET, o, SOCKBUF)
        except OSError:
            pass
    return s


def fmt_size(n):
    for u in ["o", "Ko", "Mo", "Go"]:
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} To"


def fmt_speed(bps):
    return fmt_size(bps) + "/s"


def fmt_eta(s):
    s = int(max(0, s))
    return f"{s // 60}:{s % 60:02d}" if s < 3600 else f"{s // 3600}h{(s % 3600) // 60:02d}"


def unique_path(folder, name):
    base, ext = os.path.splitext(name)
    path, i = os.path.join(folder, name), 1
    while os.path.exists(path):
        path = os.path.join(folder, f"{base} ({i}){ext}")
        i += 1
    return path


def safe_rel(rel):
    """Sous-dossier demande par l'expediteur, nettoye (jamais de '..' ni de lecteur)."""
    parts = [p for p in rel.replace("\\", "/").split("/") if p not in ("", ".", "..") and ":" not in p]
    return os.path.join(*parts) if parts else ""


def expand_paths(paths):
    """Fichiers et dossiers -> liste de (chemin, sous-dossier relatif)."""
    items = []
    for p in paths:
        if os.path.isdir(p):
            base = os.path.basename(os.path.normpath(p))
            for root, _, files in os.walk(p):
                r = os.path.relpath(root, p)
                rel = base if r == "." else base + "/" + r.replace(os.sep, "/")
                for f in sorted(files):
                    items.append((os.path.join(root, f), rel))
        elif os.path.isfile(p):
            items.append((p, ""))
    return items


class Meter:
    """Vitesse lissee et temps restant."""
    def __init__(self, total):
        self.total, self.speed = total, 0.0
        self.t = time.time()
        self.n = 0

    def tick(self, n):
        now = time.time()
        if now - self.t < 0.3:
            return False
        inst = (n - self.n) / (now - self.t)
        self.speed = inst if self.speed == 0 else self.speed * 0.6 + inst * 0.4
        self.t, self.n = now, n
        return True

    def eta(self, n):
        return (self.total - n) / self.speed if self.speed > 0 else 0


class Hooks:
    """Points d'accroche : l'interface ou la CLI remplace ces fonctions."""
    def __init__(self):
        self.get_dir = lambda: os.path.join(os.path.expanduser("~"), "JRSDrop")
        self.ask = lambda info: False            # info: from, ip, name, size, count, total
        self.progress = lambda key, pct, speed, eta, label: None
        self.done = lambda rec: None
        self.error = lambda msg: None
        self.relay_state = lambda ok, msg="": None
        self.auto_accept = False


# ---------- decouverte (reseau local) ----------
def announce_loop():
    global MY_IPS
    while True:
        MY_IPS = local_ips()
        msg = json.dumps({"app": "flashdrop", "name": NAME, "v": VERSION, "recv": receiving}).encode()
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


def listen_loop(on_error=lambda m: None, on_new=lambda ip, name: None):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("", UDP_PORT))
    except Exception as e:
        on_error(f"Erreur découverte des PC : {e}")
        return
    while True:
        try:
            data, (ip, _) = s.recvfrom(1024)
            if ip in MY_IPS:
                continue
            d = json.loads(data)
            if d.get("app") == "flashdrop":
                if ip not in peers:
                    on_new(ip, str(d.get("name", ip)))
                peer_recv[ip] = bool(d.get("recv", True))
                peers[ip] = (str(d.get("name", ip)), time.time())
        except Exception:
            pass


# ---------- reception ----------
def _decide(hk, addr, who, name, size, batch):
    """Accepte ou refuse. Un lot de fichiers = une seule question."""
    bid = str(batch.get("id", ""))
    with _blk:
        for k in [k for k, (_, t) in _batches.items() if time.time() - t > 1800]:
            del _batches[k]
        if bid and bid in _batches:
            return _batches[bid][0]
    ok = True if hk.auto_accept else bool(hk.ask({
        "from": who, "ip": addr[0], "name": name, "size": size,
        "count": int(batch.get("count", 1)), "total": int(batch.get("total", size))}))
    if bid:
        with _blk:
            _batches[bid] = (ok, time.time())
    return ok


def handle(conn, addr, hk):
    key = f"in-{addr[0]}:{addr[1]}"
    part = None
    with conn:
        try:
            conn.settimeout(120)
            n = struct.unpack("!I", recv_exact(conn, 4))[0]
            if n > 65536:
                return
            meta = json.loads(recv_exact(conn, n))
            size = int(meta["size"])
            who = str(meta.get("from", addr[0]))
            if not receiving:                           # reception coupee
                conn.sendall(b"0")
                return
            if meta.get("bench"):                       # test de vitesse : on jette les octets
                if size > 2 * 1024 ** 3:
                    return
                conn.sendall(b"1")
                got, t0 = 0, time.time()
                buf = bytearray(CHUNK)
                mv = memoryview(buf)
                while got < size:
                    k = conn.recv_into(mv, min(CHUNK, size - got))
                    if not k:
                        raise ConnectionError("Test interrompu")
                    got += k
                conn.sendall(b"1")
                dt = max(time.time() - t0, 1e-6)
                hk.done({"kind": "bench", "dir": "in", "name": "Test de vitesse", "size": size,
                         "speed": size / dt, "peer": who, "path": ""})
                return
            name = os.path.basename(str(meta["name"]))
            rel = safe_rel(str(meta.get("rel", "")))
            os.makedirs(hk.get_dir(), exist_ok=True)
            free = shutil.disk_usage(hk.get_dir()).free
            if size > free - 50 * 1024 * 1024:
                conn.sendall(b"0")
                hk.error(f"Pas assez de place pour {name} ({fmt_size(size)}) : il reste {fmt_size(free)}")
                return
            ok = _decide(hk, addr, who, name, size, meta.get("batch") or {})
            conn.sendall(b"1" if ok else b"0")
            if not ok:
                return
            folder = os.path.join(hk.get_dir(), rel) if rel else hk.get_dir()
            os.makedirs(folder, exist_ok=True)
            dest = unique_path(folder, name)
            part = dest + ".part"
            m, got, t0 = Meter(size), 0, time.time()
            buf = bytearray(CHUNK)
            mv = memoryview(buf)
            with open(part, "wb") as f:
                while got < size:
                    k = conn.recv_into(mv, min(CHUNK, size - got))
                    if not k:
                        raise ConnectionError("Transfert interrompu")
                    f.write(mv[:k])
                    got += k
                    if m.tick(got):
                        hk.progress(key, got * 100 / max(size, 1), m.speed, m.eta(got), name)
            os.replace(part, dest)
            part = None
            conn.sendall(b"1")
            dt = max(time.time() - t0, 1e-6)
            hk.done({"kind": "file", "dir": "in", "name": name, "size": size,
                     "speed": size / dt, "peer": who, "path": dest})
        except Exception as e:
            hk.error(f"Erreur réception : {e}")
            if part and os.path.exists(part):
                try:
                    os.remove(part)
                except OSError:
                    pass
        finally:
            hk.progress(key, 0, 0, 0, "")


def serve_direct(hk):
    try:
        srv = tune(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("", TCP_PORT))
        srv.listen(10)
    except Exception as e:
        hk.error(f"Erreur : port {TCP_PORT} déjà utilisé (JRSDrop est peut-être déjà ouvert) : {e}")
        return
    while True:
        conn, addr = srv.accept()
        threading.Thread(target=handle, args=(conn, addr, hk), daemon=True).start()


class RelayListener:
    """Mode distance : on se connecte (sortant) au serveur relais et on attend qu'un PC envoie."""
    def __init__(self, hk):
        self.hk, self.sock, self.ev = hk, None, threading.Event()

    def start(self, host, port, code):
        self.stop()
        self.ev = threading.Event()
        threading.Thread(target=self._run, args=(host, port, code, self.ev), daemon=True).start()

    def stop(self):
        self.ev.set()
        s = self.sock
        if s:
            try:
                s.close()
            except OSError:
                pass

    def _run(self, host, port, code, ev):
        while not ev.is_set():
            try:
                s = tune(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
                s.settimeout(10)
                s.connect((host, port))
                self.sock = s
                s.settimeout(None)
                s.sendall(f"L {code} {DEVICE_ID}\n".encode())
                self.hk.relay_state(True)
                while True:
                    b = s.recv(1)
                    if not b:
                        raise ConnectionError("relais déconnecté")
                    if b == b"G":
                        break                       # '.' = simple signal de vie
                self.sock = None
                threading.Thread(target=handle, args=(s, ("salle", next(_ids)), self.hk), daemon=True).start()
            except Exception as e:
                if ev.is_set():
                    return
                self.hk.relay_state(False, str(e))
                ev.wait(3)


# ---------- envoi ----------
def _connect(host, port):
    s = tune(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
    s.settimeout(10)
    s.connect((host, port))
    return s


def open_conn(t):
    """t = {'ip','port'} (direct) ou {'room','relay_host','relay_port'} (via relais)."""
    if t.get("room"):
        s = _connect(t["relay_host"], t["relay_port"])
        s.sendall(f"S {t['room']} {DEVICE_ID}\n".encode())
        s.settimeout(15)
        if s.recv(1) != b"G":
            s.close()
            raise ConnectionError("personne n'écoute dans cette salle (l'autre PC doit l'activer)")
        return s
    return _connect(t["ip"], t.get("port", TCP_PORT))


def send_files(t, label, items, hk):
    key = "out-" + str(t.get("ip") or t.get("room"))
    batch = {"id": uuid.uuid4().hex[:10], "count": len(items),
             "total": sum(os.path.getsize(p) for p, _ in items)}
    for path, rel in items:
        try:
            size, name = os.path.getsize(path), os.path.basename(path)
            with open_conn(t) as s:
                hdr = json.dumps({"name": name, "size": size, "from": NAME, "rel": rel, "batch": batch}).encode()
                s.sendall(struct.pack("!I", len(hdr)) + hdr)
                s.settimeout(120)
                if recv_exact(s, 1) != b"1":
                    hk.error(f"{label} a refusé {name} (ou n'est pas en mode réception)")
                    break
                m, sent, t0 = Meter(size), 0, time.time()
                buf = bytearray(CHUNK)
                mv = memoryview(buf)
                with open(path, "rb", buffering=0) as f:
                    while True:
                        k = f.readinto(buf)
                        if not k:
                            break
                        s.sendall(mv[:k])
                        sent += k
                        if m.tick(sent):
                            hk.progress(key, sent * 100 / max(size, 1), m.speed, m.eta(sent), name)
                recv_exact(s, 1)
            dt = max(time.time() - t0, 1e-6)
            hk.done({"kind": "file", "dir": "out", "name": name, "size": size,
                     "speed": size / dt, "peer": label, "path": path})
        except Exception as e:
            hk.error(f"Erreur envoi vers {label} : {e}")
            break
    hk.progress(key, 0, 0, 0, "")


def bench_send(t, label, mb, hk):
    """Mesure la vitesse reseau pure (rien n'est ecrit sur le disque du destinataire)."""
    size = mb * 1024 * 1024
    try:
        with open_conn(t) as s:
            hdr = json.dumps({"bench": True, "name": "bench", "size": size, "from": NAME}).encode()
            s.sendall(struct.pack("!I", len(hdr)) + hdr)
            s.settimeout(120)
            if recv_exact(s, 1) != b"1":
                hk.error(f"{label} n'est pas prêt à recevoir (mode réception coupé ?)")
                return
            block, sent, t0 = memoryview(os.urandom(CHUNK)), 0, time.time()
            while sent < size:
                k = min(CHUNK, size - sent)
                s.sendall(block[:k])
                sent += k
            recv_exact(s, 1)
        dt = max(time.time() - t0, 1e-6)
        hk.done({"kind": "bench", "dir": "out", "name": "Test de vitesse", "size": size,
                 "speed": size / dt, "peer": label, "path": ""})
    except Exception as e:
        hk.error(f"Erreur test de vitesse vers {label} : {e}")