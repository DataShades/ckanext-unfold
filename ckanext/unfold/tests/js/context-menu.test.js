"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");

const { mount, node, fullResponse, lazyResponse, waitFor } = require("./harness");

const archive = () =>
    fullResponse(
        node("docs", { folder: true }),
        node("docs/readme.txt"),
        node("top.txt"),
    );

/** Pick an item of the open context menu by its label. */
function choose(page, label) {
    const item = page.$(".vakata-context > li > a").filter((_, a) => a.textContent.trim() === label);

    assert.equal(item.length, 1, `no "${label}" in the menu: ${page.menu()}`);
    item[0].click();
}

test("a folder can be expanded or collapsed and a file cannot", async (t) => {
    const page = await mount({ api: { get_archive_structure: archive } });
    t.after(page.destroy);

    page.rightClick("docs");
    assert.deepEqual(page.menu(), ["Collapse", "Copy path"]);

    page.rightClick("top.txt");
    assert.deepEqual(page.menu(), ["Copy path"]);
});

test("an unloaded folder of a large archive offers Expand", async (t) => {
    const page = await mount({
        api: { get_archive_structure: () => lazyResponse([node("docs", { folder: true, lazy: true })]) },
    });
    t.after(page.destroy);

    page.rightClick("docs");
    assert.deepEqual(page.menu(), ["Expand", "Copy path"]);
});

test("Copy path puts the entry's path on the clipboard and says so", async (t) => {
    const page = await mount({ api: { get_archive_structure: archive } });
    t.after(page.destroy);

    page.rightClick("docs/readme.txt");
    choose(page, "Copy path");

    await waitFor(() => page.el.find(".unfold-toast").text(), "the toast");

    assert.deepEqual(page.clipboard.written, ["docs/readme.txt"]);
    assert.equal(page.el.find(".unfold-toast").text(), "Path copied");
    assert.ok(page.el.find(".unfold-toast").hasClass("text-success"));
    assert.ok(!page.el.find(".unfold-toast").hasClass("text-danger"));
});

test("a refused clipboard write is reported instead of ignored", async (t) => {
    const page = await mount({ api: { get_archive_structure: archive } });
    t.after(page.destroy);

    page.clipboard.reject = true;
    page.rightClick("top.txt");
    choose(page, "Copy path");

    await waitFor(() => page.el.find(".unfold-toast").text(), "the toast");

    assert.equal(page.el.find(".unfold-toast").text(), "Could not copy");
    assert.ok(page.el.find(".unfold-toast").hasClass("text-danger"));
    assert.ok(!page.el.find(".unfold-toast").hasClass("text-success"));
});

test("without a secure context the copy falls back to a selected textarea", async (t) => {
    const page = await mount({ api: { get_archive_structure: archive }, secure: false });
    t.after(page.destroy);

    page.rightClick("top.txt");
    choose(page, "Copy path");

    assert.deepEqual(page.selection.copied, ["top.txt"]);
    assert.deepEqual(page.clipboard.written, [], "navigator.clipboard must not be used over plain HTTP");
    assert.equal(page.el.find(".unfold-toast").text(), "Path copied");
    assert.equal(page.document.querySelectorAll("textarea").length, 0, "the helper textarea is removed");
});

test("the fallback reports a failed copy too", async (t) => {
    const page = await mount({ api: { get_archive_structure: archive }, secure: false });
    t.after(page.destroy);

    page.selection.ok = false;
    page.rightClick("top.txt");
    choose(page, "Copy path");

    assert.equal(page.el.find(".unfold-toast").text(), "Could not copy");
    assert.ok(page.el.find(".unfold-toast").hasClass("text-danger"));
    assert.equal(page.document.querySelectorAll("textarea").length, 0);
});

test("a failing execCommand does not escape the click handler", async (t) => {
    const page = await mount({ api: { get_archive_structure: archive }, secure: false });
    t.after(page.destroy);

    page.document.execCommand = () => {
        throw new Error("not allowed");
    };
    page.rightClick("top.txt");
    choose(page, "Copy path");

    assert.equal(page.el.find(".unfold-toast").text(), "Could not copy");
});

test("entries with a link get Open URL and Copy URL", async (t) => {
    const page = await mount({
        api: {
            get_archive_structure: () =>
                fullResponse(node("linked.txt", { a_attr: { href: "https://files.test/linked.txt", target: "_blank" } })),
        },
    });
    t.after(page.destroy);

    page.rightClick("linked.txt");
    assert.deepEqual(page.menu(), ["Copy path", "Open URL", "Copy URL"]);

    choose(page, "Open URL");
    assert.deepEqual(page.opened, [["https://files.test/linked.txt", "_blank"]]);

    page.rightClick("linked.txt");
    choose(page, "Copy URL");
    await waitFor(() => page.clipboard.written.length, "the URL to be copied");

    assert.deepEqual(page.clipboard.written, ["https://files.test/linked.txt"]);
    assert.equal(page.el.find(".unfold-toast").text(), "URL copied");
});

test("right click does not toggle the folder under the pointer", async (t) => {
    const page = await mount({ api: { get_archive_structure: archive } });
    t.after(page.destroy);

    assert.equal(page.tree().is_open("docs"), true);

    page.rightClick("docs");
    assert.equal(page.tree().is_open("docs"), true, "right click closed the folder");

    page.tree().close_node("docs", null, true);
    page.rightClick("docs");
    assert.equal(page.tree().is_open("docs"), false, "right click opened the folder");
    assert.ok(page.menu().includes("Expand"));

    // control: a left click still toggles
    page.click("docs");
    assert.equal(page.tree().is_open("docs"), true);
});

test("right click on a lazy folder does not request its children", async (t) => {
    const page = await mount({
        api: {
            get_archive_structure: (data) =>
                data.parent === "#" ? lazyResponse([node("docs", { folder: true, lazy: true })]) : lazyResponse([]),
        },
    });
    t.after(page.destroy);

    page.rightClick("docs");
    await page.idle();

    assert.equal(page.callsTo("get_archive_structure").length, 1, "only the root was requested");
    assert.equal(page.tree().is_open("docs"), false);
});

test("right click on Show more neither loads more nor opens a menu", async (t) => {
    const page = await mount({
        options: { pageSize: 2 },
        api: {
            get_archive_structure: () =>
                lazyResponse([node("a.txt", { lazy: true }), node("b.txt", { lazy: true })], { childrenTotal: 5 }),
        },
    });
    t.after(page.destroy);

    const more = "#::unfold-more";
    assert.ok(page.tree().get_node(more), "no Show more row");

    page.rightClick(more);
    await page.idle();

    assert.equal(page.callsTo("get_archive_structure").length, 1, "right click loaded another page");
    assert.deepEqual(page.menu(), []);
    assert.equal(page.el.find(".vakata-context").children().length, 0);
});

test("without the context menu there is no menu and a link opens on select", async (t) => {
    const page = await mount({
        options: { showContextMenu: false },
        api: {
            get_archive_structure: () =>
                fullResponse(
                    node("linked.txt", { a_attr: { href: "https://files.test/x", target: "_blank" } }),
                    node("plain.txt"),
                ),
        },
    });
    t.after(page.destroy);

    assert.ok(!page.tree().settings.plugins.includes("contextmenu"));

    page.click("plain.txt");
    assert.deepEqual(page.opened, [], "a node without a link opened something");

    page.click("linked.txt");
    assert.deepEqual(page.opened, [["https://files.test/x", "_blank"]]);
});
