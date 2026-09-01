const CACHE_NAME = 'huajuan-v3';
const SHELL = [
  '/',
  '/static/manifest.json',
  '/static/icon-192.png',
  '/static/icon-512.png'
];
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE_NAME).then(c => c.addAll(SHELL))
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
    ))
  );
});

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;

  if (e.request.mode === 'navigate') {
    // 页面请求：网络优先，拿最新的；拿不到才用缓存兜底
    e.respondWith(
      fetch(e.request).catch(() => caches.match('/'))
    );
    return;
  }

  // 静态资源：缓存优先（和原来一样）
  e.respondWith(
    caches.match(e.request).then(hit => {
      if (hit) return hit;
      return fetch(e.request).then(resp => {
        const copy = resp.clone();
        caches.open(CACHE_NAME).then(c => c.put(e.request, copy));
        return resp;
      });
    })
  );
});

