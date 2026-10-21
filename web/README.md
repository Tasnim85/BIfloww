# Askboard — application web (étape 7)

*Drop a CSV. Ask a question. Get your dashboard.*

L'application Next.js de BIFlow : page d'accueil, inscription / connexion (e-mail + Google, reCAPTCHA), pipeline complet, historique, français / anglais, mode clair / sombre.

**Ce qui est réel aujourd'hui :**
- **BO4-12** : les 5 contrôles, la correction proposée, la décision de l'utilisateur, puis le dashboard calculé en SQL ;
- **l'Auditor** : SHAP, journal d'audit chaîné, drift et agent « pourquoi ? ».

Les autres étapes du pipeline sont des **démos clairement étiquetées**, en attendant que chaque membre branche son agent (voir plus bas).

---

## 1. Lancer l'app (Windows, cmd)

Il faut **Node.js 22 ou 24** (https://nodejs.org) et l'API Python déjà lancée (`uvicorn api.main:app --port 8000`).

```cmd
cd /d D:\5ds3\pi\BIFLOW\web
npm install
copy .env.example .env.local
```

Ouvre `.env.local` et remplace `NEXTAUTH_SECRET` par une longue valeur aléatoire. Pour la générer :

```cmd
node -e "console.log(require('crypto').randomBytes(32).toString('base64'))"
```

Puis lance l'app :

```cmd
npm run dev
```

Ouvre http://localhost:3000.

- Sans clés Google et reCAPTCHA, tout fonctionne en développement : le bouton Google est simplement désactivé et reCAPTCHA est ignoré.
- **En production, reCAPTCHA sans clé est refusé.** C'est voulu.

## 2. Les clés (optionnelles en développement)

### Connexion Google

1. Va sur https://console.cloud.google.com, puis **APIs & Services → Credentials → Create credentials → OAuth client ID**.
2. Pour le type d'application, choisis **Web application**.
3. Dans **Authorized redirect URIs**, mets `http://localhost:3000/api/auth/callback/google`.
4. Copie l'ID client et le secret dans `.env.local`, dans `GOOGLE_CLIENT_ID` et `GOOGLE_CLIENT_SECRET`.
5. Relance `npm run dev`.

### reCAPTCHA v2 (case à cocher)

1. Va sur https://www.google.com/recaptcha/admin et crée un site de type **reCAPTCHA v2 → case à cocher « Je ne suis pas un robot »**, avec le domaine `localhost`.
   Des clés v3 ou « invisible » ne marchent **pas** avec ce code.
2. Copie la clé du site dans `NEXT_PUBLIC_RECAPTCHA_SITE_KEY` et la clé secrète dans `RECAPTCHA_SECRET_KEY`, dans `web\.env.local`.
3. **Arrête puis relance** `npm run dev` : Next.js ne relit pas `.env.local` à chaud.

À l'inscription, la case n'est cochée qu'une fois : le serveur renvoie ensuite un ticket à usage unique (2 minutes) pour la connexion automatique. Diagnostic : `npm run check:recaptcha`.

### E-mail de bienvenue

À la création d'un compte (e-mail ou Google), Askboard envoie un e-mail de bienvenue avec le logo, dans la langue de l'utilisateur. Il est envoyé en arrière-plan : une panne d'e-mail ne bloque jamais l'inscription.

1. Avec Gmail : active la validation en 2 étapes sur ton compte Google, puis crée un **mot de passe d'application** (https://myaccount.google.com/apppasswords).
2. Dans `web\.env.local`, remplis `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=465`, `SMTP_USER`, `SMTP_PASS` (le mot de passe d'application) et `MAIL_FROM`.
3. Relance `npm run dev`.

**Erreur « self-signed certificate in certificate chain »** : un logiciel de ton PC, presque toujours l'antivirus (Avast, AVG, Kaspersky, ESET…), ouvre les e-mails sortants pour les analyser et remplace le certificat de Gmail par le sien. Lance `npm run check:mail` : la ligne « signed by » donne son nom. Deux solutions sûres :
- désactive l'analyse des e-mails sortants dans l'antivirus (Avast / AVG : Paramètres → Protection → Agents principaux → Agent Mail → décocher l'analyse des e-mails sortants (SMTP)) ;
- ou exporte le certificat racine de l'antivirus en `.pem` et indique son chemin dans `SMTP_CA_FILE` : il ne sera utilisé que pour l'envoi des e-mails.

Ne désactive jamais la vérification des certificats (`NODE_TLS_REJECT_UNAUTHORIZED=0`) : n'importe qui pourrait alors lire ton mot de passe.

Sans `SMTP_HOST`, en développement, l'e-mail est enregistré dans `web\data\outbox\` : ouvre le fichier `.html` dans ton navigateur pour le voir.

### Notifications

Quand une analyse se termine (prête, en attente de décision ou en échec), une notification apparaît dans la cloche en haut de l'app, avec un message en bas à droite. Tu peux quitter la page « Nouvelle analyse » pendant le calcul : la notification te ramène au résultat.

## 3. Ce que fait chaque partie

```
navigateur ──► Next.js (cette app) ──► /api/backend/* (proxy sécurisé) ──► FastAPI /api/* (Python)
                   │                                                         │
                   └── data/askboard.db (SQLite)                              └── runs/ + journaux d'audit
                       utilisateurs + historique                                  (décisions des agents)
```

| Dossier | Rôle |
|---|---|
| `src/app/page.tsx` | page d'accueil |
| `src/app/(auth)/` | inscription et connexion |
| `src/app/app/` | l'application connectée : vue d'ensemble, nouvelle analyse, analyse, historique, audit |
| `src/app/api/` | routes serveur : auth, inscription, historique, proxy vers Python |
| `src/lib/pipeline.ts` | **les étapes du pipeline**, réelles ou démo : le fichier que chaque membre modifie |
| `src/components/run/` | l'écran d'une analyse : pipeline, BO4-12, SHAP, journal, drift, « pourquoi ? » |
| `messages/en.json`, `messages/fr.json` | tous les textes de l'interface, en anglais (langue par défaut) et en français |
| `src/app/globals.css` | les couleurs du logo (clair et sombre), en variables CSS |
| `src/lib/api-types.ts` | types **générés** depuis les contrats Python (ne pas modifier à la main) |

## 4. Brancher son agent (pour l'équipe)

Chaque étape est déclarée dans `src/lib/pipeline.ts`, avec son responsable :

```ts
{ id: "profiling", step: "2", owner: "Ahmed", bo: ["BO2"], mode: "demo", icon: "scan" },
```

Pour passer son étape de **démo** à **réelle** :

1. **Côté Python** : expose la sortie de ton agent dans ton propre `APIRouter` FastAPI, par exemple `GET /api/runs/{run_id}/profiling`. Inclus-le dans l'API commune avec le même préfixe `/api`.
2. **Côté proxy** : ajoute ta route à la liste autorisée `READ` dans `src/app/api/backend/[...path]/route.ts`. Le proxy refuse tout ce qui n'est pas dans la liste.
3. **Types** : lance `python -m api.export_openapi`, puis `npm run types:api` dans `web/`.
4. **Affichage** : dans `src/lib/pipeline.ts`, passe à `mode: "live"`. Dans `useOutput()` de `src/components/run/Pipeline.tsx`, écris ce que ton étape affiche à partir de ta route. Pour un panneau complet, ajoute un onglet dans `src/components/run/RunView.tsx`.
5. **Textes** : ajoute-les dans `messages/en.json` **et** `messages/fr.json`, sous `app.stages.<ton id>`.

**Quand l'orchestrateur sera prêt**, la route « Nouvelle analyse » (`src/app/api/analyses/route.ts`) appellera `POST /api/runs` (dépôt du CSV + question) au lieu de `POST /api/comparisons`. Le reste de l'écran ne change pas, car il lit les mêmes contrats.

## 5. Sécurité

- **Mots de passe** : hachés avec bcrypt (coût 12), au moins 8 caractères avec une lettre et un chiffre. Un e-mail inconnu met autant de temps à être refusé qu'un mauvais mot de passe, ce qui empêche de deviner les comptes existants.
- **Limite de tentatives** : 5 connexions par minute et 5 inscriptions par 10 minutes, par adresse IP.
- **reCAPTCHA v2 (case à cocher)** : vérifié **côté serveur**, avec contrôle que le défi a été résolu sur ce site (hostname).
- **Google** : seuls les e-mails vérifiés par Google sont acceptés.
- **Sessions** : cookies JWT signés (`NEXTAUTH_SECRET`), valables 7 jours. Toutes les pages `/app` exigent une session.
- **Proxy vers Python** : le navigateur ne parle jamais directement à l'API Python. Le proxy :
  - exige une session ;
  - n'autorise qu'une liste de routes ;
  - vérifie la **propriété** : un utilisateur lit les jeux de démonstration et **ses** analyses, et n'écrit (décision, « pourquoi ? ») que sur les siennes.
- **Redirection après connexion** : uniquement vers une page `/app` de ce site, jamais vers un site extérieur.
- **En-têtes HTTP** : `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`.
- **Fichier CSV** : lu **dans le navigateur** pour l'aperçu, jamais envoyé ni stocké pour l'instant.
- **Fichiers à ne jamais commiter** : `.env.local` et `data/` sont dans `.gitignore`.

## 6. Commandes

| Commande | Rôle |
|---|---|
| `npm run dev` | développement, avec rechargement automatique |
| `npm run build` puis `npm start` | version de production |
| `npm run typecheck` | vérification TypeScript |
| `npm run types:api` | régénère les types depuis `../api/openapi.json` |
