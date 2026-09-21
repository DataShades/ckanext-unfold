ckan.module("unfold-init-jstree", function ($, _) {
    "use strict";
    return {
        options: {
            resourceId: null,
            resourceViewId: null,
            animationThreshold: 1000,
            searchShowOnlyMatches: true,
            searchCloseOpenedOnClear: false,
            searchLimit: 200,
            searchDebounce: 250,
            pageSize: 500,
            showContextMenu: true,
        },

        initialize: function () {
            $.proxyAll(this, /_/);

            this.el.css("visibility", "visible");

            this.panel = this.el.find(".unfold-panel");
            this.tree = this.el.find(".unf-tree");
            this.errorBlock = this.el.find(".unf-tree-error");
            this.errorMessage = this.errorBlock.find(".unfold-error-message");
            this.retryButton = this.el.find(".unf-tree-retry");
            // re-runs the request whose failure is currently displayed
            this.retry = null;
            this.loadState = this.el.find(".unfold-load-state");
            this.meta = this.el.find(".unfold-tree-meta");
            this.toast = this.el.find(".unfold-toast");
            this._toastTimer = null;
            this.expandAll = this.el.find(".unf-expand-all");
            this.results = this.el.find(".unfold-search-results");
            this.searchInput = this.el.find(".unf-search-input");
            this.searchClear = this.el.find(".jstree-search-clear");
            this.controls = this.el.find(
                ".unf-search-input, .unf-search-run, .unf-expand-all, .unf-collapse-all"
            );
            // "full": every node is in the DOM; "lazy": folders load on open
            this.mode = null;
            this.total = 0;
            // lazy mode: how many children each folder currently shows
            this.folderLimits = {};

            const debouncedSearch = this._debounce(this._search, this.options.searchDebounce);

            this.searchInput.on("input", (e) => {
                this._toggleSearchClear();
                debouncedSearch($(e.target).val());
            });
            this.el.find(".unf-search-run").click(() => this._search(this.searchInput.val()));
            this.searchClear.click(() => {
                this.searchInput.val("").trigger("focus");
                this._toggleSearchClear();
                this._clearSearch();
            });
            this.expandAll.click(() => this.tree.jstree("open_all"));
            this.el.find(".unf-collapse-all").click(() => this.tree.jstree("close_all"));
            this.retryButton.click(() => {
                if (this.retry) {
                    this.retry();
                }
            });

            this._observeMetadata();
            this._initJsTree();
        },

        /**
         * Returns a version of `fn` that only runs `wait` ms after the last
         * call, so a fast typist triggers one search instead of one per
         * keystroke.
         */
        _debounce: function (fn, wait) {
            let timer = null;

            return (...args) => {
                clearTimeout(timer);
                timer = setTimeout(() => fn(...args), wait);
            };
        },

        teardown: function () {
            if (this._metadataObserver) {
                this._metadataObserver.disconnect();
            }
        },

        _payload: function (extra) {
            const payload = $.extend({ id: this.options.resourceId }, extra);

            if (this.options.resourceViewId && this.options.resourceViewId !== true) {
                payload.view_id = this.options.resourceViewId;
            }

            return payload;
        },

        _moreNodeId: function (parentId) {
            return parentId + "::unfold-more";
        },

        /**
         * jstree `core.data` callback. Called once with the root ("#") and,
         * in lazy mode, again for every folder the user opens (or reloads
         * after "show more").
         */
        _loadNodes: function (node, callback) {
            const instance = this.tree.jstree(true);

            this._clearError();
            this._setBusy(true);

            const limit = this.folderLimits[node.id] || this.options.pageSize;
            const retry = node.id === "#"
                ? () => instance.refresh()
                : () => instance.load_node(node.id, (loaded, ok) => ok && instance.open_node(loaded));

            $.ajax({
                url: this.sandbox.url("/api/action/get_archive_structure"),
                data: this._payload({ parent: node.id, limit: limit }),
            })
                .done((response) => {
                    const result = response.result;

                    if (result.error) {
                        // the archive itself could not be read: there is no
                        // tree to fall back to, so the panel comes down
                        this._displayApiError(result.error, { retry: retry, fatal: node.id === "#" });
                        callback.call(instance, []);
                        return;
                    }

                    let nodes = result.nodes;

                    // Any exception here would leave jstree's own "Loading ..."
                    // placeholder in place forever, so surface it instead.
                    try {
                        if (node.id === "#") {
                            this.mode = result.mode;
                            this.total = result.total;
                            this._applyMode();
                        }

                        if (result.has_more) {
                            nodes.push(this._moreNode(node.id, nodes.length, result.children_total));
                        }
                    } catch (e) {
                        this._displayErrorReason(String(e), { fatal: node.id === "#" });
                        nodes = [];
                    }

                    callback.call(instance, nodes);
                })
                .fail((xhr) => {
                    if (node.id === "#") {
                        // An empty root lets jstree finish initialising and
                        // drop its own "Loading ..." row; refresh() re-runs
                        // this callback for the root.
                        callback.call(instance, []);
                        this._displayErrorReason(
                            this._requestFailure(ckan.i18n._("Could not load the archive listing"), xhr),
                            { retry: retry, fatal: true }
                        );
                        return;
                    }

                    // `false` leaves the folder unloaded, so opening it
                    // again requests it again.
                    callback.call(instance, false);
                    // the rest of the tree is still valid, so it stays visible
                    this._displayErrorReason(
                        this._requestFailure(ckan.i18n._("Could not load folder %(name)s", { name: node.id }), xhr),
                        { retry: retry }
                    );
                })
                .always(() => this._setBusy(false));
        },

        /** Toggles the toolbar spinner and the tree's busy state together. */
        _setBusy: function (busy) {
            this.loadState.prop("hidden", !busy);
            this.tree.attr("aria-busy", busy ? "true" : "false");
        },

        _requestFailure: function (message, xhr) {
            return xhr.status ? message + " (HTTP " + xhr.status + ")" : message;
        },

        _moreNode: function (parentId, shown, total) {
            const text = ckan.i18n._("Show more (%(shown)s of %(total)s shown)", {
                shown: shown.toLocaleString(),
                total: total.toLocaleString(),
            });

            return {
                id: this._moreNodeId(parentId),
                text: text,
                icon: "fa fa-ellipsis-h",
                li_attr: { class: "unfold-load-more" },
                data: { load_more: true, parent: parentId },
                children: false,
            };
        },

        _loadMore: function (parentId) {
            const instance = this.tree.jstree(true);
            const current = this.folderLimits[parentId] || this.options.pageSize;

            this.folderLimits[parentId] = current + this.options.pageSize;

            // reloading the folder replaces its children in a single redraw
            instance.load_node(parentId, (node, ok) => ok && instance.open_node(node));
        },

        _applyMode: function () {
            if (!this.mode) {
                // the root never loaded, so there is nothing to show yet
                return;
            }

            const count = this.total.toLocaleString();

            this.panel.prop("hidden", false);
            this.controls.prop("disabled", false);

            if (this.mode === "lazy") {
                this.meta.text(ckan.i18n._("%(count)s entries, folders load when opened", { count: count }));
                // open_all would request every folder in the archive
                this.expandAll.prop("disabled", true)
                    .attr("title", ckan.i18n._("Not available for large archives"));
            } else {
                this.meta.text(ckan.i18n._("%(count)s entries", { count: count }));
            }
        },

        _search: function (query) {
            query = (query || "").trim();

            if (!query) {
                this._clearSearch();
                return;
            }

            this._clearError();

            if (this.mode !== "lazy") {
                this.tree.jstree("search", query);
                return;
            }

            // Large archive: matches may sit in folders that are not loaded
            // (or past their first page), so results are shown as a flat
            // list instead of highlighted in the tree.
            this._setBusy(true);

            $.ajax({
                url: this.sandbox.url("/api/action/search_archive_structure"),
                data: this._payload({ q: query, limit: this.options.searchLimit }),
            })
                .done((response) => {
                    const result = response.result;

                    if (result.error) {
                        this._displayApiError(result.error, { retry: () => this._search(query) });
                        return;
                    }

                    try {
                        let text = ckan.i18n._("%(count)s matches", { count: result.matches.toLocaleString() });

                        if (result.truncated) {
                            text += " " + ckan.i18n._("(showing the first %(limit)s)", { limit: this.options.searchLimit });
                        }

                        this.meta.text(text);
                        this._showResults(result.results);
                    } catch (e) {
                        this._displayErrorReason(String(e));
                    }
                })
                // whatever is on screen - the tree or the previous result
                // list - is still valid, so only the message is added
                .fail((xhr) => this._displayErrorReason(
                    this._requestFailure(ckan.i18n._("Search failed"), xhr),
                    { retry: () => this._search(query) }
                ))
                .always(() => this._setBusy(false));
        },

        _showResults: function (rows) {
            const list = this.results.empty();

            if (!rows.length) {
                list.append($("<div>", { class: "unfold-result unfold-result--empty", text: ckan.i18n._("No entries match") }));
            }

            rows.forEach((row) => {
                // text() everywhere: names come from the archive and are untrusted
                const item = $("<div>", { class: "unfold-result" });
                $("<i>", { class: row.icon + " unfold-result-icon" }).appendTo(item);
                $("<span>", { class: "unfold-result-path", text: row.id, title: row.id }).appendTo(item);
                $("<span>", { class: "unfold-node-metadata d-none d-md-block" })
                    .append($("<span>", { class: "unfold-node-size", text: row.size }))
                    .append($("<span>", { class: "unfold-node-modified-at", text: row.modified_at }))
                    .appendTo(item);
                list.append(item);
            });

            this.tree.prop("hidden", true);
            list.prop("hidden", false);
        },

        _clearSearch: function () {
            this._clearError();

            if (this.mode === "lazy") {
                this.results.prop("hidden", true).empty();
                this.tree.prop("hidden", false);
            } else {
                this.tree.jstree("clear_search");
            }

            this._applyMode();
        },

        _toggleSearchClear: function () {
            this.searchClear.prop("hidden", !this.searchInput.val().length);
        },

        /**
         * Show the `{code, message}` error the API returns for an archive it
         * could not list. Only a failed download (`fetch_failed`) keeps the
         * `options.retry` button: a wrong password or an archive over the size
         * limit fails the same way every time.
         */
        _displayApiError: function (error, options) {
            options = $.extend({}, options);

            if (error.code !== "fetch_failed") {
                delete options.retry;
            }

            this._displayErrorReason(error.message, options);
        },

        /**
         * Show `error` above the widget.
         *
         * `options.retry` adds a Retry button that calls it.
         * `options.fatal` means nothing was loaded at all, so the tree
         * and its header are taken down with it - otherwise they keep showing
         * whatever loaded before the failure.
         */
        _displayErrorReason: function (error, options) {
            options = options || {};

            this.retry = options.retry || null;
            this.retryButton.prop("hidden", !this.retry);
            this.errorMessage.text(error);
            this.errorBlock.prop("hidden", false);

            if (options.fatal) {
                this.panel.prop("hidden", true);
                this.controls.prop("disabled", true);
                this.meta.text("");
            }
        },

        _clearError: function () {
            this.retry = null;
            this.errorBlock.prop("hidden", true);
        },

        _initJsTree: function () {
            let plugins = ["search", "wholerow"];

            if (this.options.showContextMenu) {
                plugins.push("contextmenu");
            }

            this.tree
                .on("ready.jstree", () => {
                    if (this.total < this.options.animationThreshold) {
                        this.tree.jstree(true).settings.core.animation = 200;
                    }
                })
                .on("activate_node.jstree", (_, data) => {
                    // The contextmenu plugin activates the node under a right
                    // click (to highlight the row the menu is for), which is
                    // not a request to open it or to load more entries.
                    if (data.event && data.event.type === "contextmenu") {
                        return;
                    }

                    if (data.node.data && data.node.data.load_more) {
                        this._loadMore(data.node.data.parent);
                        return;
                    }

                    this.tree.jstree("toggle_node", data.node);
                })
                .jstree({
                    core: {
                        data: this._loadNodes,
                        themes: { dots: false },
                        strings: { "Loading ...": ckan.i18n._("Loading...") },
                        // animation is decided once the size is known
                        animation: 0,
                        multiple: false,
                        force_text: true,
                    },
                    search: {
                        show_only_matches: this.options.searchShowOnlyMatches,
                        close_opened_onclear: this.options.searchCloseOpenedOnClear,
                        // Path only: matching size/date rarely helps and
                        // tripled the work per node for no real benefit.
                        search_callback: (str, node) =>
                            node.id.toLowerCase().includes(str.toLowerCase()),
                    },
                    contextmenu: {
                        items: this._getContextMenuItems,
                    },
                    plugins: plugins,
                });

            if (!this.options.showContextMenu) {
                this.tree.on("select_node.jstree", (_, data) => {
                    const node = data.node;
                    const nodeHref = node.a_attr?.href || null;
                    const nodeTarget = node.a_attr?.target || "_self";

                    if (nodeHref && nodeHref !== "#") {
                        window.open(nodeHref, nodeTarget);
                    }
                });
            }
        },

        /**
         * jstree redraws by emptying and rebuilding whichever part of the
         * tree changed (a folder opening, a page loading, a search
         * filtering), so there is no single reliable "node rendered" event
         * to hook. Watching the DOM directly catches every anchor jstree
         * ever adds, however it got there.
         */
        _observeMetadata: function () {
            this._metadataObserver = new MutationObserver((mutations) => {
                const instance = this.tree.jstree(true);

                if (!instance) {
                    return;
                }

                mutations.forEach((mutation) => {
                    mutation.addedNodes.forEach((added) => {
                        if (added.nodeType !== Node.ELEMENT_NODE) {
                            return;
                        }

                        if (added.matches(".jstree-anchor")) {
                            this._decorateAnchor(added, instance);
                        }

                        added.querySelectorAll(".jstree-anchor").forEach((anchor) =>
                            this._decorateAnchor(anchor, instance)
                        );
                    });
                });
            });

            this._metadataObserver.observe(this.tree[0], { childList: true, subtree: true });
        },

        /**
         * Append the size/modified-at spans jstree does not know about.
         * Built with textContent, never innerHTML: `data.size` and
         * `data.modified_at` come from the archive and are untrusted.
         */
        _decorateAnchor: function (anchor, instance) {
            if (anchor.dataset.unfoldDecorated) {
                return;
            }

            anchor.dataset.unfoldDecorated = "1";

            const li = anchor.closest(".jstree-node");
            const node = li && instance.get_node(li.id);
            const data = node && node.data;

            if (!data || (!data.size && !data.modified_at)) {
                return;
            }

            const meta = document.createElement("span");
            meta.className = "unfold-node-metadata d-none d-md-block";

            if (data.size) {
                const size = document.createElement("span");
                size.className = "unfold-node-size";
                size.textContent = data.size;
                meta.appendChild(size);
            }

            if (data.modified_at) {
                const modifiedAt = document.createElement("span");
                modifiedAt.className = "unfold-node-modified-at";
                modifiedAt.textContent = data.modified_at;
                meta.appendChild(modifiedAt);
            }

            anchor.appendChild(meta);
        },

        _getContextMenuItems: function (node) {
            const items = {};
            const nodeHref = node.a_attr?.href || null;

            if (node.data && node.data.load_more) {
                return false;
            }

            if (node.children.length > 0 || node.state.loaded === false) {
                items["toggle"] = {
                    label: node.state.opened ? ckan.i18n._("Collapse") : ckan.i18n._("Expand"),
                    action: () => {
                        if (node.state.opened) {
                            this.tree.jstree("close_node", node);
                        } else {
                            this.tree.jstree("open_node", node);
                        }
                    },
                };
            }

            // every entry has a path, whatever the adapter, so this item keeps
            // the menu useful for archives whose nodes carry no link
            items["copyPath"] = {
                label: ckan.i18n._("Copy path"),
                action: () => this._copyText(node.id, ckan.i18n._("Path copied")),
            };

            // links only come from custom adapters (`a_attr.href`)
            if (nodeHref && nodeHref !== "#") {
                items["openURL"] = {
                    label: ckan.i18n._("Open URL"),
                    action: () => {
                        window.open(nodeHref, "_blank");
                    },
                };

                items["copyURL"] = {
                    label: ckan.i18n._("Copy URL"),
                    action: () => this._copyText(nodeHref, ckan.i18n._("URL copied")),
                };
            }

            return items;
        },

        /**
         * Put `text` on the clipboard and say so. `navigator.clipboard` only
         * exists on secure (HTTPS or localhost) pages, and CKAN is often served
         * over plain HTTP, so fall back to a selected textarea there; if that
         * fails too the user is told instead of nothing happening.
         */
        _copyText: function (text, successMessage) {
            const failed = () => this._notify(ckan.i18n._("Could not copy"), true);
            const copied = () => this._notify(successMessage);

            if (navigator.clipboard && window.isSecureContext) {
                navigator.clipboard.writeText(text).then(copied, failed);
                return;
            }

            if (this._copyWithSelection(text)) {
                copied();
            } else {
                failed();
            }
        },

        _copyWithSelection: function (text) {
            const area = document.createElement("textarea");
            area.value = text;
            area.setAttribute("readonly", "");
            area.style.position = "fixed";
            area.style.opacity = "0";
            document.body.appendChild(area);
            area.select();

            let ok = false;

            try {
                ok = document.execCommand("copy");
            } catch (e) {
                ok = false;
            }

            area.remove();

            return ok;
        },

        /** Show a short message in the toolbar, announced to screen readers. */
        _notify: function (message, isError) {
            clearTimeout(this._toastTimer);

            this.toast
                .toggleClass("text-danger", !!isError)
                .toggleClass("text-success", !isError)
                .text(message);

            this._toastTimer = setTimeout(() => this.toast.text(""), 2500);
        }
    };
});
