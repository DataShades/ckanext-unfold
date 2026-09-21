"""Tests for the folder index. No CKAN runtime needed."""

from dataclasses import asdict, replace

from ckanext.unfold import index
from ckanext.unfold.types import Node


def _node(path: str, folder: bool = False) -> Node:
    parts = [p for p in path.split("/") if p]

    return Node(
        id=path,
        text=parts[-1],
        icon=index.FOLDER_ICON if folder else "fa fa-file",
        parent="/".join(parts[:-1]) or index.ROOT,
        data={"size": "" if folder else "1.0 KB", "modified_at": ""},
    )


def test_groups_children_by_parent_and_flags_folders():
    nodes = [_node("a", True), _node("a/x.txt"), _node("a/y.txt"), _node("z.txt")]
    idx = index.ArchiveIndex.from_nodes(nodes)

    assert idx.total == 4
    assert [n.id for n in idx.children_of(index.ROOT)] == ["a", "z.txt"]
    assert [n.id for n in idx.children_of("a")] == ["a/x.txt", "a/y.txt"]
    assert idx.children_of("missing") == []

    by_id = {n.id: n for n in idx.all_nodes()}
    assert by_id["a"].children is True
    assert by_id["z.txt"].children is False


def test_creates_missing_ancestor_folders():
    """tar/7z/rar may list files without directory entries."""
    idx = index.ArchiveIndex.from_nodes([_node("a/b/c.txt"), _node("a/d.txt")])

    ids = {n.id for n in idx.all_nodes()}
    assert ids == {"a", "a/b", "a/b/c.txt", "a/d.txt"}
    assert idx.total == 4

    by_id = {n.id: n for n in idx.all_nodes()}
    assert by_id["a"].parent == index.ROOT
    assert by_id["a/b"].parent == "a"
    assert by_id["a/b"].icon == index.FOLDER_ICON
    assert by_id["a/b"].children is True


def test_sorts_folders_first_then_case_insensitive():
    nodes = [_node("b.txt"), _node("A.txt"), _node("zdir", True), _node("zdir/f")]
    idx = index.ArchiveIndex.from_nodes(nodes)

    assert [n.id for n in idx.children_of(index.ROOT)] == ["zdir", "A.txt", "b.txt"]


def test_drops_duplicate_ids_first_wins():
    first = _node("dup.txt")
    idx = index.ArchiveIndex.from_nodes([first, _node("dup.txt")])

    assert idx.total == 1
    assert idx.all_nodes()[0] is first


def test_search_returns_ancestors_of_matches_in_order():
    idx = index.ArchiveIndex.from_nodes(
        [_node("assets/img/logo.PNG"), _node("assets/css/site.css"), _node("readme.md")]
    )

    result = idx.search("png")

    assert result.ids == ["assets", "assets/img"]
    assert result.matches == 1
    assert result.truncated is False
    assert [n.id for n in result.results] == ["assets/img/logo.PNG"]


def test_search_is_truncated_at_limit():
    nodes = [_node(f"d{i}/file{i}.log") for i in range(10)]
    idx = index.ArchiveIndex.from_nodes(nodes)

    result = idx.search(".log", limit=3)

    assert result.matches == 10
    assert result.truncated is True
    assert result.ids == ["d0", "d1", "d2"]


def test_search_no_matches():
    idx = index.ArchiveIndex.from_nodes([_node("a/b.txt")])

    assert asdict(idx.search("zzz")) == {
        "ids": [],
        "matches": 0,
        "truncated": False,
        "results": [],
    }


def test_search_paths_returns_first_matches_and_total():
    matched, matches = index.search_paths(["a/x.txt", "b/x.txt", "c.md"], "x.txt", 1)

    assert matched == ["a/x.txt"]
    assert matches == 2


def _same(node: Node) -> tuple:
    return (
        node.id,
        node.text,
        node.icon,
        node.parent,
        node.data,
        node.li_attr,
        node.a_attr,
        node.children,
    )


def test_folder_round_trips_through_its_cached_form():
    nodes = [
        _node("d", True),
        _node("d/new\nline.txt"),
        _node('d/quo"te,\\back.txt'),
        _node("d/uni\u2028\u00e9\u4e2d.txt"),
    ]
    nodes[0].children = True
    nodes[1].a_attr = {"href": "http://x.test/f", "target": "_self"}
    nodes[2].li_attr = {"class": "c"}
    nodes[3].text = "A name that is not the file name"

    raw = index.encode_folder(nodes)
    restored = index.decode_folder(raw, index.ROOT)

    # the parent is not stored: it is whatever folder the caller read it from
    assert [_same(n) for n in restored] == [
        _same(replace(n, parent=index.ROOT)) for n in nodes
    ]
    assert index.folder_size(raw) == len(nodes)
    assert index.folder_size(raw.encode()) == len(nodes)


def test_cached_form_is_one_line_per_node_and_leaves_out_what_is_derivable():
    raw = index.encode_folder([_node("a/b.txt"), _node("a/c\nd.txt")])
    lines = raw.split("\n")

    assert len(lines) == 2  # the newline in a name is escaped, not raw
    assert lines[0] == (
        '{"id":"a/b.txt","icon":"fa fa-file","data":{"size":"1.0 KB","modified_at":""}}'
    )


def test_decode_folder_stops_after_the_limit():
    nodes = [_node(f"f{i:03d}.txt") for i in range(50)]
    raw = index.encode_folder(nodes).encode()

    first = index.decode_folder(raw, index.ROOT, 5)

    assert [n.id for n in first] == [f"f{i:03d}.txt" for i in range(5)]
    assert index.folder_size(raw) == 50
    assert len(index.decode_folder(raw, index.ROOT)) == 50
    assert index.decode_folder(b"", index.ROOT) == []
    assert index.folder_size(b"") == 0


def test_children_page_returns_a_page_and_the_folder_size():
    idx = index.ArchiveIndex.from_nodes([_node(f"f{i}.txt") for i in range(5)])

    page, total = idx.children_page(index.ROOT, 2)

    assert [n.id for n in page] == ["f0.txt", "f1.txt"]
    assert total == 5
    assert idx.children_page("missing", 2) == ([], 0)
