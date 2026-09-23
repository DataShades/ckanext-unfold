"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");

const { mount, node, fullResponse, lazyResponse, waitFor, sleep } = require("./harness");

const visible = (page, selector) => !page.el.find(selector).prop("hidden");

/** Type into the search box the way a user does. */
function type(page, text) {
    page.el.find(".unf-search-input").val(text).trigger("input");
}

const row = (id, extra = {}) => ({
    id,
    text: id.split("/").pop(),
    icon: "fa fa-file",
    is_dir: false,
    size: "1 KB",
    modified_at: "2026-01-01",
    ...extra,
});

const archive = () =>
    fullResponse(
        node("docs", { folder: true }),
        node("docs/readme.txt"),
        node("docs/notes.md"),
        node("Top.txt"),
    );

const matching = (page) => Array.from(page.el.find(".jstree-search")).map((a) => a.closest(".jstree-node").id);

test("a small archive is searched in the tree, by path and ignoring case", async (t) => {
    const page = await mount({ api: { get_archive_structure: archive } });
    t.after(page.destroy);

    type(page, "TOP");
    await waitFor(() => matching(page).length, "the match");

    assert.deepEqual(matching(page), ["Top.txt"]);
    assert.equal(page.callsTo("search_archive_structure").length, 0, "no request in full mode");
    assert.ok(!visible(page, ".unfold-search-results"));

    // the whole path is searched, so a folder's name finds what is inside it
    type(page, "docs/");
    await waitFor(() => matching(page).length === 2, "matches on the parent path");
    assert.deepEqual(matching(page).sort(), ["docs/notes.md", "docs/readme.txt"]);
});

test("typing is debounced into one search", async (t) => {
    const page = await mount({ options: { searchDebounce: 40 }, api: { get_archive_structure: archive } });
    t.after(page.destroy);

    let searches = 0;
    const search = page.tree().search;

    page.tree().search = function (...args) {
        searches += 1;
        return search.apply(this, args);
    };

    for (const text of ["r", "re", "rea", "read"]) {
        type(page, text);
    }

    await sleep(120);
    assert.equal(searches, 1);
    assert.deepEqual(matching(page), ["docs/readme.txt"]);
});

test("clearing the search restores the tree and hides the clear button", async (t) => {
    const page = await mount({ api: { get_archive_structure: archive } });
    t.after(page.destroy);

    assert.ok(!visible(page, ".jstree-search-clear"), "no clear button on an empty box");

    type(page, "top");
    assert.ok(visible(page, ".jstree-search-clear"));
    await waitFor(() => matching(page).length, "the match");

    page.el.find(".jstree-search-clear").click();

    assert.equal(page.el.find(".unf-search-input").val(), "");
    assert.ok(!visible(page, ".jstree-search-clear"));
    assert.equal(matching(page).length, 0);
    assert.equal(page.el.find(".unfold-tree-meta").text(), "4 entries");
});

test("a large archive is searched on the server and the matches are listed flat", async (t) => {
    const page = await mount({
        options: { searchLimit: 50 },
        api: {
            get_archive_structure: () => lazyResponse([node("docs", { folder: true, lazy: true })], { total: 9000 }),
            search_archive_structure: () => ({
                ids: ["docs"],
                matches: 1234,
                truncated: true,
                results: [row("docs/deep/readme.txt", { size: "3 KB", modified_at: "2026-05-06" })],
            }),
        },
    });
    t.after(page.destroy);

    type(page, "readme");
    await waitFor(() => page.el.find(".unfold-result").length, "the results");

    const [call] = page.callsTo("search_archive_structure");
    assert.equal(call.data.q, "readme");
    assert.equal(call.data.limit, 50);
    assert.equal(call.data.view_id, "view-1");

    assert.equal(page.el.find(".unfold-result-path").text(), "docs/deep/readme.txt");
    assert.equal(page.el.find(".unfold-search-results .unfold-node-size").text(), "3 KB");
    assert.equal(page.el.find(".unfold-search-results .unfold-node-modified-at").text(), "2026-05-06");
    assert.equal(page.el.find(".unfold-tree-meta").text(), "1,234 matches (showing the first 50)");
    assert.ok(visible(page, ".unfold-search-results"));
    assert.ok(page.el.find(".unf-tree").prop("hidden"), "the tree gives way to the list");
});

test("search results are text, never markup", async (t) => {
    const evil = '<img src=x onerror="window.pwned=1">';
    const page = await mount({
        api: {
            get_archive_structure: () => lazyResponse([node("docs", { folder: true, lazy: true })]),
            search_archive_structure: () => ({
                ids: [],
                matches: 1,
                truncated: false,
                results: [row(evil, { size: "<b>big</b>", modified_at: "<i>now</i>" })],
            }),
        },
    });
    t.after(page.destroy);

    type(page, "img");
    await waitFor(() => page.el.find(".unfold-result").length, "the results");

    assert.equal(page.el.find(".unfold-search-results img, .unfold-search-results b, .unfold-search-results i:not(.unfold-result-icon)").length, 0);
    assert.equal(page.el.find(".unfold-result-path").text(), evil);
    assert.equal(page.el.find(".unfold-search-results .unfold-node-size").text(), "<b>big</b>");
    assert.equal(page.window.pwned, undefined);
});

test("no matches says so", async (t) => {
    const page = await mount({
        api: {
            get_archive_structure: () => lazyResponse([node("docs", { folder: true, lazy: true })]),
            search_archive_structure: () => ({ ids: [], matches: 0, truncated: false, results: [] }),
        },
    });
    t.after(page.destroy);

    type(page, "zzz");
    await waitFor(() => page.el.find(".unfold-result--empty").length, "the empty notice");

    assert.equal(page.el.find(".unfold-result--empty").text(), "No entries match");
    assert.equal(page.el.find(".unfold-tree-meta").text(), "0 matches");
});

test("clearing a large-archive search brings the tree and its summary back", async (t) => {
    const page = await mount({
        api: {
            get_archive_structure: () => lazyResponse([node("docs", { folder: true, lazy: true })], { total: 9000 }),
            search_archive_structure: () => ({ ids: [], matches: 1, truncated: false, results: [row("docs/a.txt")] }),
        },
    });
    t.after(page.destroy);

    type(page, "a");
    await waitFor(() => page.el.find(".unfold-result").length, "the results");

    page.el.find(".jstree-search-clear").click();

    assert.ok(!page.el.find(".unf-tree").prop("hidden"));
    assert.ok(visible(page, ".unfold-search-results") === false);
    assert.equal(page.el.find(".unfold-search-results").children().length, 0);
    assert.equal(page.el.find(".unfold-tree-meta").text(), "9,000 entries, folders load when opened");
});

test("a failed search leaves what was on screen and offers Retry", async (t) => {
    let fail = true;
    const page = await mount({
        api: {
            get_archive_structure: () => lazyResponse([node("docs", { folder: true, lazy: true })]),
            search_archive_structure: () =>
                fail ? { fail: 503 } : { ids: [], matches: 1, truncated: false, results: [row("docs/a.txt")] },
        },
    });
    t.after(page.destroy);

    type(page, "a");
    await waitFor(() => visible(page, ".unf-tree-error"), "the error");

    assert.equal(page.el.find(".unfold-error-message").text(), "Search failed (HTTP 503)");
    assert.ok(visible(page, ".unfold-panel"));
    assert.ok(!page.el.find(".unf-tree").prop("hidden"));

    fail = false;
    page.el.find(".unf-tree-retry").click();
    await waitFor(() => page.el.find(".unfold-result").length, "the retried search");

    assert.ok(!visible(page, ".unf-tree-error"));
});

test("an error from the search action can only be retried when the download failed", async (t) => {
    const page = await mount({
        api: {
            get_archive_structure: () => lazyResponse([node("docs", { folder: true, lazy: true })]),
            search_archive_structure: () => ({ error: { code: "too_large", message: "Too large" } }),
        },
    });
    t.after(page.destroy);

    type(page, "a");
    await waitFor(() => visible(page, ".unf-tree-error"), "the error");

    assert.equal(page.el.find(".unfold-error-message").text(), "Too large");
    assert.ok(!visible(page, ".unf-tree-retry"));
});

test("a search that finds the index expired waits for the job, then searches again", async (t) => {
    let searches = 0;
    const page = await mount({
        api: {
            get_archive_structure: () => lazyResponse([node("docs", { folder: true, lazy: true })]),
            get_archive_status: () => ({ status: "ready" }),
            search_archive_structure: () =>
                ++searches === 1
                    ? { status: "processing" }
                    : { ids: [], matches: 1, truncated: false, results: [row("docs/a.txt")] },
        },
    });
    t.after(page.destroy);

    type(page, "a");
    await waitFor(() => page.el.find(".unfold-result").length, "the results");

    assert.equal(searches, 2);
    assert.ok(!visible(page, ".unf-tree-processing"));
    assert.ok(visible(page, ".unfold-panel"), "a search must not take the tree down");
});

test("an empty query is a clear, not a search", async (t) => {
    const page = await mount({
        api: {
            get_archive_structure: () => lazyResponse([node("docs", { folder: true, lazy: true })]),
            search_archive_structure: () => ({ ids: [], matches: 0, truncated: false, results: [] }),
        },
    });
    t.after(page.destroy);

    type(page, "   ");
    await sleep(40);

    assert.equal(page.callsTo("search_archive_structure").length, 0);
});
