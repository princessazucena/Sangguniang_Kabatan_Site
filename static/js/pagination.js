/**
 * Lightweight client-side pagination + search filter.
 *
 * Mark the container holding the items with:
 *   data-paginate data-page-size="15"
 *
 * Mark each paginatable child with:
 *   data-page-item
 *
 * Optionally point the controls at a specific element with
 *   data-pagination-into="#some-id"
 * Otherwise the nav is inserted right after the container (or, for a
 * <tbody>, right after its parent <table>).
 *
 * Optionally wire a live search input by giving the container
 *   data-paginate-search="#input-id"
 * The input's text value filters items by their textContent (case
 * insensitive); pagination is recalculated against the visible subset.
 *
 * If the total number of visible items is <= page size, no controls are
 * rendered and all items stay visible.
 */
(function () {
    function makeBtn(label, enabled, onClick, opts) {
        opts = opts || {};
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.textContent = label;
        const base =
            'min-w-[2rem] h-8 px-2 rounded-md text-sm border transition ' +
            'flex items-center justify-center';
        const idle =
            'border-slate-200 bg-white text-slate-600 hover:bg-slate-100';
        const active =
            'border-brand-500 bg-brand-500 text-white hover:bg-brand-600';
        const disabled =
            'border-slate-100 bg-slate-50 text-slate-300 cursor-not-allowed';
        btn.className = base + ' ' + (
            !enabled ? disabled : (opts.active ? active : idle)
        );
        if (!enabled) {
            btn.disabled = true;
        } else {
            btn.addEventListener('click', onClick);
        }
        return btn;
    }

    function makeEllipsis() {
        const span = document.createElement('span');
        span.textContent = '…';
        span.className = 'px-1 text-slate-400 text-sm select-none';
        return span;
    }

    function pageList(current, total) {
        // Always show first, last, current, current±1; collapse the rest.
        const out = new Set([1, total, current, current - 1, current + 1]);
        const pages = Array.from(out)
            .filter((p) => p >= 1 && p <= total)
            .sort((a, b) => a - b);
        const result = [];
        for (let i = 0; i < pages.length; i++) {
            if (i > 0 && pages[i] - pages[i - 1] > 1) result.push('…');
            result.push(pages[i]);
        }
        return result;
    }

    function placeNav(container, nav) {
        const target = container.dataset.paginationInto
            ? document.querySelector(container.dataset.paginationInto)
            : null;
        if (target) {
            target.appendChild(nav);
            return;
        }
        // For a <tbody>, attach after the parent <table>.
        const anchor =
            container.tagName === 'TBODY' && container.parentElement
                ? container.parentElement
                : container;
        anchor.insertAdjacentElement('afterend', nav);
    }

    function init(container) {
        const pageSize = parseInt(container.dataset.pageSize, 10) || 15;
        const allItems = Array.from(
            container.querySelectorAll(':scope > [data-page-item]')
        );
        if (allItems.length === 0) return;

        // Cache the searchable text for each item once so we don't pay
        // for textContent traversal on every keystroke.
        const haystacks = allItems.map((el) =>
            (el.textContent || '').toLowerCase()
        );

        const searchSel = container.dataset.paginateSearch;
        const searchInput = searchSel
            ? document.querySelector(searchSel)
            : null;

        // ---- Lazy-create the nav so we can show/hide it as the visible
        // subset crosses the page-size threshold during search.
        let nav = null;
        let info = null;
        let buttons = null;

        function ensureNav() {
            if (nav) return;
            nav = document.createElement('nav');
            nav.className =
                'pagination-controls flex items-center justify-between gap-3 ' +
                'flex-wrap px-4 py-3 border-t border-slate-100 bg-slate-50 ' +
                'text-sm';
            nav.setAttribute('aria-label', 'Pagination');

            info = document.createElement('span');
            info.className = 'text-xs text-slate-500';
            nav.appendChild(info);

            buttons = document.createElement('div');
            buttons.className = 'flex items-center gap-1 flex-wrap';
            nav.appendChild(buttons);

            placeNav(container, nav);
        }

        let current = 1;
        let visibleItems = allItems.slice();

        function applyFilter() {
            const q = searchInput
                ? (searchInput.value || '').trim().toLowerCase()
                : '';
            visibleItems = [];
            allItems.forEach((el, idx) => {
                const match = !q || haystacks[idx].indexOf(q) !== -1;
                if (match) {
                    visibleItems.push(el);
                } else {
                    // Hidden by filter (different from hidden by paging).
                    el.style.display = 'none';
                }
            });
            current = 1;
            render();
        }

        function render() {
            const total = visibleItems.length;
            const totalPages = Math.max(1, Math.ceil(total / pageSize));
            if (current > totalPages) current = totalPages;

            const start = (current - 1) * pageSize;
            const end = start + pageSize;
            visibleItems.forEach((el, idx) => {
                el.style.display = idx >= start && idx < end ? '' : 'none';
            });

            if (totalPages <= 1) {
                if (nav) nav.style.display = 'none';
                return;
            }
            ensureNav();
            nav.style.display = '';

            const shown = Math.min(end, total) - start;
            info.textContent =
                'Showing ' + (start + 1) + '–' + (start + shown) +
                ' of ' + total;

            buttons.innerHTML = '';
            buttons.appendChild(
                makeBtn('‹', current > 1, function () {
                    current = Math.max(1, current - 1);
                    render();
                })
            );
            pageList(current, totalPages).forEach(function (p) {
                if (p === '…') {
                    buttons.appendChild(makeEllipsis());
                } else {
                    buttons.appendChild(
                        makeBtn(String(p), true, function () {
                            current = p;
                            render();
                        }, { active: p === current })
                    );
                }
            });
            buttons.appendChild(
                makeBtn('›', current < totalPages, function () {
                    current = Math.min(totalPages, current + 1);
                    render();
                })
            );
        }

        if (searchInput) {
            // Debounced filter so typing fast feels snappy without
            // hammering layout on every keystroke.
            let pending = null;
            searchInput.addEventListener('input', function () {
                if (pending) clearTimeout(pending);
                pending = setTimeout(applyFilter, 80);
            });
        }

        // Initial render: show first page of the unfiltered list.
        render();
    }

    function boot() {
        document
            .querySelectorAll('[data-paginate]')
            .forEach(init);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
})();
