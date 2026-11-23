/* WanderShots lightweight performance helpers.
 * Native lazy-loading with an above-the-fold exception, plus a mutation hook
 * for images inserted by AJAX (chat, calendar, galleries).
 */
(function () {
    'use strict';

    var VIEWPORT_MARGIN = 1.15;
    var pendingRoots = [];
    var scheduled = false;

    function markLoaded(image) {
        image.classList.add('is-loaded');
    }

    function prepareImage(image) {
        if (!image || image.tagName !== 'IMG' || image.dataset.wsLazyReady === '1') return;
        image.dataset.wsLazyReady = '1';
        image.decoding = 'async';
        image.classList.add('ws-lazy-img');

        if (image.complete && image.naturalWidth > 0) {
            markLoaded(image);
        } else {
            image.addEventListener('load', function () { markLoaded(image); }, { once: true });
        }

        var rect = image.getBoundingClientRect();
        var nearViewport = rect.top < (window.innerHeight * VIEWPORT_MARGIN) && rect.bottom > -100;
        if (!image.hasAttribute('loading')) {
            image.loading = nearViewport ? 'eager' : 'lazy';
        }
        if (nearViewport && !image.hasAttribute('fetchpriority') && rect.top < window.innerHeight) {
            image.setAttribute('fetchpriority', 'high');
        }
    }

    function refresh(root) {
        var scope = root || document;
        if (scope.tagName === 'IMG') {
            prepareImage(scope);
            return;
        }
        if (!scope.querySelectorAll) return;
        prepareImage(scope);
        var images = scope.querySelectorAll('img:not([data-ws-lazy-ready])');
        for (var i = 0; i < images.length; i += 1) prepareImage(images[i]);
    }

    function flushPending() {
        scheduled = false;
        var roots = pendingRoots;
        pendingRoots = [];
        for (var i = 0; i < roots.length; i += 1) refresh(roots[i]);
    }

    function enqueue(root) {
        if (!root || root.nodeType !== 1) return;
        pendingRoots.push(root);
        if (scheduled) return;
        scheduled = true;
        window.requestAnimationFrame(flushPending);
    }

    if ('MutationObserver' in window) {
        var observer = new MutationObserver(function (mutations) {
            for (var i = 0; i < mutations.length; i += 1) {
                var added = mutations[i].addedNodes;
                for (var j = 0; j < added.length; j += 1) enqueue(added[j]);
            }
        });
        observer.observe(document.documentElement, { childList: true, subtree: true });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { refresh(document); }, { once: true });
    } else {
        refresh(document);
    }

    window.WSPerf = { refreshLazyImages: refresh };
})();
