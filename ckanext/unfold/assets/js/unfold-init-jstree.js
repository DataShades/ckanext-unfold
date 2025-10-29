ckan.module("unfold-init-jstree", function ($, _) {
    "use strict";
    return {
        options: {
            data: null,
            resourceId: null,
            resourceViewId: null,
        },

        initialize: function () {
            $.proxyAll(this, /_/);

            this.tree = $(this.el);
            this.errorBlock = $("#archive-tree-error");
            this.loadState = $(".unfold-load-state");

            $("#jstree-search").on("change", (e) => this.tree.jstree("search", $(e.target).val()));
            $("#jstree-search-clear").click(() => $("#jstree-search").val("").trigger("change"));
            $("#jstree-expand-all").click(() => {
                this.loadState.show();
                this.tree.jstree("open_all");
            });
            $("#jstree-collapse-all").click(() => this.tree.jstree("close_all"));

            document.addEventListener("keydown", this._onPageSearch);

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
            $(".archive-tree--spinner").remove();
            $("#archive-tree-error span").text(error);
            $("#archive-tree-error").toggle();
        },

        _initJsTree: function (data) {
            this.tree = $(this.el)
                .on("ready.jstree", () => {
                    this.loadState.hide();
                })
                .on("loading.jstree", () => {
                    this.loadState.show();
                })
                .on("open_all.jstree", () => {
                    this.loadState.hide();
                })
                .jstree({
                    core: {
                        data: data,
                        themes: { dots: false },
                    },
                    search: {
                        show_only_matches: true,
                    },
                    contextmenu: {
                        items: this._getContextMenuItems,
                    },
                    plugins: ["search", "wholerow", "contextmenu"],
                });
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
                        console.log(node);

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
        },

        _onPageSearch: function (e) {
            const isMac = navigator.userAgentData
                ? navigator.userAgentData.platform === "macOS"
                : /Mac/i.test(navigator.userAgent);
            const isSearchShortcut = (isMac && e.metaKey && e.key === "f") || (!isMac && e.ctrlKey && e.key === "f");

            if (isSearchShortcut) {
                e.preventDefault();

                const searchInput = document.querySelector("#jstree-search");

                if (searchInput) {
                    searchInput.focus();
                    searchInput.select();
                }
            }
        },
    };
});
