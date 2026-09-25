// Service Worker for PickerWheel Contest App
const VERSION = '15.0_cinematic_redesign';
const CACHE_NAME = 'pickerwheel-contest-v' + VERSION;
// Note: each file below carries its own cache-busting query string (set in
// index.html) rather than a single shared VERSION, so they're listed as-is.
const STATIC_ASSETS = [
    '/',
    '/index.html',
    '/style.css?v=20.0_cinematic',
    '/theme-manager.js?v=3.0_cinematic',
    '/wheel.js?v=16.0_cinematic',
    'https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700;800;900&display=swap'
];

// Install event - cache static assets
self.addEventListener('install', (event) => {
    console.log('[SW] Install event');
    
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => {
                console.log('[SW] Caching static assets');
                return cache.addAll(STATIC_ASSETS);
            })
            .then(() => {
                console.log('[SW] Static assets cached');
                return self.skipWaiting();
            })
            .catch((error) => {
                console.error('[SW] Failed to cache static assets:', error);
            })
    );
});

// Activate event - clean up old caches
self.addEventListener('activate', (event) => {
    console.log('[SW] Activate event');
    
    event.waitUntil(
        caches.keys()
            .then((cacheNames) => {
                return Promise.all(
                    cacheNames
                        .filter((cacheName) => {
                            return cacheName !== CACHE_NAME;
                        })
                        .map((cacheName) => {
                            console.log('[SW] Deleting old cache:', cacheName);
                            return caches.delete(cacheName);
                        })
                );
            })
            .then(() => {
                console.log('[SW] Claiming clients');
                return self.clients.claim();
            })
    );
});

// Fetch event - serve from cache with network fallback
self.addEventListener('fetch', (event) => {
    // Skip cross-origin requests
    if (!event.request.url.startsWith(self.location.origin) && 
        !event.request.url.startsWith('https://fonts.googleapis.com')) {
        return;
    }
    
    // Skip API requests - always go to network
    if (event.request.url.includes('/api/')) {
        event.respondWith(
            fetch(event.request).catch(error => {
                console.error('[SW] API fetch failed:', error);
                return new Response(JSON.stringify({
                    success: false,
                    error: 'Network error. Please check your connection.'
                }), {
                    headers: { 'Content-Type': 'application/json' }
                });
            })
        );
        return;
    }
    
    event.respondWith(
        caches.match(event.request)
            .then((cachedResponse) => {
                if (cachedResponse) {
                    console.log('[SW] Serving from cache:', event.request.url);
                    return cachedResponse;
                }
                
                console.log('[SW] Fetching from network:', event.request.url);
                return fetch(event.request)
                    .then((networkResponse) => {
                        // Don't cache non-successful responses
                        if (!networkResponse || networkResponse.status !== 200 || networkResponse.type !== 'basic') {
                            return networkResponse;
                        }
                        
                        // Clone response for caching
                        const responseToCache = networkResponse.clone();
                        
                        caches.open(CACHE_NAME)
                            .then((cache) => {
                                cache.put(event.request, responseToCache);
                            });
                        
                        return networkResponse;
                    })
                    .catch((error) => {
                        console.error('[SW] Fetch failed:', error);
                        
                        // Return offline page for navigation requests
                        if (event.request.destination === 'document') {
                            return caches.match('/index.html');
                        }
                        
                        throw error;
                    });
            })
    );
});

// Background sync for future enhancements
self.addEventListener('sync', (event) => {
    console.log('[SW] Background sync:', event.tag);
    
    if (event.tag === 'prize-sync') {
        event.waitUntil(
            syncPrizeData()
        );
    }
});

// Push notifications for future enhancements
self.addEventListener('push', (event) => {
    console.log('[SW] Push notification received');
    
    if (event.data) {
        const data = event.data.json();
        
        const options = {
            body: data.body || 'New prizes available!',
            icon: '/icon-192.png',
            badge: '/icon-72.png',
            vibrate: [100, 50, 100],
            data: {
                dateOfArrival: Date.now(),
                primaryKey: data.primaryKey || 'default'
            },
            actions: [
                {
                    action: 'spin',
                    title: 'Spin Now!',
                    icon: '/icon-spin.png'
                },
                {
                    action: 'close',
                    title: 'Later',
                    icon: '/icon-close.png'
                }
            ]
        };
        
        event.waitUntil(
            self.registration.showNotification(
                data.title || '🎄 New Prize Available!',
                options
            )
        );
    }
});

// Handle notification clicks
self.addEventListener('notificationclick', (event) => {
    console.log('[SW] Notification clicked:', event.action);
    
    event.notification.close();
    
    if (event.action === 'spin') {
        // Open app and focus on spin button
        event.waitUntil(
            clients.matchAll({
                type: 'window'
            }).then((clientList) => {
                for (const client of clientList) {
                    if (client.url === self.location.origin && 'focus' in client) {
                        return client.focus();
                    }
                }
                if (clients.openWindow) {
                    return clients.openWindow('/');
                }
            })
        );
    }
});

// Message handling for communication with main app
self.addEventListener('message', (event) => {
    console.log('[SW] Message received:', event.data);
    
    if (event.data && event.data.type) {
        switch (event.data.type) {
            case 'SKIP_WAITING':
                self.skipWaiting();
                break;
            case 'GET_VERSION':
                event.ports[0].postMessage({version: CACHE_NAME});
                break;
            case 'CLEAR_CACHE':
                event.waitUntil(
                    caches.delete(CACHE_NAME).then(() => {
                        event.ports[0].postMessage({success: true});
                    })
                );
                break;
        }
    }
});

// Helper functions
async function syncPrizeData() {
    try {
        // Future enhancement: sync prize data with server
        console.log('[SW] Syncing prize data...');
        return Promise.resolve();
    } catch (error) {
        console.error('[SW] Prize sync failed:', error);
        throw error;
    }
}

// Error handling
self.addEventListener('error', (event) => {
    console.error('[SW] Error:', event.error);
});

self.addEventListener('unhandledrejection', (event) => {
    console.error('[SW] Unhandled promise rejection:', event.reason);
});

console.log('[SW] Service Worker loaded');