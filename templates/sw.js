// Service worker di {{ site.name }}: apre il sito anche senza campo e lo installa come app.
const VERSION = "{{ updated_iso }}";
const SHELL = "crinale-shell-" + VERSION;
const PAGES = "crinale-pagine";
const SAVED = "crinale-salvati";
const PRECACHE = ["./", "static/style.css", "static/favicon.svg", "static/icon-192.png", "offline/", "api/v1/forecast.json"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(SHELL).then(c => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(
    keys.filter(k => k.startsWith("crinale-shell-") && k !== SHELL).map(k => caches.delete(k))
  )).then(() => self.clients.claim()));
});

// Pagine e dati: prima la rete (previsioni fresche), poi la copia salvata. File statici: prima la copia.
self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET" || new URL(req.url).origin !== location.origin) return;
  const isStatic = new URL(req.url).pathname.includes("/static/");
  if (isStatic) {
    e.respondWith(caches.match(req).then(hit => hit || fetch(req).then(res => {
      const copy = res.clone(); caches.open(SHELL).then(c => c.put(req, copy)); return res;
    })));
    return;
  }
  e.respondWith(fetch(req).then(res => {
    if (res.ok) { const copy = res.clone(); caches.open(PAGES).then(c => c.put(req, copy)); }
    return res;
  }).catch(async () => {
    const hit = await caches.match(req);
    if (hit) return hit;
    if (req.mode === "navigate") return caches.match("offline/");
    return new Response("", { status: 504 });
  }));
});

// Un percorso chiede di essere salvato per l'uso senza rete (pagina, traccia GPX, dati).
self.addEventListener("message", e => {
  if (e.data && e.data.type === "save") {
    e.waitUntil(caches.open(SAVED).then(c => c.addAll(e.data.urls)).then(() =>
      e.source && e.source.postMessage({ type: "saved", urls: e.data.urls })));
  }
});
