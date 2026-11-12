// Service worker: приложение открывается мгновенно и при плохом интернете.
// Оболочка (страница, стили, скрипт, иконки) берётся из кэша, данные — всегда с сервера.
const VERSION = "__VERSION__"; // подставляет сервер: хеш файлов, при изменении кэш обновится
const CACHE = `finance-${VERSION}`;
const SHELL = ["/", "/static/manifest.webmanifest", "/static/icons/icon-192.png", "/static/icons/apple-touch-icon.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== location.origin) return;
  // Финансовые данные не кэшируем: всегда актуальные и не остаются на устройстве
  if (url.pathname.startsWith("/api/")) return;

  if (request.mode === "navigate") {
    // Страница: сначала сеть, без интернета — сохранённая копия
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put("/", copy));
          return response;
        })
        .catch(() => caches.match("/")),
    );
    return;
  }

  if (url.pathname.startsWith("/static/")) {
    // Статика с хешем в адресе не меняется — можно отдавать из кэша
    event.respondWith(
      caches.match(request).then((cached) => cached || fetch(request).then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy));
        }
        return response;
      })),
    );
  }
});
