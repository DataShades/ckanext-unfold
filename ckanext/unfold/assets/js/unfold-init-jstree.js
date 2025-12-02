ckan.module("unfold-init-jstree", function ($, _) {
    "use strict";
    return {
        options: {
            data: null,
            resourceId: null,
            resourceViewId: null,
            animationThreshold: 1000,
            searchShowOnlyMatches: true,
            searchCloseOpenedOnClear: false,
            enableSort: true,
            showContextMenu: true,
        },

        initialize: function () {
            $.proxyAll(this, /_/);

            this.tree = $(this.el);
            this.errorBlock = $("#archive-tree-error");
            this.loadState = $(".unfold-load-state");

            $("#jstree-search").on("change", (e) => this.tree.jstree("search", $(e.target).val()));
            $("#jstree-search-clear").click(() => $("#jstree-search").val("").trigger("change"));
            $("#jstree-expand-all").click(() => this.tree.jstree("open_all"));
            $("#jstree-collapse-all").click(() => this.tree.jstree("close_all"));

            // Fetch archive structure data after page load
            $.ajax({
                url: this.sandbox.url("/api/action/get_archive_structure"),
                data: {
                    id: this.options.resourceId,
                    view_id: this.options.resourceViewId,
                },
                success: this._onSuccessRequest,
            });
        },

        _onSuccessRequest: function (data) {
            if (data.result.error) {
                this._displayErrorReason(data.result.error);
            } else {
                this._initJsTree(data.result);
            }
        },

        _displayErrorReason: function (error) {
            $("#archive-tree--loader").remove();
            $("#archive-tree-error span").text(error);
            $("#archive-tree-error").toggle();
        },

        _initJsTree: function (data) {
            let withAnimation = data.length < this.options.animationThreshold;
            let plugins = ["search", "wholerow"];

            if (this.options.showContextMenu) {
                plugins.push("contextmenu");
            }

            if (this.options.enableSort) {
                plugins.push("sort");
            }

            this.tree = $(this.el)
                .on("ready.jstree", () => this.loadState.hide())
                .on("loading.jstree", () => this.loadState.show())
                .jstree({
                    core: {
                        data: data,
                        themes: { dots: false },
                        animation: withAnimation ? 200 : 0,
                    },
                    search: {
                        show_only_matches: this.options.searchShowOnlyMatches,
                        close_opened_onclear: this.options.searchCloseOpenedOnClear,
                        search_callback: (str, node) => {
                            const query = str.toLowerCase();
                            return (
                                node.id.toLowerCase().includes(query) ||
                                node.data?.size?.toLowerCase().includes(query) ||
                                node.data?.modified_at?.toLowerCase().includes(query)
                            );
                        },
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

        _getContextMenuItems: function (node) {
            const items = {};
            const nodeHref = node.a_attr?.href || null;

            if (nodeHref && nodeHref !== "#") {
                items["openURL"] = {
                    label: ckan.i18n._("Open URL"),
                    action: () => {
                        window.open(nodeHref, "_blank");
                    },
                };

                items["copyURL"] = {
                    label: ckan.i18n._("Copy URL"),
                    action: () => {
                        navigator.clipboard.writeText(nodeHref);
                    },
                };
            }

            if (node.children.length > 0) {
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

            if (!Object.keys(items).length) {
                return false;
            }

            return items;
        }
    };
});
