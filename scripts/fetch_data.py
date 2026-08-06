"""
Script di raccolta dati e calcolo del sentiment finanziario.
Eseguito ogni giorno da GitHub Actions. Scrive docs/data.json,
che viene letto dal sito (docs/index.html) pubblicato con GitHub Pages.

Nessuna chiave API richiesta tranne FRED_API_KEY (gratuita, vedi README).
"""

import json
import os
import datetime
import feedparser
import yfinance as yf
import requests

FRED_API_KEY = os.environ.get("FRED_API_KEY", "")

# ---------------------------------------------------------------------
# 1. DATI DI MERCATO (yfinance, nessuna chiave richiesta)
# ---------------------------------------------------------------------

MARKET_TICKERS = {
    "FTSE MIB (Italia)": "FTSEMIB.MI",
    "S&P 500 (USA)": "^GSPC",
    "Stoxx 600 (Eurozona)": "^STOXX",
    "MSCI World ETF": "URTH",
    "VIX (volatilità USA)": "^VIX",
}


def get_market_data():
    result = {}
    for name, ticker in MARKET_TICKERS.items():
        try:
            hist = yf.Ticker(ticker).history(period="1y")
            if hist.empty:
                continue
            last_price = float(hist["Close"].iloc[-1])
            sma50 = float(hist["Close"].tail(50).mean())
            sma200 = float(hist["Close"].mean())
            change_1d = float(
                (hist["Close"].iloc[-1] / hist["Close"].iloc[-2] - 1) * 100
            )
            result[name] = {
                "prezzo": round(last_price, 2),
                "variazione_1g_pct": round(change_1d, 2),
                "sopra_media_50gg": last_price > sma50,
                "sopra_media_200gg": last_price > sma200,
            }
        except Exception as e:
            result[name] = {"errore": str(e)}
    return result


# ---------------------------------------------------------------------
# 2. DATI MACRO (FRED per USA, ECB/Eurostat per Eurozona - REST, no key)
# ---------------------------------------------------------------------

def get_fred_series(series_id):
    """Ultimo valore di una serie FRED (richiede chiave gratuita)."""
    if not FRED_API_KEY:
        return None
    url = (
        f"https://api.stlouisfed.org/fred/series/observations"
        f"?series_id={series_id}&api_key={FRED_API_KEY}&file_type=json"
        f"&sort_order=desc&limit=1"
    )
    try:
        r = requests.get(url, timeout=15)
        obs = r.json()["observations"][0]
        return {"data": obs["date"], "valore": float(obs["value"])}
    except Exception:
        return None


def get_macro_data():
    macro = {}
    # Curva rendimenti USA (10Y-2Y): se negativa, storicamente segnale di rischio recessione
    macro["spread_10y_2y_usa"] = get_fred_series("T10Y2Y")
    # Inflazione USA (CPI, variazione annua)
    macro["inflazione_usa_cpi"] = get_fred_series("CPIAUCSL")
    # Debito pubblico USA / PIL
    macro["debito_pil_usa"] = get_fred_series("GFDEGDQ188S")

    # Eurostat: inflazione eurozona (HICP) - REST pubblico, nessuna chiave
    try:
        url = (
            "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/"
            "data/prc_hicp_manr?format=JSON&geo=EA&coicop=CP00&lang=EN"
        )
        r = requests.get(url, timeout=15)
        data = r.json()
        values = list(data["value"].values())
        macro["inflazione_eurozona_hicp"] = round(values[-1], 2) if values else None
    except Exception:
        macro["inflazione_eurozona_hicp"] = None

    return macro


# ---------------------------------------------------------------------
# 3. NEWS (RSS, nessuna chiave richiesta)
# ---------------------------------------------------------------------

NEWS_FEEDS = {
    "Il Sole 24 Ore": "https://www.ilsole24ore.com/rss/finanza.xml",
    "ANSA Economia": "https://www.ansa.it/sito/notizie/economia/economia_rss.xml",
    "Reuters Business": "https://feeds.reuters.com/reuters/businessNews",
}


def get_news():
    news = []
    for source, url in NEWS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                news.append(
                    {
                        "fonte": source,
                        "titolo": entry.get("title", ""),
                        "link": entry.get("link", ""),
                    }
                )
        except Exception:
            continue
    return news


# ---------------------------------------------------------------------
# 4. CALCOLO SENTIMENT SCORE (regole fisse, non IA generativa)
# ---------------------------------------------------------------------

def calculate_sentiment(market, macro):
    """
    Restituisce un punteggio 0-100 e un semaforo.
    Punteggio alto = condizioni favorevoli. Punteggio basso = rischio elevato.
    Ogni componente mancante viene esclusa e i pesi ridistribuiti.
    """
    components = {}

    # --- Volatilità (VIX): sotto 20 = calmo, sopra 30 = stress ---
    vix = market.get("VIX (volatilità USA)", {}).get("prezzo")
    if vix is not None:
        if vix < 20:
            components["volatilita"] = 100
        elif vix < 30:
            components["volatilita"] = 60
        else:
            components["volatilita"] = 20

    # --- Momentum: media dei principali indici sopra le medie mobili ---
    momentum_scores = []
    for name in ["FTSE MIB (Italia)", "S&P 500 (USA)", "Stoxx 600 (Eurozona)", "MSCI World ETF"]:
        d = market.get(name, {})
        if "sopra_media_50gg" in d:
            score = 50
            if d["sopra_media_50gg"]:
                score += 25
            if d["sopra_media_200gg"]:
                score += 25
            momentum_scores.append(score)
    if momentum_scores:
        components["momentum"] = sum(momentum_scores) / len(momentum_scores)

    # --- Curva rendimenti USA: spread negativo = segnale di allarme ---
    spread = macro.get("spread_10y_2y_usa")
    if spread and spread.get("valore") is not None:
        v = spread["valore"]
        components["curva_rendimenti"] = 20 if v < 0 else 80

    # --- Inflazione eurozona: vicino al 2% (target BCE) = ok ---
    infl = macro.get("inflazione_eurozona_hicp")
    if infl is not None:
        distanza = abs(infl - 2.0)
        components["inflazione"] = max(0, 100 - distanza * 25)

    if not components:
        return {"punteggio": None, "semaforo": "sconosciuto", "dettaglio": {}}

    punteggio = round(sum(components.values()) / len(components), 1)

    if punteggio >= 70:
        semaforo = "verde"
    elif punteggio >= 45:
        semaforo = "giallo"
    else:
        semaforo = "rosso"

    return {"punteggio": punteggio, "semaforo": semaforo, "dettaglio": components}


# ---------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------

def main():
    market = get_market_data()
    macro = get_macro_data()
    news = get_news()
    sentiment = calculate_sentiment(market, macro)

    output = {
        "aggiornato_il": datetime.datetime.utcnow().isoformat() + "Z",
        "sentiment": sentiment,
        "mercati": market,
        "macro": macro,
        "news": news,
    }

    os.makedirs("docs", exist_ok=True)
    with open("docs/data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("Dati salvati in docs/data.json")


if __name__ == "__main__":
    main()
