# Dashboard sentiment di mercato — guida al deploy (da zero)

Tempo stimato: 20-30 minuti, una tantum. Poi il sito si aggiorna da solo ogni giorno, gratis.

## 1. Crea un account GitHub
Vai su https://github.com/signup e registrati (gratis).

## 2. Crea un nuovo repository
- Clicca sul **+** in alto a destra → **New repository**
- Nome: `dashboard-mercati` (o quello che preferisci)
- Lascialo **pubblico** (necessario per GitHub Pages gratuito)
- Clicca **Create repository**

## 3. Carica questi file nel repository
Nella pagina del repository appena creato:
- Clicca **uploading an existing file**
- Trascina dentro TUTTI i file e le cartelle che ti ho preparato (mantenendo la struttura: `.github/workflows/`, `scripts/`, `docs/`, `requirements.txt`)
- Scrivi un messaggio tipo "primo caricamento" e clicca **Commit changes**

## 4. Ottieni la chiave gratuita FRED (per i dati macro USA)
- Vai su https://fred.stlouisfed.org/docs/api/api_key.html
- Registrati gratis e copia la tua API key

## 5. Salva la chiave nel repository (in modo sicuro)
- Nel repository, vai su **Settings** → **Secrets and variables** → **Actions**
- Clicca **New repository secret**
- Nome: `FRED_API_KEY`
- Valore: incolla la chiave ottenuta al punto 4
- Salva

## 6. Attiva GitHub Pages
- Sempre in **Settings** → **Pages**
- In "Build and deployment", alla voce **Source** scegli **Deploy from a branch**
- Branch: `main`, cartella: `/docs`
- Salva

Dopo 1-2 minuti il sito sarà visibile a un indirizzo tipo:
`https://tuonomeutente.github.io/dashboard-mercati/`

## 7. Avvia il primo aggiornamento manuale
- Vai sulla tab **Actions** del repository
- Clicca sul workflow **Aggiornamento giornaliero dashboard**
- Clicca **Run workflow** → **Run workflow** (di nuovo, per confermare)
- Aspetta 1-2 minuti che finisca (icona verde di spunta)
- Ricarica il sito: ora vedrai i dati veri

Da qui in poi, GitHub eseguirà lo script automaticamente **ogni giorno alle 7:00 UTC** senza che tu debba fare nulla. Metti l'indirizzo del sito tra i preferiti del browser.

## Come modificare le soglie del sentiment
Apri `scripts/fetch_data.py`, sezione `calculate_sentiment()`. Ogni componente (volatilità, momentum, curva dei rendimenti, inflazione) ha soglie modificabili a mano — sono commentate per capire cosa fanno.

## Nota
Questo strumento fotografa lo stato attuale dei mercati con regole fisse e trasparenti, non fa previsioni. Non è consulenza finanziaria.
