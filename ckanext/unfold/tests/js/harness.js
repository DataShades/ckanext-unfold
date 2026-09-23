"use strict";

/**
 * Loads `unfold-init-jstree.js` the way CKAN does, without CKAN: the real
 * jQuery and the vendored jstree run in a jsdom window, and only what CKAN
 * itself provides (`ckan.module`, `ckan.i18n`, `$.proxyAll`, the sandbox) is
 * stubbed. The API is a plain function per action, so a test decides what
 * every request gets back.
 */

const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const ASSETS = path.join(__dirname, "..", "..", "assets");
const JQUERY = require.resolve("jquery/dist/jquery.js");
const JSTREE = path.join(ASSETS, "vendor", "jstree.min.js");
const MODULE = path.join(ASSETS, "js", "unfold-init-jstree.js");

// The class names and data attributes the module looks for. Keep in step with
// `unfold_preview.html`; `test_templates.py` checks the template against the
// module's own selectors.
const MARKUP = `
<div class="unfold-preview" data-module="unfold-init-jstree" style="visibility: hidden">
  <input class="unf-search-input" type="text" disabled>
  <button class="jstree-search-clear" type="button" hidden></button>
  <button class="unf-search-run" type="button" disabled></button>
  <button class="unf-expand-all" type="button" disabled></button>
  <button class="unf-collapse-all" type="button" disabled></button>
  <span class="unfold-load-state" hidden></span>
  <span class="unfold-tree-meta"></span>
  <span class="unfold-toast"></span>
  <div class="unf-tree-error" hidden>
    <span class="unfold-error-message"></span>
    <button class="unf-tree-retry" type="button" hidden></button>
  </div>
  <div class="unf-tree-processing" hidden></div>
  <div class="unfold-panel">
    <div class="unfold-search-results" hidden></div>
    <div class="unf-tree"></div>
  </div>
</div>`;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Wait until `check()` is truthy; the failure says what was being waited for. */
async function waitFor(check, what = "condition", timeout = 3000) {
    const started = Date.now();

    while (!check()) {
        if (Date.now() - started > timeout) {
            throw new Error(`Timed out waiting for ${what}`);
        }

        await sleep(5);
    }
}

/**
 * A node as `get_archive_structure` returns it. Full mode sends every entry
 * flat with its `parent`, opened; lazy mode nests one folder's children and
 * marks a folder `children: true` until it is opened.
 */
function node(id, { folder = false, lazy = false, size = "1 KB", modified = "2026-01-01", ...extra } = {}) {
    const parts = id.split("/");
    const result = {
        id,
        text: parts[parts.length - 1],
        icon: folder ? "fa fa-folder" : "fa fa-file",
        state: { opened: !lazy },
        data: { size, modified_at: modified },
        li_attr: {},
        a_attr: {},
        children: lazy ? folder : false,
    };

    if (!lazy) {
        result.parent = parts.length > 1 ? parts.slice(0, -1).join("/") : "#";
    }

    return { ...result, ...extra };
}

/** A whole-archive response. */
const fullResponse = (...nodes) => ({ mode: "full", total: nodes.length, has_more: false, nodes });

/** One folder's page of a large archive. */
const lazyResponse = (nodes, { total = 100, childrenTotal = nodes.length } = {}) => ({
    mode: "lazy",
    total,
    children_total: childrenTotal,
    has_more: childrenTotal > nodes.length,
    nodes,
});

/**
 * Build a page holding the widget and start the module on it.
 *
 * `api` maps an action name to `(data) => response`. A response is either the
 * `result` object, `{ fail: 500 }` for an HTTP error, or a promise of either
 * (used to keep a request pending). Requests are recorded in `calls`.
 */
async function mount({ api = {}, options = {}, secure = true, wait = true } = {}) {
    const dom = new JSDOM(`<!DOCTYPE html><body>${MARKUP}</body>`, {
        runScripts: "outside-only",
        pretendToBeVisual: true,
        url: secure ? "https://ckan.test/" : "http://ckan.test/",
    });
    const { window } = dom;

    window.eval(fs.readFileSync(JQUERY, "utf8"));
    window.eval(fs.readFileSync(JSTREE, "utf8"));

    const $ = window.jQuery;

    // jstree builds its context menu element in a jQuery ready callback, which
    // jsdom runs on a later tick
    await waitFor(() => $.isReady, "jQuery to be ready");

    const calls = [];
    const modules = {};

    // CKAN's jquery.proxy-all.js
    $.proxyAll = (obj, ...methods) => {
        for (const method of methods) {
            for (const property in obj) {
                if (typeof obj[property] === "function" && method.test(property)) {
                    obj[property] = $.proxy(obj[property], obj);
                }
            }
        }

        return obj;
    };

    // `$.ajax` is replaced rather than the transport underneath it, so the
    // module sees the same `done` / `fail` / `always` chain it gets from jqXHR.
    $.ajax = (settings) => {
        const action = settings.url.replace("/api/action/", "");
        const deferred = $.Deferred();
        const call = { action, data: settings.data, url: settings.url };

        calls.push(call);

        const handler = api[action];

        if (!handler) {
            deferred.reject({ status: 404 });
            return deferred.promise();
        }

        Promise.resolve(handler(settings.data)).then((response) => {
            if (response && response.fail) {
                deferred.reject({ status: response.fail });
            } else {
                deferred.resolve({ success: true, result: response });
            }
        });

        return deferred.promise();
    };

    window.ckan = {
        // Placeholders are substituted the way `ckan.i18n._` does with a
        // values dict; a string that has placeholders but is given none is a
        // bug in the module, so it throws (it does in CKAN too).
        i18n: {
            _: (text, values) => {
                const placeholders = text.match(/%\((\w+)\)s/g) || [];

                if (placeholders.length && !values) {
                    throw new Error(`No values for placeholders in ${JSON.stringify(text)}`);
                }

                return text.replace(/%\((\w+)\)s/g, (_, key) => values[key]);
            },
        },
        module: (name, factory) => {
            modules[name] = factory;
        },
    };

    window.eval(fs.readFileSync(MODULE, "utf8"));

    const element = window.document.querySelector(".unfold-preview");
    const definition = modules["unfold-init-jstree"]($, window.ckan.i18n._);
    const instance = Object.create(definition);

    instance.el = $(element);
    instance.options = $.extend(true, {}, definition.options, {
        resourceId: "res-1",
        resourceViewId: "view-1",
        // fast enough for a test to wait on
        pollInterval: 10,
        pollMaxInterval: 20,
        searchDebounce: 5,
        ...options,
    });
    instance.sandbox = { url: (p) => p };

    // Clipboard and the selection fallback, which jsdom does not implement
    const clipboard = { written: [], reject: false };
    const selection = { copied: [], ok: true };

    Object.defineProperty(window.navigator, "clipboard", {
        configurable: true,
        value: {
            writeText: (text) => {
                if (clipboard.reject) {
                    return Promise.reject(new Error("denied"));
                }

                clipboard.written.push(text);
                return Promise.resolve();
            },
        },
    });
    window.document.execCommand = () => {
        const area = window.document.querySelector("textarea");

        selection.copied.push(area && area.value);
        return selection.ok;
    };

    Object.defineProperty(window, "isSecureContext", { configurable: true, value: secure });

    const opened = [];

    window.open = (...args) => opened.push(args);

    instance.initialize();

    const page = {
        window,
        document: window.document,
        $,
        instance,
        calls,
        clipboard,
        selection,
        opened,
        el: instance.el,

        /** Requests made to one action. */
        callsTo: (action) => calls.filter((call) => call.action === action),

        tree: () => instance.tree.jstree(true),

        /** The rendered row for a node id. */
        anchor: (id) => $(page.tree().get_node(id, true)).children(".jstree-anchor")[0],

        /** Wait for a node to be drawn. */
        drawn: (id) => waitFor(() => page.tree().get_node(id, true), `node ${id} to be drawn`),

        /** Wait for every request in flight to finish. */
        idle: () => waitFor(() => instance.tree.attr("aria-busy") === "false", "the tree to be idle"),

        /** Ids of the nodes currently in the DOM, in order. */
        nodes: () => Array.from(page.el.find(".jstree-node").map((_, li) => li.id)),

        /** A native right click, which is what the context menu plugin listens for. */
        rightClick: (id) => {
            const anchor = page.anchor(id);
            const event = new window.MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 5, clientY: 5 });

            anchor.dispatchEvent(event);
        },

        click: (id) => page.anchor(id).click(),

        /** Items of the open context menu, by label. */
        menu: () => Array.from($(".vakata-context > li > a").map((_, a) => $(a).text().trim())),

        destroy: () => {
            instance.teardown();
            window.close();
        },
    };

    if (wait) {
        await page.idle();
    }

    return page;
}

module.exports = { mount, node, fullResponse, lazyResponse, waitFor, sleep };
