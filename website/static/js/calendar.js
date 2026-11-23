/* WanderShots admin calendar: async range loading, details modal, sync retry. */
(function () {
    'use strict';

    var calendarEl = document.getElementById('calendar');
    var configEl = document.getElementById('calendarConfig');
    if (!calendarEl || !configEl) return;

    if (!window.FullCalendar) {
        if (window.WSLoading) window.WSLoading.toast('Calendar library could not be loaded.', 'error');
        return;
    }

    var eventsUrl = configEl.dataset.eventsUrl;
    var retrySyncUrl = configEl.dataset.retrySyncUrl;
    var retryBookingUrl = configEl.dataset.retryBookingUrl;
    var csrfToken = configEl.dataset.csrfToken;
    var loginUrl = configEl.dataset.loginUrl || '/login';
    var googleConnected = configEl.dataset.googleConnected === '1';
    var skeleton = document.getElementById('calendarSkeleton');
    var eventModal = document.getElementById('eventModal');
    var blockedModal = document.getElementById('blockedDatesModal');
    var retryButton = document.getElementById('m-retry-btn');
    var syncBadge = document.getElementById('m-sync-badge');
    var syncError = document.getElementById('m-sync-error');
    var activeRequest = null;
    var activeRetry = null;

    var STATUS_LABELS = {
        synced: 'Synced',
        pending: 'Sync pending',
        processing: 'Syncing',
        failed: 'Sync failed',
        cancelled: 'Removed from Google',
        disconnected: 'Reconnect needed',
        skipped: 'Not synced',
        not_synced: 'Not synced'
    };

    function showSkeleton() {
        if (skeleton) skeleton.classList.add('is-visible');
    }

    function hideSkeleton() {
        if (skeleton) skeleton.classList.remove('is-visible');
    }

    function toast(message, type) {
        if (window.WSLoading) window.WSLoading.toast(message, type);
    }

    function redirectToLogin() {
        window.location.href = loginUrl + '?next=' + encodeURIComponent(window.location.pathname);
    }

    function openModal(modal) {
        if (!modal) return;
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        document.body.style.overflow = 'hidden';
    }

    function closeModal(modal) {
        if (!modal) return;
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        document.body.style.overflow = '';
    }

    function setText(id, value) {
        var el = document.getElementById(id);
        if (el) el.textContent = value || 'N/A';
    }

    function setSyncBadge(status) {
        if (!syncBadge) return;
        var safeStatus = STATUS_LABELS[status] ? status : 'not_synced';
        syncBadge.className = 'ws-sync-badge ws-sync-' + safeStatus;
        syncBadge.textContent = STATUS_LABELS[safeStatus] || 'Not synced';
    }

    function setRetryButton(bookingId, syncId, status) {
        if (!retryButton) return;
        var canRetry = googleConnected && ['failed', 'not_synced', 'disconnected', 'skipped'].indexOf(status) !== -1;
        retryButton.classList.toggle('hidden', !canRetry);
        retryButton.dataset.bookingId = bookingId || '';
        retryButton.dataset.syncId = syncId || '';
        retryButton.disabled = false;
        retryButton.textContent = 'Retry synchronization';
    }

    function showBookingDetails(props) {
        document.getElementById('modal-title').textContent = 'Booking Details';
        document.getElementById('standard-details').classList.remove('hidden');
        document.getElementById('blocked-details').classList.add('hidden');

        setText('m-customer', props.customer);
        setText('m-email', props.email);
        setText('m-service', props.service);
        setText('m-location', props.location || 'In Studio');
        setText('m-package', props.package || 'None Selected');
        setText('m-notes', props.notes || 'No notes provided.');

        var status = props.sync_status || 'not_synced';
        setSyncBadge(status);
        if (syncError) {
            syncError.textContent = props.sync_error || '';
            syncError.classList.toggle('hidden', !props.sync_error);
        }
        setRetryButton(props.booking_id, props.sync_id, status);
    }

    function showBlockedDetails(props) {
        document.getElementById('modal-title').textContent = 'Date Blocked';
        document.getElementById('standard-details').classList.add('hidden');
        document.getElementById('blocked-details').classList.remove('hidden');
        setText('m-blocked-reason', props.notes || 'No reason provided');
    }

    function loadEvents(info, successCallback, failureCallback) {
        if (!navigator.onLine) {
            showSkeleton();
            window.setTimeout(function () {
                hideSkeleton();
                successCallback([]);
                toast('You are offline. Live calendar data could not be loaded.', 'error');
            }, 250);
            return;
        }

        if (activeRequest) activeRequest.abort();
        activeRequest = new AbortController();

        var url = new URL(eventsUrl, window.location.origin);
        url.searchParams.set('start', info.startStr);
        url.searchParams.set('end', info.endStr);

        showSkeleton();
        fetch(url.toString(), {
            method: 'GET',
            credentials: 'same-origin',
            cache: 'no-store',
            headers: { 'Accept': 'application/json' },
            signal: activeRequest.signal
        }).then(function (response) {
            var contentType = response.headers.get('content-type') || '';
            if (response.redirected && response.url.indexOf('/login') !== -1) {
                redirectToLogin();
                throw { handled: true };
            }
            if (response.status === 401 || response.status === 403) {
                redirectToLogin();
                throw { handled: true };
            }
            if (!response.ok) throw new Error('Calendar request failed with status ' + response.status);
            if (contentType.indexOf('application/json') === -1) {
                throw new Error('Calendar returned an unexpected response.');
            }
            return response.json();
        }).then(function (data) {
            hideSkeleton();
            successCallback((data && data.events) || []);
        }).catch(function (error) {
            hideSkeleton();
            if (error && error.name === 'AbortError') return;
            if (error && error.handled) return;
            failureCallback(error instanceof Error ? error : new Error('Calendar request failed.'));
            toast('Calendar could not be refreshed. Check your connection and try again.', 'error');
        });
    }

    var calendar = new FullCalendar.Calendar(calendarEl, {
        initialView: window.innerWidth < 768 ? 'timeGridDay' : 'dayGridMonth',
        timeZone: 'Asia/Manila',
        headerToolbar: {
            left: 'prev,next today',
            center: 'title',
            right: 'dayGridMonth,timeGridWeek,timeGridDay'
        },
        eventTimeFormat: { hour: 'numeric', minute: '2-digit', meridiem: 'short' },
        height: 'auto',
        nowIndicator: true,
        dayMaxEvents: true,
        events: loadEvents,
        loading: function (isLoading) {
            if (isLoading) showSkeleton();
            else hideSkeleton();
        },
        eventDidMount: function (info) {
            var status = info.event.extendedProps.sync_status;
            if (status) info.el.setAttribute('data-sync-status', status);
        },
        eventClick: function (info) {
            info.jsEvent.preventDefault();
            var props = info.event.extendedProps || {};
            if (props.kind === 'blocked' || props.status === 'blocked') {
                showBlockedDetails(props);
            } else {
                showBookingDetails(props);
            }
            openModal(eventModal);
        }
    });

    calendar.render();

    function retrySynchronization() {
        if (!retryButton || activeRetry) return;
        var syncId = retryButton.dataset.syncId;
        var bookingId = retryButton.dataset.bookingId;
        var url;
        if (syncId) {
            url = retrySyncUrl.replace(/0$/, syncId);
        } else if (bookingId) {
            url = retryBookingUrl.replace(/0$/, bookingId);
        } else {
            toast('This booking cannot be retried yet.', 'error');
            return;
        }

        activeRetry = true;
        retryButton.disabled = true;
        retryButton.textContent = 'Queueing...';

        fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            redirect: 'follow',
            headers: {
                'X-CSRF-Token': csrfToken,
                'Accept': 'text/html,application/json'
            }
        }).then(function (response) {
            if (response.redirected && response.url.indexOf('/login') !== -1) {
                redirectToLogin();
                return null;
            }
            if (!response.ok) throw new Error('Retry failed with status ' + response.status);
            return response;
        }).then(function (response) {
            if (!response) return;
            toast('Synchronization queued. Refreshing calendar...', 'success');
            window.setTimeout(function () {
                calendar.refetchEvents();
            }, 1200);
        }).catch(function () {
            toast('Synchronization could not be queued. Please try again.', 'error');
        }).finally(function () {
            activeRetry = null;
            if (retryButton) {
                retryButton.disabled = false;
                retryButton.textContent = 'Retry synchronization';
            }
        });
    }

    if (retryButton) retryButton.addEventListener('click', retrySynchronization);

    document.querySelectorAll('[data-close-modal]').forEach(function (button) {
        button.addEventListener('click', function () { closeModal(eventModal); });
    });

    if (eventModal) {
        eventModal.addEventListener('click', function (event) {
            if (event.target === eventModal) closeModal(eventModal);
        });
    }

    document.querySelectorAll('[data-open-blocked]').forEach(function (button) {
        button.addEventListener('click', function () { openModal(blockedModal); });
    });

    document.querySelectorAll('[data-close-blocked]').forEach(function (button) {
        button.addEventListener('click', function () { closeModal(blockedModal); });
    });

    if (blockedModal) {
        blockedModal.addEventListener('click', function (event) {
            if (event.target === blockedModal) closeModal(blockedModal);
        });
    }

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') {
            closeModal(eventModal);
            closeModal(blockedModal);
        }
    });
})();
