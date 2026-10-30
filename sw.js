'use strict';

const PREFIX = `bygga-${new URL(self.registration.scope).pathname}-`;
const CACHE = `${PREFIX}v5`;
const FILES = [
  './', './index.html', './style.css?v=3', './engine.js?v=3', './sound.js?v=2',
  './game.js?v=6', './install.js', './favicon.svg', './manifest.webmanifest',
  './icons/apple-touch-icon.png', './icons/icon-192.png', './icons/icon-512.png',
];
const allowedPaths = new Set(FILES.map(file => new URL(file, self.registration.scope).pathname));

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache =>
    cache.addAll(FILES.map(file => new Request(new URL(file, self.registration.scope), {cache: 'reload'})))
  ).then(() => self.skipWaiting()));
});

self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(
    keys.filter(key => key.startsWith(PREFIX) && key !== CACHE).map(key => caches.delete(key))
  )).then(() => self.clients.claim()));
});

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin || !allowedPaths.has(url.pathname)) return;
  if (event.request.mode === 'navigate') {
    // Check for a newer page online; open the complete cached game offline.
    event.respondWith(fetch(event.request).catch(() => caches.match(new URL('./index.html', self.registration.scope))));
  } else {
    event.respondWith(caches.match(event.request).then(cached => cached || fetch(event.request)));
  }
});
