"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");

const { mount, node, fullResponse, lazyResponse, waitFor, sleep } = require("./harness");

const visible = (page, selector) => !page.el.find(selector).prop("hidden");

test("a small archive is shown whole, with its size and date on every row", async (t) => {
    const page = await mount({
        api: {
            get_archive_structure: () =>
                fullResponse(node("docs", { folder: true }), node("docs/a.txt", { size: "2 KB", modified: "2026-02-03" })),
        },
    });
    t.after(page.destroy);

    assert.deepEqual(page.nodes(), ["docs", "docs/a.txt"]);
    assert.equal(page.el.find(".unfold-tree-meta").text(), "2 entries");
    assert.ok(visible(page, ".unfold-panel"));
    assert.equal(page.el.find(".unf-search-input").prop("disabled"), false);
    assert.equal(page.el.find(".unf-expand-all").prop("disabled"), false);

    const row = page.anchor("docs/a.txt");
    assert.equal(row.querySelector(".unfold-node-size").textContent, "2 KB");
    assert.equal(row.querySelector(".unfold-node-modified-at").textContent, "2026-02-03");
    assert.equal(page.callsTo("get_archive_structure")[0].data.view_id, "view-1");
});

test("entry names are text, never markup", async (t) => {
    const name = '<img src=x onerror="window.pwned=1">';
    const page = await mount({
        api: { get_archive_structure: () => fullResponse(node(name, { size: "<b>1</b>" })) },
    });
    t.after(page.destroy);

    assert.equal(page.el.find(".unf-tree img, .unf-tree b").length, 0);
    assert.equal(page.anchor(name).textContent.includes(name), true);
    assert.equal(page.window.pwned, undefined);
    assert.equal(page.anchor(name).querySelector(".unfold-node-size").textContent, "<b>1</b>");
});

test("a large archive loads a folder when it is opened", async (t) => {
    const page = await mount({
        api: {
            get_archive_structure: (data) =>
                data.parent === "#"
                    ? lazyResponse([node("docs", { folder: true, lazy: true })], { total: 5000 })
                    : lazyResponse([node("docs/a.txt", { lazy: true })]),
        },
    });
    t.after(page.destroy);

    assert.equal(page.el.find(".unfold-tree-meta").text(), "5,000 entries, folders load when opened");
    assert.equal(page.el.find(".unf-expand-all").prop("disabled"), true, "open_all would request every folder");
    assert.equal(page.el.find(".unf-expand-all").attr("title"), "Not available for large archives");
    assert.deepEqual(page.nodes(), ["docs"]);

    page.click("docs");
    await waitFor(() => page.tree().get_node("docs/a.txt", true), "the folder's children");

    assert.deepEqual(page.callsTo("get_archive_structure").map((c) => c.data.parent), ["#", "docs"]);
    assert.equal(page.callsTo("get_archive_structure")[1].data.limit, 500);
});

test("Show more asks for another page of the same folder", async (t) => {
    const page = await mount({
        options: { pageSize: 2 },
        api: {
            get_archive_structure: (data) => {
                const names = ["a", "b", "c", "d", "e"].slice(0, data.limit);

                return lazyResponse(names.map((n) => node(n, { lazy: true })), { childrenTotal: 5 });
            },
        },
    });
    t.after(page.destroy);

    assert.equal(page.tree().get_text("#::unfold-more"), "Show more (2 of 5 shown)");

    page.click("#::unfold-more");
    await waitFor(() => page.tree().get_node("d", true), "the second page");

    assert.deepEqual(page.callsTo("get_archive_structure").map((c) => c.data.limit), [2, 4]);
    assert.equal(page.tree().get_text("#::unfold-more"), "Show more (4 of 5 shown)");
});

test("a failed folder request keeps the tree and offers Retry", async (t) => {
    let fail = true;
    const page = await mount({
        api: {
            get_archive_structure: (data) => {
                if (data.parent === "#") {
                    return lazyResponse([node("docs", { folder: true, lazy: true })]);
                }

                return fail ? { fail: 502 } : lazyResponse([node("docs/a.txt", { lazy: true })]);
            },
        },
    });
    t.after(page.destroy);

    page.click("docs");
    await waitFor(() => visible(page, ".unf-tree-error"), "the error");

    assert.equal(page.el.find(".unfold-error-message").text(), "Could not load folder docs (HTTP 502)");
    assert.ok(visible(page, ".unf-tree-retry"));
    assert.ok(visible(page, ".unfold-panel"), "the rest of the tree is still valid");
    assert.equal(page.tree().is_open("docs"), false);

    fail = false;
    page.el.find(".unf-tree-retry").click();
    await waitFor(() => page.tree().get_node("docs/a.txt", true), "the retried folder");

    assert.ok(!visible(page, ".unf-tree-error"));
    assert.equal(page.tree().is_open("docs"), true);
});

test("an unreadable archive takes the panel down; only a failed download can be retried", async (t) => {
    const cases = [
        ["fetch_failed", true],
        ["wrong_password", false],
        ["too_large", false],
        ["unsupported_format", false],
    ];

    for (const [code, retryable] of cases) {
        const page = await mount({
            api: { get_archive_structure: () => ({ error: { code, message: `it broke: ${code}` } }) },
        });

        assert.equal(page.el.find(".unfold-error-message").text(), `it broke: ${code}`);
        assert.ok(visible(page, ".unf-tree-error"), code);
        assert.equal(visible(page, ".unf-tree-retry"), retryable, `Retry for ${code}`);
        assert.ok(!visible(page, ".unfold-panel"), "the header and tree go together");
        assert.equal(page.el.find(".unf-search-input").prop("disabled"), true);
        assert.equal(page.el.find(".unfold-tree-meta").text(), "");

        page.destroy();
    }
});

test("Retry repeats the failed root request and clears the error", async (t) => {
    let calls = 0;
    const page = await mount({
        api: {
            get_archive_structure: () =>
                ++calls === 1
                    ? { error: { code: "fetch_failed", message: "could not download" } }
                    : fullResponse(node("a.txt")),
        },
    });
    t.after(page.destroy);

    assert.ok(visible(page, ".unf-tree-retry"));

    page.el.find(".unf-tree-retry").click();
    await waitFor(() => page.tree().get_node("a.txt", true), "the archive");

    assert.equal(calls, 2);
    assert.ok(!visible(page, ".unf-tree-error"));
    assert.ok(visible(page, ".unfold-panel"));
    assert.equal(page.el.find(".unfold-tree-meta").text(), "1 entries");
});

test("an editor can rebuild an archive whose read failed", async (t) => {
    let reads = 0;
    const page = await mount({
        options: { canRebuild: true },
        api: {
            get_archive_structure: () =>
                ++reads === 1
                    ? { error: { code: "unreadable", message: "Could not read the archive" } }
                    : fullResponse(node("a.txt")),
            rebuild_archive_index: () => ({ status: "missing" }),
        },
    });
    t.after(page.destroy);

    assert.ok(visible(page, ".unf-tree-rebuild"));
    assert.ok(!visible(page, ".unf-tree-retry"));

    page.el.find(".unf-tree-rebuild").click();
    await waitFor(() => page.tree().get_node("a.txt", true), "the archive");

    const [rebuild] = page.callsTo("rebuild_archive_index");
    assert.deepEqual(JSON.parse(rebuild.data), { id: "res-1", view_id: "view-1" });
    assert.equal(reads, 2);
    assert.ok(!visible(page, ".unf-tree-error"));
    assert.ok(!visible(page, ".unf-tree-rebuild"));
    assert.ok(visible(page, ".unfold-panel"));
});

test("Rebuild is only offered to editors, and not for a failed download", async (t) => {
    const cases = [
        [{ canRebuild: false }, "unreadable", false],
        [{ canRebuild: true }, "fetch_failed", false],
        [{ canRebuild: true }, "too_large", true],
    ];

    for (const [options, code, offered] of cases) {
        const page = await mount({
            options,
            api: { get_archive_structure: () => ({ error: { code, message: "it broke" } }) },
        });

        assert.equal(visible(page, ".unf-tree-rebuild"), offered, `Rebuild for ${code}, ${JSON.stringify(options)}`);

        page.destroy();
    }
});

test("a failed rebuild request is reported and can be tried again", async (t) => {
    const page = await mount({
        options: { canRebuild: true },
        api: {
            get_archive_structure: () => ({ error: { code: "unreadable", message: "Could not read the archive" } }),
            rebuild_archive_index: () => ({ fail: 403 }),
        },
    });
    t.after(page.destroy);

    page.el.find(".unf-tree-rebuild").click();
    await waitFor(
        () => page.el.find(".unfold-error-message").text() === "Could not rebuild the archive listing (HTTP 403)",
        "the error"
    );

    assert.ok(visible(page, ".unf-tree-rebuild"));
    assert.equal(page.el.find(".unf-tree-rebuild").prop("disabled"), false);
});

test("an HTTP error on the root names the status and offers Retry", async (t) => {
    const page = await mount({ api: { get_archive_structure: () => ({ fail: 500 }) } });
    t.after(page.destroy);

    assert.equal(page.el.find(".unfold-error-message").text(), "Could not load the archive listing (HTTP 500)");
    assert.ok(visible(page, ".unf-tree-retry"));
    assert.ok(!visible(page, ".unfold-panel"));
});

test("a response the module cannot use is reported, not left loading", async (t) => {
    const page = await mount({
        // `total` is missing, so `.toLocaleString()` throws while applying the mode
        api: { get_archive_structure: () => ({ mode: "full", nodes: [node("a.txt")], has_more: false }) },
    });
    t.after(page.destroy);

    assert.ok(visible(page, ".unf-tree-error"));
    assert.match(page.el.find(".unfold-error-message").text(), /TypeError/);
    assert.equal(page.el.find(".jstree-loading").length, 0);
});

test("while a background job reads the archive the widget polls, then loads it", async (t) => {
    let ready = false;
    let statusChecks = 0;
    const page = await mount({
        wait: false,
        api: {
            get_archive_structure: () => (ready ? fullResponse(node("a.txt")) : { status: "processing" }),
            get_archive_status: () => {
                statusChecks += 1;
                ready = statusChecks >= 3;

                return { status: ready ? "ready" : "processing" };
            },
        },
    });
    t.after(page.destroy);

    await waitFor(() => visible(page, ".unf-tree-processing"), "the processing notice");
    assert.ok(!visible(page, ".unfold-panel"), "nothing to show yet");
    assert.equal(page.el.find(".unf-search-input").prop("disabled"), true);

    await waitFor(() => page.tree().get_node("a.txt", true), "the archive");

    assert.equal(statusChecks, 3);
    assert.ok(!visible(page, ".unf-tree-processing"));
    assert.ok(visible(page, ".unfold-panel"));
    assert.equal(page.callsTo("get_archive_status")[0].data.id, "res-1");
});

test("a failed background job shows its error", async (t) => {
    const page = await mount({
        wait: false,
        api: {
            get_archive_structure: () => ({ status: "processing" }),
            get_archive_status: () => ({
                status: "failed",
                error: { code: "wrong_password", message: "The password is wrong" },
            }),
        },
    });
    t.after(page.destroy);

    await waitFor(() => visible(page, ".unf-tree-error"), "the error");

    assert.equal(page.el.find(".unfold-error-message").text(), "The password is wrong");
    assert.ok(!visible(page, ".unf-tree-retry"));
    assert.ok(!visible(page, ".unf-tree-processing"));
});

test("the wait is given up after waitTimeout", async (t) => {
    const page = await mount({
        wait: false,
        options: { waitTimeout: 60 },
        api: {
            get_archive_structure: () => ({ status: "processing" }),
            get_archive_status: () => ({ status: "processing" }),
        },
    });
    t.after(page.destroy);

    await waitFor(() => visible(page, ".unf-tree-error"), "the timeout");

    assert.match(page.el.find(".unfold-error-message").text(), /still being processed/);
    assert.ok(visible(page, ".unf-tree-retry"));
    assert.ok(!visible(page, ".unf-tree-processing"));
});

test("a job whose record expired is asked for again", async (t) => {
    let started = 0;
    const page = await mount({
        wait: false,
        api: {
            get_archive_structure: () => (++started === 1 ? { status: "processing" } : fullResponse(node("a.txt"))),
            get_archive_status: () => ({ status: "missing" }),
        },
    });
    t.after(page.destroy);

    await waitFor(() => page.tree().get_node("a.txt", true), "the archive");
    assert.equal(started, 2);
});

test("tearing down stops the polling", async (t) => {
    const page = await mount({
        wait: false,
        api: {
            get_archive_structure: () => ({ status: "processing" }),
            get_archive_status: () => ({ status: "processing" }),
        },
    });

    await waitFor(() => page.callsTo("get_archive_status").length >= 1, "the first status check");
    page.instance.teardown();

    const seen = page.callsTo("get_archive_status").length;
    await sleep(100);

    assert.equal(page.callsTo("get_archive_status").length, seen);
    page.window.close();
});
