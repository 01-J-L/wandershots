/* WanderShots connectivity + service-worker update UX. */
(function () {
    'use strict';

    var banner = document.getElementById('wsOfflineBanner');
    var retry = document.getElementById('wsOfflineRetry');
    var reloading = false;
    var hadController = false;

    function notify(message, type) {
        if (window.WSLoading && window.WSLoading.toast) {
            window.WSLoading.toast(message, type);
        }
    }

    function setOffline(isOffline) {
        if (banner) banner.hidden = !isOffline;
        document.documentElement.classList.toggle('is-offline', isOffline);
    }

    function check() {
        setOffline(!navigator.onLine);
    }

    window.addEventListener('online', function () {
        setOffline(false);
        notify('Back online.', 'success');
    });

    window.addEventListener('offline', function () {
        setOffline(true);
    });

    if (retry) {
        retry.addEventListener('click', function () {
            if (navigator.onLine) {
                window.location.reload();
            } else {
                notify('Still offline. Check your connection and try again.', 'error');
            }
        });
    }

    if ('serviceWorker' in navigator) {
        hadController = !!navigator.serviceWorker.controller;

        navigator.serviceWorker.addEventListener('controllerchange', function () {
            // Only reload for an update, never for the first install.
            if (!hadController || reloading) return;
            reloading = true;
            window.location.reload();
        });

        window.addEventListener('ws:sw-updated', function () {
            notify('A new version of Wandershots is ready. Refresh to update.', 'success');
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', check, { once: true });
    } else {
        check();
    }

    window.WSNetwork = {
        isOnline: function () { return navigator.onLine; },
        refresh: check
    };
})();
