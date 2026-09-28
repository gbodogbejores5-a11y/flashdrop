# FlashDrop

Envoie des fichiers d'un PC a un autre, tres vite, sans cable, sans cle USB et sans Bluetooth.
Un seul fichier .exe, gratuit et open source. Fonctionne avec ou sans internet.

## Fonctionnalites

- Radar anime : les PC qui utilisent FlashDrop apparaissent automatiquement
- Envoi a plusieurs PC en meme temps
- Transfert direct PC vers PC en Wi-Fi local (pas de serveur, pas de compte)
- Le destinataire doit accepter chaque fichier
- Fichiers de toute taille (envoi par blocs de 1 Mo)

## Telecharger

Va dans l'onglet Releases et telecharge FlashDrop.exe.

Windows peut afficher "Windows a protege votre PC" car l'application n'est pas signee.
Clique sur "Informations complementaires" puis "Executer quand meme".
Le code est ouvert : tu peux le verifier dans flashdrop.py.

## Connecter les PC

1. Wi-Fi existant (maison, box, routeur) : connecte les PC dessus.
2. Pas de Wi-Fi : active le Point d'acces mobile de Windows sur un PC et connecte les autres dessus.
3. Pour aller le plus vite possible : relie les 2 PC avec un cable Ethernet.
4. Lance FlashDrop.exe sur chaque PC et autorise le pare-feu (reseaux prives).
5. Choisis les PC sur le radar, choisis tes fichiers, clique sur Envoyer.

Si un PC n'apparait pas, entre son IP dans "IP manuelle" (commande ipconfig).

## Lancer depuis le code source

    python flashdrop.py

Creer le .exe :

    pip install pyinstaller
    pyinstaller --onefile --noconsole --name FlashDrop flashdrop.py

## Idees pour la suite

- Reprise apres coupure (important pour les tres gros fichiers)
- Glisser-deposer et dossiers entiers
- Chiffrement et code d'appairage
- Version Android

## Licence

MIT : utilise, modifie et partage librement.