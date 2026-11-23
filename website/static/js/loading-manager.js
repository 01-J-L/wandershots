/* WanderShots loading manager.
 *
 * Three separate loading concepts:
 *   initial   - full-screen branded loader, only on genuine entry/reload
 *   section   - thin top progress bar for navigation/async section work
 *   background- non-blocking toast/spinner for long operations
 */
(function () {
    'use strict';

    var LOADER_ID = 'wsInitialLoader';
    var NAV_MARKER = 'ws:navigating';
    var sectionCount = 0;
    var initialHidden = false;
    var navMarkerTimer = null;

    function storageGet(key) {
        try { return window.sessionStorage.getItem(key); } catch (e) { return null; }
    }

    function storageSet(key, value) {
        try { window.sessionStorage.setItem(key, value); } catch (e) { /* ignore */ }
    }

    function storageRemove(key) {
        try { window.sessionStorage.removeItem(key); } catch (e) { /* ignore */ }
    }

    function loader() {
        return document.getElementById(LOADER_ID);
    }

    function hideInitial(reason) {
        var el = loader();
        if (!el) {
            initialHidden = true;
            return;
        }
        el.classList.add('is-hidden');
        initialHidden = true;
        window.setTimeout(function () {
            if (el && el.parentNode) el.setAttribute('aria-hidden', 'true');
        }, 450);
    }

    function showInitial(message) {
        var el = loader();
        if (!el) return;
        initialHidden = false;
        el.style.animation = 'none';
        el.classList.remove('is-hidden');
        el.removeAttribute('aria-hidden');
        var caption = document.getElementById('wsLoaderCaption');
        if (caption && message) caption.textContent = message;
    }

    function sectionStart() {
        sectionCount += 1;
        var bar = document.getElementById('wsTopProgress');
        if (bar) bar.classList.add('is-active');
    }

    function sectionEnd() {
        sectionCount = Math.max(0, sectionCount - 1);
        if (sectionCount === 0) {
            var bar = document.getElementById('wsTopProgress');
            if (bar) bar.classList.remove('is-active');
        }
    }

    function resetForPageShow() {
        sectionCount = 0;
        var bar = document.getElementById('wsTopProgress');
        if (bar) bar.classList.remove('is-active');
        hideInitial('pageshow');
    }

    function markNavigating() {
        storageSet(NAV_MARKER, '1');
        if (navMarkerTimer) window.clearTimeout(navMarkerTimer);
        // Validation failures can leave the marker behind; expire it.
        navMarkerTimer = window.setTimeout(function () {
            storageRemove(NAV_MARKER);
        }, 15000);
    }

    function isModifiedClick(event) {
        return event.metaKey || event.ctrlKey || event.shiftKey || event.altKey;
    }

    function shouldHandleLink(link, event) {
        if (!link || event.defaultPrevented || event.button !== 0 || isModifiedClick(event)) return false;
        if (link.hasAttribute('data-no-loader')) return false;
        if (link.target && link.target !== '_self') return false;
        if (link.hasAttribute('download')) return false;
        var href = link.getAttribute('href');
        if (!href || href.charAt(0) === '#' || /^(mailto:|tel:|javascript:)/i.test(href)) return false;
        try {
            var url = new URL(link.href, window.location.href);
            if (url.origin !== window.location.origin) return false;
            if (url.pathname === window.location.pathname && url.search === window.location.search && url.hash) return false;
        } catch (e) {
            return false;
        }
        return true;
    }

    function shouldHandleForm(form) {
        if (!form || form.hasAttribute('data-no-loader') || form.hasAttribute('data-ajax')) return false;
        if ((form.target || '').toLowerCase() === '_blank') return false;
        if ((form.method || 'get').toLowerCase() === 'dialog') return false;
        return true;
    }

    document.addEventListener('click', function (event) {
        var link = event.target && event.target.closest ? event.target.closest('a') : null;
        if (!shouldHandleLink(link, event)) return;
        markNavigating();
        sectionStart();
    }, true);

    document.addEventListener('submit', function (event) {
        if (!shouldHandleForm(event.target)) return;
        markNavigating();
        sectionStart();
    }, true);

    window.addEventListener('pageshow', function (event) {
        if (event.persisted) resetForPageShow();
    });

    // Hide the initial loader when the real page load is complete, with a
    // safety timeout for broken third-party assets.
    function finishInitial() {
        if (!initialHidden) hideInitial('load');
    }

    if (document.readyState === 'complete') {
        window.setTimeout(finishInitial, 80);
    } else {
        window.addEventListener('load', finishInitial, { once: true });
    }

    document.addEventListener('DOMContentLoaded', function () {
        var root = document.documentElement;
        if (root.getAttribute('data-ws-skip-initial-loader') === '1') {
            hideInitial('internal-navigation');
        }
    });

    window.setTimeout(function () {
        if (!initialHidden) hideInitial('safety-timeout');
    }, 9000);

    function toast(message, type) {
        if (!message) return;
        var el = document.createElement('div');
        el.className = 'ws-toast' + (type ? ' is-' + type : '');
        el.setAttribute('role', 'status');
        el.textContent = message;
        document.body.appendChild(el);
        window.setTimeout(function () {
            el.classList.add('is-hidden');
            window.setTimeout(function () { if (el.parentNode) el.remove(); }, 300);
        }, 4200);
    }

    window.WSLoading = {
        showInitial: showInitial,
        hideInitial: hideInitial,
        sectionStart: sectionStart,
        sectionEnd: sectionEnd,
        resetForPageShow: resetForPageShow,
        toast: toast
    };

    // Backwards compatibility for older inline scripts (idle logout, etc.).
    window.showLoading = showInitial;
})();
