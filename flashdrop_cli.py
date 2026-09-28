#!/usr/bin/env python3
"""FlashDrop CLI : version sans interface (serveur Linux, homelab).
Compatible avec FlashDrop.exe (meme protocole).

Usage :
  python3 flashdrop_cli.py receive [--auto] [--dir DOSSIER]   recevoir des fichiers
  python3 flashdrop_cli.py list                                voir les PC detectes
  python3 flashdrop_cli.py send IP fichier1 [fichier2 ...]     envoyer des fichiers
"""
import socket, threading, json, os, struct, time, sys, subprocess

TCP_PORT = 50555          # port des transferts de fichiers
UDP_PORT = 50556          # port de decouverte des PC
CHUNK = 1024 * 1024       # blocs de 1 Mo
NAME = socket.gethostname()
peers = {}                # ip -> (nom, dernier_signe_de_vie)
MY_IPS = []
ASK_LOCK = threading.Lock()


def local_ips():
    """Adresses IPv4 de cette machine (sur Ubuntu, gethostname donne 127.0.1.1, donc on utilise hostname -I)."""
    ips = set()
    try:
        out = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=3).stdout
        ips.update(i for i in out.split() if "." in i and ":" not in i)
    except Exception:
        pass
    if not ips:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("10.255.255.255", 1))
            ips.add(s.getsockname()[0])
            s.close()
        except Exception:
            pass
    return sorted(i for i in ips if not i.startswith("127."))


def recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        part = sock.recv(n - len(buf))
        if not part:
            raise ConnectionError("Connexion coupee")
        buf += part
    return buf


def fmt_size(n):
    for u in ["o", "Ko", "Mo", "Go"]:
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} To"


def unique_path(folder, name):
    base, ext = os.path.splitext(name)
    path, i = os.path.join(folder, name), 1
    while os.path.exists(path):
        path = os.path.join(folder, f"{base} ({i}){ext}")
        i += 1
    return path


# ---------- decouverte ----------
def announce_loop():
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


def listen_loop():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("", UDP_PORT))
    except Exception as e:
        print("Erreur decouverte :", e)
        return
    while True:
        try:
            data, (ip, _) = s.recvfrom(1024)
            if ip in MY_IPS:
                continue
            d = json.loads(data)
            if d.get("app") == "flashdrop":
                if ip not in peers:
                    print(f"[+] PC detecte : {d.get('name', ip)} ({ip})")
                peers[ip] = (str(d.get("name", ip)), time.time())
        except Exception:
            pass


# ---------- reception ----------
def ask(question):
    with ASK_LOCK:
        try:
            return input(question).strip().lower() in ("o", "oui", "y", "yes")
        except EOFError:
            return False


def handle(conn, addr, recv_dir, auto):
    with conn:
        try:
            conn.settimeout(120)
            n = struct.unpack("!I", recv_exact(conn, 4))[0]
            if n > 65536:
                return
            meta = json.loads(recv_exact(conn, n))
            name = os.path.basename(meta["name"])
            size = int(meta["size"])
            print(f"\n{meta.get('from', addr[0])} ({addr[0]}) veut envoyer : {name} ({fmt_size(size)})")
            ok = True if auto else ask("Accepter ? [o/N] ")
            conn.sendall(b"1" if ok else b"0")
            if not ok:
                print("Refuse.")
                return
            dest = unique_path(recv_dir, name)
            got, t0, last = 0, time.time(), 0.0
            with open(dest, "wb") as f:
                while got < size:
                    b = conn.recv(min(CHUNK, size - got))
                    if not b:
                        raise ConnectionError("Transfert interrompu")
                    f.write(b)
                    got += len(b)
                    if time.time() - last > 1:
                        last = time.time()
                        print(f"\r  {got * 100 // max(size, 1)}%  {fmt_size(got)}   ", end="", flush=True)
            conn.sendall(b"1")
            dt = max(time.time() - t0, 1e-6)
            print(f"\rRecu : {dest} ({fmt_size(size)} en {dt:.1f} s = {size / dt / 1048576:.1f} Mo/s)")
        except Exception as e:
            print("Erreur reception :", e)


def receive(recv_dir, auto):
    os.makedirs(recv_dir, exist_ok=True)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("", TCP_PORT))
    srv.listen(10)
    threading.Thread(target=announce_loop, daemon=True).start()
    threading.Thread(target=listen_loop, daemon=True).start()
    time.sleep(0.5)
    print(f"FlashDrop CLI pret sur {NAME} ({', '.join(MY_IPS) or 'pas de reseau'})")
    print(f"Dossier de reception : {recv_dir}  |  acceptation auto : {'oui' if auto else 'non'}")
    print("Ctrl+C pour arreter.")
    while True:
        conn, addr = srv.accept()
        threading.Thread(target=handle, args=(conn, addr, recv_dir, auto), daemon=True).start()


# ---------- envoi ----------
def send(ip, paths):
    for p in paths:
        try:
            size = os.path.getsize(p)
            name = os.path.basename(p)
            print(f"-> {ip} : {name} ({fmt_size(size)}) en attente d'acceptation...")
            with socket.create_connection((ip, TCP_PORT), timeout=10) as s:
                hdr = json.dumps({"name": name, "size": size, "from": NAME}).encode()
                s.sendall(struct.pack("!I", len(hdr)) + hdr)
                s.settimeout(120)
                if recv_exact(s, 1) != b"1":
                    print("Refuse par l'autre PC.")
                    continue
                sent, t0, last = 0, time.time(), 0.0
                with open(p, "rb") as f:
                    while True:
                        b = f.read(CHUNK)
                        if not b:
                            break
                        s.sendall(b)
                        sent += len(b)
                        if time.time() - last > 1:
                            last = time.time()
                            print(f"\r  {sent * 100 // max(size, 1)}%  {fmt_size(sent)}   ", end="", flush=True)
                recv_exact(s, 1)
            dt = max(time.time() - t0, 1e-6)
            print(f"\rEnvoye : {name} en {dt:.1f} s = {size / dt / 1048576:.1f} Mo/s")
        except Exception as e:
            print("Erreur envoi :", e)


def main():
    a = sys.argv[1:]
    if not a or a[0] not in ("receive", "list", "send"):
        print(__doc__)
        return
    if a[0] == "receive":
        d = os.path.join(os.path.expanduser("~"), "FlashDrop")
        if "--dir" in a:
            d = a[a.index("--dir") + 1]
        try:
            receive(d, "--auto" in a)
        except KeyboardInterrupt:
            print("\nArret.")
    elif a[0] == "list":
        threading.Thread(target=announce_loop, daemon=True).start()
        threading.Thread(target=listen_loop, daemon=True).start()
        print("Recherche pendant 6 secondes...")
        time.sleep(6)
        if peers:
            for ip, (name, _) in peers.items():
                print(f"  {name}  -  {ip}")
        else:
            print("Aucun PC detecte (utilise l'IP directement avec la commande send).")
    elif a[0] == "send":
        if len(a) < 3:
            print("Usage : python3 flashdrop_cli.py send IP fichier1 [fichier2 ...]")
            return
        send(a[1], a[2:])


if __name__ == "__main__":
    main()