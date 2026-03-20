(function () {
    'use strict';

    /**
     * Matches Python's _make_slug() applied to heading textContent
     * (no markdown markers to strip — heading DOM text has none).
     */
    function makeSlug(text) {
        var t = (text || '').toLowerCase().trim();
        // "2.4. " (digit/letter + literal-dot + whitespace) → "2.4-"
        t = t.replace(/([a-z0-9])\.\s/g, '$1-');
        // Anything not a-z, 0-9, or literal dot → hyphen
        t = t.replace(/[^a-z0-9.]+/g, '-');
        // Cleanup
        t = t.replace(/-+/g, '-').replace(/^-+|-+$/g, '').replace(/\.$/, '');
        return t;
    }

    /** Assign id to every heading inside .doc-content-card that lacks one. */
    function assignHeadingIds() {
        document.querySelectorAll(
            '.doc-content-card h1,.doc-content-card h2,.doc-content-card h3,' +
            '.doc-content-card h4,.doc-content-card h5,.doc-content-card h6'
        ).forEach(function (h) {
            if (!h.id) {
                h.id = makeSlug(h.textContent || '');
            }
        });
    }

    /** Scroll to the element whose id matches the current URL hash. */
    function scrollToHash() {
        var hash = window.location.hash.slice(1);
        if (!hash) return;
        var el = document.getElementById(hash);
        if (el) el.scrollIntoView({ behavior: 'smooth' });
    }

    // Re-assign IDs whenever React re-renders content (debounced).
    var debounceTimer;
    new MutationObserver(function () {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(assignHeadingIds, 50);
    }).observe(document.documentElement, { childList: true, subtree: true });

    // Native hashchange fires for every same-page anchor click.
    window.addEventListener('hashchange', function () {
        // Small delay to let MutationObserver flush first.
        setTimeout(scrollToHash, 60);
    });

    // Initial load: assign IDs, then scroll if hash is present.
    if (document.readyState !== 'loading') {
        assignHeadingIds();
        scrollToHash();
    } else {
        document.addEventListener('DOMContentLoaded', function () {
            assignHeadingIds();
            scrollToHash();
        });
    }
}());
