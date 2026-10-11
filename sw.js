// Legacy service worker removal. Version 2 no longer caches HTML.
self.addEventListener('install',()=>self.skipWaiting());self.addEventListener('activate',e=>e.waitUntil((async()=>{await self.registration.unregister();const keys=await caches.keys();await Promise.all(keys.filter(k=>k.startsWith('pokedex-')).map(k=>caches.delete(k)));})()));
