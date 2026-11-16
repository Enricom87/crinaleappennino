# Crinale – previsioni neve per l'Appennino tosco-emiliano

Sito statico che si aggiorna da solo tre volte al giorno con GitHub Actions e si pubblica gratis su GitHub Pages.

## Come funziona
1. `pipeline/fetch.py` scarica i modelli da Open-Meteo: LAM (ICON-2I, ICON-CH2, ICON-D2, AROME), globali (ECMWF, GFS, ICON), ensemble ECMWF e variabili in quota.
2. `pipeline/build.py` calcola la neve stimata a ogni quota, le probabilità, l'indice per l'innevamento artificiale e la configurazione. Poi genera le pagine in `site/` e l'API JSON in `site/api/v1/`, pensata per la futura app.
3. `pipeline/newsletter.py` invia l'allerta neve (almeno 5 cm in 72 ore) e il riepilogo del giovedì tramite Brevo.

## Cosa si cambia senza toccare il codice
- `config/site.json`: nome, dominio, email, modulo newsletter, analytics.
- `config/locations.json`: località e punti (coordinate e quota).
- `config/sponsors.json`: sponsor per località (`_global` per la home, `_newsletter` per le email).
- `config/webcams.json`: link alle webcam.

## Messa online (una volta sola)
1. Crea un repository su GitHub e caricaci questi file.
2. Vai in Settings → Pages → Source e scegli "GitHub Actions".
3. Vai in Settings → Secrets and variables → Actions e aggiungi (facoltativi, servono solo per la newsletter):
   `BREVO_API_KEY`, `BREVO_LIST_ID`, `SENDER_EMAIL`.
   Prima di avere sponsor attivi aggiungi anche `OPEN_METEO_API_KEY`: l'API gratuita di Open-Meteo è solo per uso non commerciale.
4. Vai in Actions → "Aggiorna previsioni" → Run workflow per il primo aggiornamento.
5. Dominio: in Settings → Pages → Custom domain inserisci il dominio, poi nel pannello del registrar crea i record DNS indicati da GitHub.

## Prova in locale
```
pip install requests jinja2
python tests/make_fixture.py            # dati di prova, senza rete
cd pipeline && SAMPLE=1 python build.py  # sito in site/
```

## Licenze dei dati
I dati dei modelli sono di ItaliaMeteo-ARPAE, MeteoSvizzera, DWD, Météo-France, ECMWF e NOAA, distribuiti tramite Open-Meteo con licenza CC BY 4.0: l'attribuzione è già nel footer e nella pagina Metodo. Con ricavi da sponsor serve l'abbonamento commerciale di Open-Meteo, oppure si passa ai dati aperti scaricati direttamente.
