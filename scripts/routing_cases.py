"""The routing battery: 241 labelled missions that exercise the two-way decision.

Every mission is completed by exactly one of the agent's two execution paths, so
the label is the ground truth of the product decision, not a preference:

- ``browser``      — the mission is finished by interacting with the CURRENT page:
  clicking, typing, selecting, scrolling, navigating that site, or reading what the
  page already shows.
- ``orchestrated`` — the mission needs at least one capability the browser loop does
  not have: searching the wider web, opening other sites, downloading a file, parsing
  or creating a document (PDF/DOCX/XLSX/CSV), or running commands and code.

Mixed missions follow the safe direction: if ANY part needs a tool, the label is
``orchestrated``. That is the direction that degrades gracefully — an over-routed
browser mission still completes (slower, through the tool loop), while an
under-routed tool mission cannot complete at all in the browser loop. The battery
counts that failure separately as *dangerous confusion*.

Composition (241 cases):

- 6 languages x 36 core missions (18 browser + 18 orchestrated) = 216, with the
  same variety of intents in each language so per-language accuracy is comparable.
- 25 adversarial missions: mixed intent, multi-clause, bilingual, telegraphic and
  typos — the shapes real users actually type.

Add more cases without touching Python by passing a JSONL fixture to the benches
(``{"lang": "es", "mission": "...", "expected": "browser", "kind": "extra"}``), which
is how the battery scales from 241 to 500.
"""

import json

LANGUAGES = ("es", "en", "de", "fr", "it", "pt")

CORE_PER_LANGUAGE = 36
ADVERSARIAL_TOTAL = 25

# ── core battery: (lang, mission) grouped by the label they must produce ──────

BROWSER_CORE = [
    # ── español ──────────────────────────────────────────────────────────────
    ("es", "Haz clic en el botón de iniciar sesión de esta página"),
    ("es", "Rellena el formulario de contacto con mis datos y envíalo"),
    ("es", "En esta página, cambia el idioma a inglés"),
    ("es", "Busca vuelos de ida de Zúrich a Londres el 20 de septiembre de 2026 en esta página"),
    ("es", "Acepta el banner de cookies y sigue navegando"),
    ("es", "Desplázate hasta la sección de opiniones y dime la nota media"),
    ("es", "Selecciona 2 adultos en el desplegable de pasajeros"),
    ("es", "Activa la opción de solo ida en este buscador"),
    ("es", "Reserva una mesa para dos el viernes a las 21:00 en este restaurante"),
    ("es", "Cambia la moneda a euros y ordena los resultados por precio"),
    ("es", "Añade el primer producto al carrito y ve a la caja"),
    ("es", "Filtra los resultados por envío gratis"),
    ("es", "Suscríbete al boletín con mi correo electrónico"),
    ("es", "Ordénalos por valoración y dime cuál está mejor puntuado"),
    ("es", "Abre la pestaña de facturación de esta web"),
    ("es", "Quita el filtro de fecha y vuelve a buscar"),
    ("es", "Pulsa Siguiente hasta la última página de resultados de esta lista"),
    ("es", "Marca la casilla de aceptar términos y pulsa Continuar"),
    # ── english ──────────────────────────────────────────────────────────────
    ("en", "Click the sign in button on this page"),
    ("en", "Fill the shipping address form and confirm the order"),
    ("en", "On this page, switch the language to English"),
    ("en", "Find one-way flights from Zurich to London on September 20, 2026 on this page"),
    ("en", "Accept the cookie banner and keep browsing"),
    ("en", "Scroll to the reviews section and tell me the average rating"),
    ("en", "Select 2 adults in the passengers dropdown"),
    ("en", "Turn on the one-way option in this flight search"),
    ("en", "Book a table for two on Friday at 9 pm at this restaurant"),
    ("en", "Change the currency to euros and sort the results by price"),
    ("en", "Add the first product to the cart and go to checkout"),
    ("en", "Filter the results by free shipping"),
    ("en", "Subscribe to the newsletter with my email address"),
    ("en", "Sort them by rating and tell me which one scores highest"),
    ("en", "Open the billing tab of this site"),
    ("en", "Clear the date filter and search again"),
    ("en", "Keep pressing Next until the last page of results in this list"),
    ("en", "Tick the terms checkbox and press Continue"),
    # ── deutsch ──────────────────────────────────────────────────────────────
    ("de", "Klicke auf den Login-Button auf dieser Seite"),
    ("de", "Fülle das Anmeldeformular aus und sende es ab"),
    ("de", "Ändere auf dieser Seite die Sprache auf Deutsch"),
    ("de", "Suche auf dieser Seite Hinflüge von Zürich nach London am 20. September 2026"),
    ("de", "Akzeptiere das Cookie-Banner und scroll weiter"),
    ("de", "Scrolle zum Bewertungsbereich und sag mir die Durchschnittsnote"),
    ("de", "Wähle 2 Erwachsene im Passagier-Menü aus"),
    ("de", "Aktiviere die Option einfache Fahrt in dieser Flugsuche"),
    ("de", "Reserviere einen Tisch für zwei am Freitag um 21 Uhr in diesem Restaurant"),
    ("de", "Stelle die Währung auf Euro um und sortiere nach Preis"),
    ("de", "Lege das erste Produkt in den Warenkorb und gehe zur Kasse"),
    ("de", "Filtere die Ergebnisse nach kostenlosem Versand"),
    ("de", "Abonniere den Newsletter mit meiner E-Mail-Adresse"),
    ("de", "Sortiere sie nach Bewertung und sag mir, welches am besten abschneidet"),
    ("de", "Öffne den Rechnungs-Tab auf dieser Website"),
    ("de", "Entferne den Datumsfilter und suche erneut"),
    ("de", "Klicke auf Weiter bis zur letzten Ergebnisseite dieser Liste"),
    ("de", "Setze das Häkchen bei den Bedingungen und klicke auf Weiter"),
    # ── français ─────────────────────────────────────────────────────────────
    ("fr", "Clique sur le bouton de connexion de cette page"),
    ("fr", "Remplis le formulaire d'inscription et valide l'envoi"),
    ("fr", "Sur cette page, change la langue en français"),
    ("fr", "Cherche sur cette page des vols aller simple de Zurich à Londres le 20 septembre 2026"),
    ("fr", "Accepte la bannière de cookies et continue à naviguer"),
    ("fr", "Descends jusqu'à la section des avis et donne-moi la note moyenne"),
    ("fr", "Sélectionne 2 adultes dans le menu passagers"),
    ("fr", "Active l'option aller simple dans ce moteur de vols"),
    ("fr", "Réserve une table pour deux vendredi à 21 h dans ce restaurant"),
    ("fr", "Change la devise en euros et trie les résultats par prix"),
    ("fr", "Ajoute le premier produit au panier et va au paiement"),
    ("fr", "Filtre les résultats par livraison gratuite"),
    ("fr", "Abonne-moi à la newsletter avec mon adresse e-mail"),
    ("fr", "Trie-les par note et dis-moi lequel est le mieux classé"),
    ("fr", "Ouvre l'onglet de facturation de ce site"),
    ("fr", "Enlève le filtre de date et relance la recherche"),
    ("fr", "Clique sur Suivant jusqu'à la dernière page de résultats de cette liste"),
    ("fr", "Coche la case des conditions et clique sur Continuer"),
    # ── italiano ─────────────────────────────────────────────────────────────
    ("it", "Clicca sul pulsante di accesso di questa pagina"),
    ("it", "Compila il modulo di contatto e invialo"),
    ("it", "Su questa pagina, cambia la lingua in italiano"),
    ("it", "Cerca su questa pagina voli di sola andata da Zurigo a Londra il 20 settembre 2026"),
    ("it", "Accetta il banner dei cookie e continua a navigare"),
    ("it", "Scorri fino alla sezione recensioni e dimmi la valutazione media"),
    ("it", "Seleziona 2 adulti nel menu passeggeri"),
    ("it", "Attiva l'opzione sola andata in questa ricerca voli"),
    ("it", "Prenota un tavolo per due venerdì alle 21 in questo ristorante"),
    ("it", "Cambia la valuta in euro e ordina i risultati per prezzo"),
    ("it", "Aggiungi il primo prodotto al carrello e vai alla cassa"),
    ("it", "Filtra i risultati per spedizione gratuita"),
    ("it", "Iscrivimi alla newsletter con la mia email"),
    ("it", "Ordinali per valutazione e dimmi quale è il migliore"),
    ("it", "Apri la scheda di fatturazione di questo sito"),
    ("it", "Rimuovi il filtro della data e cerca di nuovo"),
    ("it", "Premi Avanti fino all'ultima pagina di risultati di questa lista"),
    ("it", "Spunta la casella dei termini e premi Continua"),
    # ── português ────────────────────────────────────────────────────────────
    ("pt", "Clica no botão de iniciar sessão desta página"),
    ("pt", "Preenche o formulário de contacto e envia-o"),
    ("pt", "Nesta página, muda o idioma para português"),
    ("pt", "Procura nesta página voos só de ida de Zurique a Londres a 20 de setembro de 2026"),
    ("pt", "Aceita o aviso de cookies e continua a navegar"),
    ("pt", "Desce até à secção de avaliações e diz-me a nota média"),
    ("pt", "Seleciona 2 adultos no menu de passageiros"),
    ("pt", "Ativa a opção só de ida nesta pesquisa de voos"),
    ("pt", "Reserva uma mesa para dois na sexta às 21h neste restaurante"),
    ("pt", "Muda a moeda para euros e ordena os resultados por preço"),
    ("pt", "Adiciona o primeiro produto ao carrinho e vai para o pagamento"),
    ("pt", "Filtra os resultados por envio gratuito"),
    ("pt", "Subscreve a newsletter com o meu email"),
    ("pt", "Ordena-os por avaliação e diz-me qual é o melhor"),
    ("pt", "Abre o separador de faturação deste site"),
    ("pt", "Remove o filtro de data e volta a pesquisar"),
    ("pt", "Clica em Seguinte até à última página de resultados desta lista"),
    ("pt", "Marca a caixa dos termos e clica em Continuar"),
]

ORCHESTRATED_CORE = [
    # ── español ──────────────────────────────────────────────────────────────
    ("es", "Busca en internet alternativas a Notion y guarda un resumen en un archivo"),
    ("es", "Descarga el PDF del informe anual y resume sus puntos clave"),
    ("es", "Crea un script de python que imprima hola y ejecútalo en la terminal"),
    ("es", "Analiza el Excel de ventas y dame los totales por trimestre"),
    ("es", "Investiga y compara precios de portátiles en varias webs"),
    ("es", "Escribe una guía en markdown sobre modelos de IA locales para 8 GB de RAM"),
    ("es", "Descarga el CSV de resultados y dime cuántas filas tiene"),
    ("es", "Genera un archivo CSV con los vuelos encontrados"),
    ("es", "Instala las dependencias del proyecto y corre los tests"),
    ("es", "Lee el DOCX de la propuesta y escribe un resumen en markdown"),
    ("es", "Búscame en internet la capital de Australia y cítame la fuente"),
    ("es", "Busca noticias de hoy sobre energía solar y hazme una lista con enlaces"),
    ("es", "Clona el repositorio y muéstrame el historial de commits"),
    ("es", "Renombra todos los PDF de la carpeta añadiendo la fecha al nombre"),
    ("es", "Crea un informe en markdown con los datos de los tres primeros resultados"),
    ("es", "Descarga la factura en PDF y extrae los totales a una hoja de cálculo"),
    ("es", "Ejecuta un script que cuente las palabras de los archivos de texto"),
    ("es", "Investiga tres hoteles en Lisboa y compáralos en una tabla dentro de un archivo"),
    # ── english ──────────────────────────────────────────────────────────────
    ("en", "Research Notion alternatives on the web and save a summary to a file"),
    ("en", "Download the annual report PDF and summarise its key points"),
    ("en", "Create a python script that prints hello and run it in the terminal"),
    ("en", "Parse the sales spreadsheet and give me the totals per quarter"),
    ("en", "Compare laptop prices across several websites"),
    ("en", "Write a guide in markdown about local AI models for an 8 GB laptop"),
    ("en", "Download the results CSV and tell me how many rows it has"),
    ("en", "Generate a CSV file with the flights found"),
    ("en", "Install the project dependencies and run the tests"),
    ("en", "Read the proposal DOCX and write a markdown summary"),
    ("en", "Search the web for the capital of Australia and cite the source"),
    ("en", "Find today's news about solar energy and make me a list with links"),
    ("en", "Clone the repository and show me the commit history"),
    ("en", "Rename every PDF in the folder, adding the date to the name"),
    ("en", "Create a markdown report with the data from the first three results"),
    ("en", "Download the invoice PDF and extract the totals into a spreadsheet"),
    ("en", "Run a script that counts the words in the text files of this folder"),
    ("en", "Research three hotels in Lisbon and compare them in a table inside a file"),
    # ── deutsch ──────────────────────────────────────────────────────────────
    ("de", "Recherchiere im Internet Alternativen zu Notion und speichere eine Zusammenfassung in einer Datei"),
    ("de", "Lade das PDF des Jahresberichts herunter und fasse die Kernpunkte zusammen"),
    ("de", "Erstelle ein Python-Skript, das hallo ausgibt, und führe es im Terminal aus"),
    ("de", "Analysiere die Excel-Datei mit den Verkäufen und nenne mir die Summen pro Quartal"),
    ("de", "Vergleiche Laptop-Preise auf mehreren Webseiten"),
    ("de", "Schreibe eine Anleitung in Markdown über lokale KI-Modelle für 8 GB RAM"),
    ("de", "Lade die CSV-Datei mit den Ergebnissen herunter und sag mir, wie viele Zeilen sie hat"),
    ("de", "Erstelle eine CSV-Datei mit den gefundenen Flügen"),
    ("de", "Installiere die Projekt-Abhängigkeiten und führe die Tests aus"),
    ("de", "Lies das DOCX-Angebot und schreibe eine Zusammenfassung in Markdown"),
    ("de", "Suche die Hauptstadt von Australien im Internet und nenne die Quelle"),
    ("de", "Suche aktuelle Nachrichten über Solarenergie und erstelle eine Liste mit Links"),
    ("de", "Klone das Repository und zeige mir die Commit-Historie"),
    ("de", "Benenne alle PDF-Dateien im Ordner um und ergänze das Datum im Namen"),
    ("de", "Erstelle einen Bericht in Markdown mit den Daten der ersten drei Ergebnisse"),
    ("de", "Lade die Rechnung als PDF herunter und extrahiere die Summen in eine Tabelle"),
    ("de", "Führe ein Skript aus, das die Wörter in den Textdateien dieses Ordners zählt"),
    ("de", "Recherchiere drei Hotels in Lissabon und vergleiche sie in einer Tabelle in einer Datei"),
    # ── français ─────────────────────────────────────────────────────────────
    ("fr", "Recherche sur le web des alternatives à Notion et enregistre un résumé dans un fichier"),
    ("fr", "Télécharge le rapport annuel en PDF et résume les points clés"),
    ("fr", "Crée un script python qui affiche bonjour et exécute-le dans le terminal"),
    ("fr", "Analyse le document Excel des ventes et donne-moi les totaux par trimestre"),
    ("fr", "Compare les prix des ordinateurs portables sur plusieurs sites"),
    ("fr", "Écris un guide en markdown sur les modèles d'IA locaux pour 8 Go de RAM"),
    ("fr", "Télécharge le fichier CSV des résultats et dis-moi combien de lignes il contient"),
    ("fr", "Génère un fichier CSV avec les vols trouvés"),
    ("fr", "Installe les dépendances du projet et lance les tests"),
    ("fr", "Lis le document DOCX de la proposition et écris un résumé en markdown"),
    ("fr", "Cherche sur le web la capitale de l'Australie et cite la source"),
    ("fr", "Cherche les actualités du jour sur l'énergie solaire et fais-moi une liste de liens"),
    ("fr", "Clone le dépôt et montre-moi l'historique des commits"),
    ("fr", "Renomme tous les PDF du dossier en ajoutant la date au nom"),
    ("fr", "Crée un rapport en markdown avec les données des trois premiers résultats"),
    ("fr", "Télécharge la facture en PDF et extrais les totaux dans un tableur"),
    ("fr", "Exécute un script qui compte les mots des fichiers texte de ce dossier"),
    ("fr", "Recherche trois hôtels à Lisbonne et compare-les dans un tableau dans un fichier"),
    # ── italiano ─────────────────────────────────────────────────────────────
    ("it", "Cerca sul web alternative a Notion e salva un riepilogo in un file"),
    ("it", "Scarica il PDF della relazione annuale e riassumi i punti chiave"),
    ("it", "Crea uno script python che stampa ciao ed eseguilo nel terminale"),
    ("it", "Analizza il file Excel delle vendite e dimmi i totali per trimestre"),
    ("it", "Confronta i prezzi dei portatili su più siti"),
    ("it", "Scrivi una guida in markdown sui modelli di IA locali per 8 GB di RAM"),
    ("it", "Scarica il file CSV dei risultati e dimmi quante righe ha"),
    ("it", "Genera un file CSV con i voli trovati"),
    ("it", "Installa le dipendenze del progetto ed esegui i test"),
    ("it", "Leggi il documento DOCX della proposta e scrivi un riepilogo in markdown"),
    ("it", "Cerca sul web la capitale dell'Australia e cita la fonte"),
    ("it", "Cerca su internet le notizie di oggi sull'energia solare e fammi una lista di link"),
    ("it", "Clona il repository e mostrami la cronologia dei commit"),
    ("it", "Rinomina tutti i PDF della cartella aggiungendo la data al nome"),
    ("it", "Crea un report in markdown con i dati dei primi tre risultati"),
    ("it", "Scarica la fattura in PDF ed estrai i totali in un foglio di calcolo"),
    ("it", "Esegui uno script che conta le parole nei file di testo di questa cartella"),
    ("it", "Cerca tre hotel a Lisbona e confrontali in una tabella dentro un file"),
    # ── português ────────────────────────────────────────────────────────────
    ("pt", "Pesquisa na web alternativas ao Notion e guarda um resumo num ficheiro"),
    ("pt", "Descarrega o PDF do relatório anual e resume os pontos principais"),
    ("pt", "Cria um script python que imprima olá e executa-o no terminal"),
    ("pt", "Analisa o ficheiro Excel das vendas e diz-me os totais por trimestre"),
    ("pt", "Compara os preços dos portáteis em vários sites"),
    ("pt", "Escreve um guia em markdown sobre modelos de IA locais para 8 GB de RAM"),
    ("pt", "Descarrega o ficheiro CSV dos resultados e diz-me quantas linhas tem"),
    ("pt", "Gera um ficheiro CSV com os voos encontrados"),
    ("pt", "Instala as dependências do projeto e corre os testes"),
    ("pt", "Lê o documento DOCX da proposta e escreve um resumo em markdown"),
    ("pt", "Pesquisa na web a capital da Austrália e cita a fonte"),
    ("pt", "Pesquisa na internet as notícias de hoje sobre energia solar e faz-me uma lista com links"),
    ("pt", "Clona o repositório e mostra-me o histórico de commits"),
    ("pt", "Renomeia todos os ficheiros PDF da pasta acrescentando a data ao nome"),
    ("pt", "Cria um relatório em markdown com os dados dos três primeiros resultados"),
    ("pt", "Descarrega a fatura em PDF e extrai os totais para uma folha de cálculo"),
    ("pt", "Executa um script que conta as palavras nos ficheiros de texto desta pasta"),
    ("pt", "Pesquisa três hotéis em Lisboa e compara-os numa tabela dentro de um ficheiro"),
]

# ── adversarial battery: the shapes real users type ──────────────────────────

ADVERSARIAL = [
    # mixed intent: on-page work that also needs the tool loop → orchestrated
    ("mixed_intent", "es",
     "Mira los vuelos en esta página y luego búscame en internet si hay trenes más baratos",
     "orchestrated"),
    ("mixed_intent", "en",
     "Fill this form, then find the company address on the web and save it to a file",
     "orchestrated"),
    ("mixed_intent", "de",
     "Klicke auf dieser Seite auf Suchen und recherchiere danach die Preise im Internet",
     "orchestrated"),
    ("mixed_intent", "fr",
     "Clique sur Réserver ici, puis télécharge la confirmation en PDF",
     "orchestrated"),
    ("mixed_intent", "it",
     "Compila questo modulo e poi cerca sul web le alternative più economiche",
     "orchestrated"),
    ("mixed_intent", "pt",
     "Preenche o formulário nesta página e depois pesquisa na web os preços",
     "orchestrated"),
    ("mixed_intent", "en",
     "On this page, filter by price — and also check on the web whether the seller is cheaper",
     "orchestrated"),
    ("mixed_intent", "es",
     "Reserva la mesa aquí y luego apunta la reserva en un archivo",
     "orchestrated"),
    ("mixed_intent", "fr",
     "Remplis le formulaire de cette page et enregistre une copie dans un fichier",
     "orchestrated"),
    ("mixed_intent", "de",
     "Fülle das Formular aus und speichere anschließend eine Kopie in einer Datei",
     "orchestrated"),
    # multi-clause but entirely on-page → browser
    ("long", "es",
     "Entra en esta página, inicia sesión, ve a la sección de movimientos, filtra por el mes "
     "pasado y dime el saldo final",
     "browser"),
    ("long", "en",
     "Open the settings page of this site, switch the theme to dark, enable two-factor prompts "
     "and confirm the changes",
     "browser"),
    ("long", "de",
     "Klicke auf dieser Seite auf Anmelden, gib meinen Benutzernamen ein, wähle Deutsch als "
     "Sprache und klicke auf Weiter",
     "browser"),
    ("long", "it",
     "Cerca sul web tre fornitori di hosting, confronta i prezzi, scarica i loro listini in PDF "
     "e crea un file di riepilogo",
     "orchestrated"),
    ("long", "pt",
     "Pesquisa na web três hotéis em Lisboa, compara os preços, descarrega as faturas em PDF e "
     "escreve um resumo num ficheiro",
     "orchestrated"),
    # bilingual / code-mixed
    ("bilingual", "es-en",
     "Find flights from Zurich to London and guarda el resultado en un archivo",
     "orchestrated"),
    ("bilingual", "en-de",
     "Click the Login button and danach öffne die Einstellungen auf dieser Seite",
     "browser"),
    ("bilingual", "fr-en",
     "Remplis le formulaire ici and then download the confirmation as PDF",
     "orchestrated"),
    ("bilingual", "it-es",
     "Cerca voli su questa pagina e apri il risultato migliore in una nuova scheda",
     "browser"),
    ("bilingual", "pt-en",
     "Preenche os dados aqui e depois save the summary to a file",
     "orchestrated"),
    # telegraphic: no verb, no grammar, still decidable
    ("telegraphic", "en", "login page -> click sign in", "browser"),
    ("telegraphic", "es", "vuelos Zúrich Londres 20 sep, esta página", "browser"),
    ("telegraphic", "de", "hier einloggen, dann Formular ausfüllen", "browser"),
    # typos and missing accents must not change the route
    ("typo", "es", "Descarga el PDF del informe y azme un resumen en un archibo", "orchestrated"),
    ("typo", "fr", "Telecharge le rapport PDF et fais un resume dans un fichier", "orchestrated"),
]


def build_cases():
    """The full battery as dicts, each with a stable id, language, label and kind."""
    cases = []
    for index, (lang, mission) in enumerate(BROWSER_CORE, start=1):
        cases.append({"id": f"r{index:04d}", "lang": lang, "mission": mission,
                      "expected": "browser", "kind": "core"})
    for index, (lang, mission) in enumerate(ORCHESTRATED_CORE, start=len(cases) + 1):
        cases.append({"id": f"r{index:04d}", "lang": lang, "mission": mission,
                      "expected": "orchestrated", "kind": "core"})
    for index, (kind, lang, mission, expected) in enumerate(ADVERSARIAL, start=len(cases) + 1):
        cases.append({"id": f"r{index:04d}", "lang": lang, "mission": mission,
                      "expected": expected, "kind": kind})
    return cases


ROUTING_CASES = build_cases()


def load_extra_cases(path):
    """Extra labelled missions from a JSONL fixture, so the battery can scale to 500."""
    extra = []
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                entry = json.loads(line)
            except ValueError as error:
                raise ValueError(f"{path}:{number}: not valid JSON ({error})") from None
            mission = str(entry.get("mission", "")).strip()
            expected = str(entry.get("expected", "")).strip()
            if not mission or expected not in {"browser", "orchestrated"}:
                raise ValueError(f"{path}:{number}: needs a mission and expected browser|orchestrated")
            extra.append({
                "id": f"x{number:04d}",
                "lang": str(entry.get("lang", "??")),
                "mission": mission,
                "expected": expected,
                "kind": str(entry.get("kind", "extra")),
            })
    return extra


def summary():
    """Composition counts, used by the report header and the fixture test."""
    core_browser = sum(1 for case in ROUTING_CASES
                       if case["kind"] == "core" and case["expected"] == "browser")
    core_orchestrated = sum(1 for case in ROUTING_CASES
                            if case["kind"] == "core" and case["expected"] == "orchestrated")
    return {
        "total": len(ROUTING_CASES),
        "core": core_browser + core_orchestrated,
        "core_browser": core_browser,
        "core_orchestrated": core_orchestrated,
        "adversarial": sum(1 for case in ROUTING_CASES if case["kind"] != "core"),
        "languages": list(LANGUAGES),
    }
