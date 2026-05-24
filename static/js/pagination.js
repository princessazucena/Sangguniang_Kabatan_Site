/**
 * Lightweight client-side pagination.
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
 * If the total number of items is <= page size, no controls are rendered
 * and all items stay visible.
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
        const items = Array.from(
            container.querySelectorAll(':scope > [data-page-item]')
        );
        if (items.length === 0) return;

        const total = items.length;
        const totalPages = Math.ceil(total / pageSize);

        // Nothing to do if everything fits.
        if (totalPages <= 1) return;

        const nav = document.createElement('nav');
        nav.className =
            'pagination-controls flex items-center justify-between gap-3 ' +
            'flex-wrap px-4 py-3 border-t border-slate-100 bg-slate-50 ' +
            'text-sm';
        nav.setAttribute('aria-label', 'Pagination');

        const info = document.createElement('span');
        info.className = 'text-xs text-slate-500';
        nav.appendChild(info);

        const buttons = document.createElement('div');
        buttons.className = 'flex items-center gap-1 flex-wrap';
        nav.appendChild(buttons);

        let current = 1;

        function render() {
            const start = (current - 1) * pageSize;
            const end = start + pageSize;
            items.forEach((el, idx) => {
                el.style.display = idx >= start && idx < end ? '' : 'none';
            });

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

        placeNav(container, nav);
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
