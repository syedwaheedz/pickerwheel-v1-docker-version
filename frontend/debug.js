// Gates the app's verbose narration logging (spin steps, audio loading,
// cache clearing, etc.) behind an explicit flag, so a customer/operator's
// browser console stays clean by default. Real errors (console.error)
// are never gated - only informational/debug narration is.
//
// Enable with ?debug=1 anywhere in the URL (persists across visits via
// localStorage until turned off with ?debug=0), or directly via
// localStorage.setItem('pw_debug', '1') in the console.
(function () {
    try {
        var params = new URLSearchParams(window.location.search);
        if (params.has('debug')) {
            localStorage.setItem('pw_debug', params.get('debug') === '0' ? '0' : '1');
        }
        window.PW_DEBUG = localStorage.getItem('pw_debug') === '1';
    } catch (e) {
        // Private browsing / blocked storage - default to no debug noise.
        window.PW_DEBUG = false;
    }
})();

function dlog(...args) {
    if (window.PW_DEBUG) console.log(...args);
}

function dwarn(...args) {
    if (window.PW_DEBUG) console.warn(...args);
}
