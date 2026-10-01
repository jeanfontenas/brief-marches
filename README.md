# Brief marchés

Chaque jour ouvré vers 8 h (heure de Paris), une page web lisible sur iPhone avec les chiffres clés de la veille (taux, actions, pétrole, change), les courbes de taux, les banques centrales, l'inflation et un commentaire pédagogique rédigé par Claude. Une notification arrive sur l'iPhone (app ntfy) avec le lien.

- **La page** : `https://<ton-compte>.github.io/<nom-du-dépôt>/` (les briefs précédents sont dans « Archives »)
- **Le réglage** : tout se change dans `config.yaml`, sans toucher au code.

## Mode d'emploi

### Modifier un fichier sur GitHub
1. Ouvre le dépôt sur github.com et clique sur le fichier (par exemple `config.yaml`).
2. Clique sur l'icône **crayon** (« Edit this file ») en haut à droite du fichier.
3. Fais ta modification, puis clique sur **Commit changes…** puis sur **Commit changes**.

Garde bien les espaces en début de ligne : ils structurent le fichier. En cas d'erreur de syntaxe, le brief suivant échoue et tu reçois une notification d'échec. Il suffit alors de corriger.

### Changer l'heure du brief
Dans `config.yaml`, section `general` :
```yaml
  heure_cible: "08:00"     # heure de Paris à laquelle la page doit être prête
```
Le calcul démarre environ 50 minutes avant (`avance_minutes`), car GitHub lance parfois les tâches avec du retard. L'heure d'été et l'heure d'hiver sont gérées automatiquement.
Les créneaux de lancement couvrent une heure cible entre environ 6 h 45 et 10 h 30. Pour une heure en dehors de cette plage, il faut aussi modifier la ligne `cron` de `.github/workflows/brief.yml` (demande-moi).

### Ajouter un indicateur (Euro Stoxx 50, DAX, Nasdaq…)
Trois exemples sont déjà prêts dans `config.yaml` : `eurostoxx50`, `dax` et `nasdaq`. Pour en afficher un, ajoute son identifiant dans un groupe :
```yaml
  - titre: "Actions"
    indicateurs: [cac40, sp500, eurostoxx50]
```
Pour un nouvel indice, copie un bloc existant (par exemple `cac40`), change l'identifiant, le nom et le symbole Yahoo Finance (visible dans l'adresse de la page de l'indice sur finance.yahoo.com, par exemple `^GDAXI` pour le DAX), puis ajoute l'identifiant dans un groupe. L'historique sur 5 ans est téléchargé automatiquement le lendemain.

### Mettre en pause
- **Pause** : dans `config.yaml`, mets `en_pause: true` (et `false` pour reprendre).
- **Arrêt complet** : onglet **Actions** du dépôt, puis **Brief marchés** dans la liste de gauche, puis le bouton **…** et **Disable workflow**. Pour relancer : **Enable workflow**.

### Lancer un brief à la main
Onglet **Actions**, puis **Brief marchés**, puis **Run workflow** et le bouton vert **Run workflow**. Coche « Ne pas appeler Claude » pour un test gratuit, sans commentaire. Coche « Reprendre le commentaire déjà publié aujourd'hui » pour republier la page du jour (après une modification de la mise en page, par exemple) sans nouvel appel à Claude, donc sans coût.

### Mettre à jour les calendriers (une fois par an, en décembre)
Dans `config.yaml` :
- **Réunions de la Fed** (`banques_centrales > fed > reunions`) : dernier jour de chaque réunion, d'après https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
- **Réunions de la BCE** (`banques_centrales > bce > reunions`) : jour de la décision, d'après https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.fr.html (déjà rempli jusqu'à fin 2028)
- **CPI et PCE américains** (`inflation > us > mesures > publications`) : dates de https://www.bls.gov/schedule/news_release/cpi.htm et https://www.bea.gov/news/schedule
- **France** (`inflation > fr > publications > dates`) : facultatif. Sans date, la page affiche une estimation (dernier jour ouvré du mois).
- **Zone euro** : rien à faire, le calendrier Eurostat est lu automatiquement.

Quand une liste est épuisée, la page affiche « date à compléter dans config.yaml ».

### Suivre les coûts
- Le coût estimé de chaque commentaire est enregistré dans `data/couts_claude.csv` (une ligne par appel, en dollars) et dans les journaux GitHub Actions (« coût estimé »).
- Le coût réel se lit dans la console Anthropic : https://platform.claude.com, menu **Usage** et **Cost**. La **limite de dépense mensuelle** s'y règle dans **Settings > Limits**.
- Pour réduire le coût, dans `config.yaml`, section `commentaire` : passe `recherches_web_max` à 2 ou 3, `effort` à `"low"`, ou `modele` à `"claude-sonnet-5-5"` (environ deux fois moins cher).
- GitHub Actions et GitHub Pages sont gratuits pour un dépôt public. ntfy est gratuit.

## En cas de problème : lire les journaux
1. Onglet **Actions** du dépôt : chaque lancement a une ligne (✓ vert = réussi, ✗ rouge = échec).
2. Clique sur le lancement, puis sur la tâche **generer** (ou **publier**), puis déplie l'étape en rouge.
3. Copie les **30 dernières lignes** de l'étape en échec et colle-les-moi. Ce qu'il faut regarder :
   - `Source en échec …` : une source n'a pas répondu, la page sort quand même avec la dernière valeur connue ;
   - `Commentaire indisponible …` : problème avec l'API Claude (clé, crédit, limite de dépense) ;
   - `Décision : rien à faire (trop tôt…)` : normal, ce créneau n'était pas le bon.

Ne colle jamais une clé API dans un message.

## Les clés expirent-elles ?
| Clé | Durée de vie | À faire |
|---|---|---|
| Anthropic | celle choisie à la création (« Never » conseillé) | rien. Si elle expire ou est supprimée, la page et la notification l'indiquent (« clé Anthropic refusée ») : recrée une clé et mets à jour le secret `ANTHROPIC_API_KEY` |
| FRED | pas d'expiration | rien |
| Banque de France (Webstat) | pas d'expiration connue | rien. Si elle cesse de marcher, le brief passe en mode sans clé (dernières valeurs seulement) |
| ntfy | pas de clé, seulement le nom secret du canal | rien |

Pour remplacer une clé : Settings > Secrets and variables > Actions, puis clique sur le crayon à côté du secret, colle la nouvelle valeur et clique sur **Update secret**.

## Sources des données
| Donnée | Source | Disponible à 8 h ? |
|---|---|---|
| Taux français (TEC 1 à 30 ans) | Banque de France, Webstat | oui, valeur officielle calculée en cours de journée |
| Taux allemands (6 mois à 30 ans) | Bundesbank, courbe de Svensson | oui, estimation publiée vers 12 h 45 le jour même |
| Taux américains, point mort 10 ans | US Treasury (courbes nominale et réelle) | oui, clôture de la veille |
| CAC 40, S&P 500, Brent, WTI, Dubai, euro/dollar | Yahoo Finance (usage personnel, non officiel) | oui, clôture de la veille |
| Taux de dépôt BCE, IPCH zone euro et France | BCE (Data Portal) | oui |
| Fourchette cible de la Fed | Fed de New York (sans clé), FRED en secours | oui |
| CPI, PCE | FRED (Fed de Saint-Louis) | oui (données mensuelles) |

Financial Times : le FT interdit l'usage de son contenu à des fins d'intelligence artificielle (https://www.ft.com/robots.txt). Le site ft.com est donc exclu des recherches de Claude (`domaines_exclus` dans `config.yaml`), et la page propose seulement des liens « Pour aller plus loin » vers le FT, à lire avec ton abonnement.

Limites connues : pas de taux quotidien gratuit pour les BTF français à 3 et 6 mois, ni pour l'Allemagne à 3 mois. Les taux français et allemands sont des valeurs officielles calculées en cours de journée, pas des cours de clôture.

## Organisation du dépôt
| Fichier | Rôle |
|---|---|
| `config.yaml` | Tous les réglages : heure, indicateurs, courbes, calendriers, modèle Claude |
| `.github/workflows/brief.yml` | Planification et exécution quotidienne, publication, notification |
| `.github/workflows/test-notification.yml` | Envoie une notification de test |
| `brief/gate.py` | Décide si c'est l'heure (gère l'heure d'été et d'hiver) |
| `brief/sources.py` | Téléchargement des données, une fonction par source |
| `brief/store.py` | Historique local des séries (`data/history/`) |
| `brief/build.py` | Calcul des variations, courbes, banques centrales, inflation, jours fériés |
| `brief/commentary.py` | Commentaire de Claude (recherche web, JSON, estimation du coût) |
| `brief/render.py` | Fabrication de la page et des archives (`site/`) |
| `brief/main.py` | Enchaîne toutes les étapes |
| `templates/page.html` | Gabarit de la page (mise en page, graphiques) |
| `static/` | Icône et manifeste pour l'écran d'accueil de l'iPhone |
| `tests/` | Tests automatiques (`python -m pytest -q`) |
| `data/` | Historique, état du dernier brief, journal des coûts (mis à jour chaque jour) |
| `site/` | Pages publiées (mises à jour chaque jour) |

## Secrets GitHub (Settings > Secrets and variables > Actions)
| Nom | Contenu | Obligatoire |
|---|---|---|
| `ANTHROPIC_API_KEY` | clé de la console Anthropic | pour le commentaire |
| `FRED_API_KEY` | clé FRED | pour le CPI et le PCE (et en secours pour la Fed) |
| `BDF_API_KEY` | clé Webstat de la Banque de France | pour l'historique des taux français |
| `NTFY_TOPIC` | nom secret du canal ntfy | pour les notifications |
