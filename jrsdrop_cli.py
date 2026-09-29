#!/usr/bin/env python3
"""jrsdrop CLI : version terminal (serveur Linux, homelab). Meme protocole que jrsdrop.exe.

  python3 jrsdrop_cli.py receive [--auto] [--dir DOSSIER] [--relay HOTE[:PORT] --room CODE]
  python3 jrsdrop_cli.py list
  python3 jrsdrop_cli.py send IP[:PORT] fichier_ou_dossier [...]
  python3 jrsdrop_cli.py send --relay HOTE[:PORT] --room CODE fichier_ou_dossier [...]
  python3 jrsdrop_cli.py bench IP[:PORT] [Mo]        test de vitesse reseau (defaut 200 Mo)
"""
import os, sys, time, threading
import fdcore as core


def hp(s, default):
    if ":" in s:
        h, p = s.rsplit(":", 1)
        return h, int(p)
    return s, default


def opt(a, name):
    return a[a.index(name) + 1] if name in a else None


ASK_LOCK = threading.Lock()


def make_hooks(d, auto):
    hk = core.Hooks()
    hk.get_dir = lambda: d
    hk.auto_accept = auto

    def ask(i):
        what = i["name"] if i["count"] <= 1 else f"{i['count']} fichiers"
        sz = i["size"] if i["count"] <= 1 else i["total"]
        with ASK_LOCK:
            try:
                return input(f"\n{i['from']} ({i['ip']}) veut envoyer : {what} ({core.fmt_size(sz)}). Accepter ? [o/N] ").strip().lower() in ("o", "oui", "y", "yes")
            except EOFError:
                return False

    def prog(key, pct, speed, eta, label):
        if pct > 0:
            print(f"\r  {label[:30]:30} {pct:5.1f}%  {core.fmt_speed(speed)}  reste {core.fmt_eta(eta)}   ", end="", flush=True)

    def done(r):
        sens = "Recu " if r["dir"] == "in" else "Envoye"
        print(f"\r{sens} : {r['name']} ({core.fmt_size(r['size'])}) = {core.fmt_speed(r['speed'])} ({r['peer']})" + " " * 20)

    hk.ask, hk.progress, hk.done = ask, prog, done
    hk.error = lambda m: print("\n" + m)
    hk.relay_state = lambda ok, m="": print("Relais :", "connecte" if ok else "erreur " + m)
    return hk


def target_from(a, ipidx):
    if "--room" in a:
        rh, rp = hp(opt(a, "--relay") or "", core.RELAY_PORT)
        return {"room": opt(a, "--room"), "relay_host": rh, "relay_port": rp}, "salle " + opt(a, "--room")
    h, p = hp(a[ipidx], core.TCP_PORT)
    return {"ip": h, "port": p}, a[ipidx]


def main():
    a = sys.argv[1:]
    if not a or a[0] not in ("receive", "list", "send", "bench"):
        print(__doc__)
        return
    cmd = a[0]
    if cmd == "receive":
        d = opt(a, "--dir") or os.path.join(os.path.expanduser("~"), "jrsdrop")
        os.makedirs(d, exist_ok=True)
        hk = make_hooks(d, "--auto" in a)
        threading.Thread(target=core.announce_loop, daemon=True).start()
        threading.Thread(target=core.listen_loop, args=(print, lambda ip, n: print(f"[+] PC detecte : {n} ({ip})")), daemon=True).start()
        threading.Thread(target=core.serve_direct, args=(hk,), daemon=True).start()
        if "--room" in a:
            rh, rp = hp(opt(a, "--relay") or "", core.RELAY_PORT)
            core.RelayListener(hk).start(rh, rp, opt(a, "--room"))
        time.sleep(0.6)
        print(f"jrsdrop CLI pret sur {core.NAME} ({', '.join(core.MY_IPS) or 'pas de reseau'}) - port {core.TCP_PORT}")
        print(f"Dossier : {d}  |  acceptation auto : {'oui' if hk.auto_accept else 'non'}  |  Ctrl+C pour arreter")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nArret.")
    elif cmd == "list":
        threading.Thread(target=core.announce_loop, daemon=True).start()
        threading.Thread(target=core.listen_loop, daemon=True).start()
        print("Recherche pendant 6 secondes...")
        time.sleep(6)
        for ip, (n, _) in core.peers.items():
            print(f"  {n}  -  {ip}")
        if not core.peers:
            print("Aucun PC detecte (utilise l'IP directement avec send).")
    else:
        hk = make_hooks("", False)
        room = "--room" in a
        rest = [x for i, x in enumerate(a[1:], 1) if x not in ("--room", "--relay") and (i < 2 or a[i - 1] not in ("--room", "--relay"))]
        if cmd == "bench":
            t, label = target_from(a, 1)
            mb = int(rest[-1]) if len(rest) > (1 if not room else 0) and rest[-1].isdigit() else 200
            print(f"Test de vitesse vers {label} ({mb} Mo)...")
            core.bench_send(t, label, mb, hk)
        else:
            t, label = target_from(a, 1)
            paths = rest if room else rest[1:]
            items = core.expand_paths(paths)
            if not items:
                print("Aucun fichier a envoyer.")
                return
            print(f"Envoi de {len(items)} fichier(s) vers {label} (attente d'acceptation)...")
            try:
                core.send_files(t, label, items, hk)
            except KeyboardInterrupt:
                print("\nEnvoi annule (Ctrl+C).")


if __name__ == "__main__":
    main()