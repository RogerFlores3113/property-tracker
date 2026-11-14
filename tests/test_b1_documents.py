"""Documents: upload limits, path safety, download headers, delete. Plus the application checklist."""
import os
import re

import pytest

from prophelper import docfiles, paths


def _place(store):
    s = store.current_search() or store.add_search("S", "rent")
    store.set_current_search(s["id"])
    return store.add_place(search_id=s["id"], title="Maple")[0]


def _upload(client, pid, name="lease.pdf", data=b"%PDF-1.4 hello", kind="lease"):
    return client.post(f"/places/{pid}/documents", data={"kind": kind}, files={"file": (name, data, "application/pdf")}, follow_redirects=False)


# ---- docfiles (pure helpers)
@pytest.mark.parametrize("raw,shown", [("lease.pdf", "lease.pdf"), ("../../etc/passwd", "passwd"), ("C:\\Users\\me\\a b.pdf", "a b.pdf"),
                                       ("a\x00b\nc.txt", "abc.txt"), ("", ""), ("   ", ""), ("..", ""), ('x<y>"z.pdf', "xyz.pdf")])
def test_display_name_strips_folders_and_junk(raw, shown):
    assert docfiles.display_name(raw) == shown


def test_display_name_is_capped():
    assert len(docfiles.display_name("a" * 500 + ".pdf")) <= 200
    assert docfiles.display_name("a" * 500 + ".pdf").endswith(".pdf")


def test_stored_name_is_random_and_keeps_only_a_plain_extension():
    a, b = docfiles.stored_name("x.PDF"), docfiles.stored_name("x.PDF")
    assert a != b and a.endswith(".pdf") and docfiles.STORED_RE.fullmatch(a)
    assert docfiles.STORED_RE.fullmatch(docfiles.stored_name("noext"))
    assert "." not in docfiles.stored_name("evil.ph p/../x")  # not a plain extension: none kept
    assert "." not in docfiles.stored_name("a.toolongextension")


def test_check_upload_limits():
    assert docfiles.check_upload("a.pdf", 1) == ""
    assert docfiles.check_upload("a.pdf", docfiles.LIMIT_BYTES) == ""
    assert "too big" in docfiles.check_upload("a.pdf", docfiles.LIMIT_BYTES + 1)
    assert "empty" in docfiles.check_upload("a.pdf", 0)
    assert "Choose a file" in docfiles.check_upload("", 10)


def test_save_and_stored_path_roundtrip(store):
    place = _place(store)
    name = docfiles.save(place["id"], "My Lease.pdf", b"data")
    path = docfiles.stored_path(place["id"], name)
    assert path is not None and path.read_bytes() == b"data"
    assert path.parent == paths.files_dir() / str(place["id"])
    assert "My Lease" not in name  # the typed name never touches the disk
    with pytest.raises(ValueError):
        docfiles.save(place["id"], "big.bin", b"x" * (docfiles.LIMIT_BYTES + 1))
    assert docfiles.remove(place["id"], name) and docfiles.stored_path(place["id"], name) is None
    assert not docfiles.remove(place["id"], name)


@pytest.mark.parametrize("bad", ["../secret", "..", "a/b", "a\\b", "", ".hidden", "x" * 40, "ABCDEF" * 6, "0" * 32 + ".p/df", "0" * 32 + ".exe.exe"])
def test_stored_path_refuses_anything_that_is_not_ours(store, bad):
    place = _place(store)
    folder = paths.files_dir() / str(place["id"])
    folder.mkdir(parents=True, exist_ok=True)
    (paths.files_dir() / "secret").write_text("no")
    assert docfiles.stored_path(place["id"], bad) is None


def test_stored_path_refuses_a_symlink(store, tmp_path):
    place = _place(store)
    folder = paths.files_dir() / str(place["id"])
    folder.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    name = "a" * 32
    try:
        os.symlink(outside, folder / name)
    except OSError:
        pytest.skip("symlinks not allowed here")
    assert docfiles.stored_path(place["id"], name) is None


def test_attachment_headers_are_safe():
    h = docfiles.attachment_headers('evil"\r\nX-Injected: 1.html', 10)
    assert h["Content-Disposition"].startswith("attachment;") and "\r" not in h["Content-Disposition"] and "\n" not in h["Content-Disposition"]
    assert h["X-Content-Type-Options"] == "nosniff" and "sandbox" in h["Content-Security-Policy"]
    assert "filename*=UTF-8''" in docfiles.attachment_headers("é.pdf", 1)["Content-Disposition"]


# ---- the routes
def test_upload_list_download_delete(client, store):
    place = _place(store)
    pid = place["id"]
    assert _upload(client, pid).status_code == 303
    doc = store.list_documents(pid)[0]
    assert doc["original_name"] == "lease.pdf" and doc["kind"] == "lease" and doc["size"] == len(b"%PDF-1.4 hello")
    assert doc["stored_name"] != "lease.pdf" and docfiles.STORED_RE.fullmatch(doc["stored_name"])
    page = client.get(f"/places/{pid}").text
    assert 'id="documents"' in page and "lease.pdf" in page and f'href="/files/{doc["id"]}"' in page
    r = client.get(f"/files/{doc['id']}")
    assert r.status_code == 200 and r.content == b"%PDF-1.4 hello"
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["content-disposition"].startswith("attachment;") and 'filename="lease.pdf"' in r.headers["content-disposition"]
    assert r.headers["x-content-type-options"] == "nosniff" and "sandbox" in r.headers["content-security-policy"]
    assert "document" in [e["kind"] for e in store.list_events(pid)]
    stored = paths.files_dir() / str(pid) / doc["stored_name"]
    assert stored.is_file()
    client.post(f"/documents/{doc['id']}/delete", data={})
    assert stored.is_file() and store.list_documents(pid)  # needs the tick box
    client.post(f"/documents/{doc['id']}/delete", data={"confirm": "yes"})
    assert not stored.exists() and store.list_documents(pid) == []
    assert client.get(f"/files/{doc['id']}").status_code == 404


def test_html_upload_is_never_served_as_a_page(client, store):
    pid = _place(store)["id"]
    _upload(client, pid, name="evil.html", data=b"<script>alert(1)</script>", kind="other")
    doc = store.list_documents(pid)[0]
    r = client.get(f"/files/{doc['id']}")
    assert r.headers["content-type"] == "application/octet-stream" and "attachment" in r.headers["content-disposition"]


def test_upload_name_with_folders_is_cleaned(client, store):
    pid = _place(store)["id"]
    _upload(client, pid, name="../../../evil.pdf")
    doc = store.list_documents(pid)[0]
    assert doc["original_name"] == "evil.pdf"
    assert [p.name for p in (paths.files_dir() / str(pid)).iterdir()] == [doc["stored_name"]]
    assert not (paths.files_dir().parent / "evil.pdf").exists()


def test_upload_over_the_limit_is_refused(client, store):
    pid = _place(store)["id"]
    r = _upload(client, pid, data=b"x" * (docfiles.LIMIT_BYTES + 1))
    assert r.status_code == 303 and store.list_documents(pid) == []
    folder = paths.files_dir() / str(pid)
    assert not folder.exists() or list(folder.iterdir()) == []
    assert "too big" in client.get(f"/places/{pid}").text


def test_upload_exactly_at_the_limit_is_accepted(client, store):
    pid = _place(store)["id"]
    _upload(client, pid, data=b"x" * docfiles.LIMIT_BYTES)
    assert len(store.list_documents(pid)) == 1


def test_a_huge_declared_size_is_refused_before_reading(client, store):
    pid = _place(store)["id"]
    r = client.post(f"/places/{pid}/documents", content=b"", headers={"content-length": str(docfiles.LIMIT_BYTES * 5),
                                                                       "content-type": "multipart/form-data; boundary=x"}, follow_redirects=False)
    assert r.status_code in (303, 400) and store.list_documents(pid) == []


@pytest.mark.parametrize("name,data,kind", [("", b"x", "lease"), ("a.pdf", b"", "lease"), ("a.pdf", b"x", "banana")])
def test_upload_rejects_bad_input(client, store, name, data, kind):
    pid = _place(store)["id"]
    r = client.post(f"/places/{pid}/documents", data={"kind": kind}, files={"file": (name, data, "application/pdf")}, follow_redirects=False)
    assert r.status_code == 303 and store.list_documents(pid) == []


def test_upload_without_a_file(client, store):
    pid = _place(store)["id"]
    assert client.post(f"/places/{pid}/documents", data={"kind": "lease"}, follow_redirects=False).status_code == 303
    assert store.list_documents(pid) == []


def test_upload_to_a_missing_place_is_404(client):
    assert client.post("/places/999/documents", data={"kind": "lease"}, files={"file": ("a.pdf", b"x")}).status_code == 404


def test_download_is_blocked_from_another_site(client, store):
    pid = _place(store)["id"]
    _upload(client, pid)
    doc = store.list_documents(pid)[0]
    assert client.get(f"/files/{doc['id']}", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.get(f"/files/{doc['id']}", headers={"Origin": "http://evil.example"}).status_code == 403


def test_upload_from_another_site_is_blocked(store):
    from conftest import local_client

    pid = _place(store)["id"]
    evil = local_client(store, origin=False)
    r = evil.post(f"/places/{pid}/documents", data={"kind": "lease"}, files={"file": ("a.pdf", b"x")}, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403 and store.list_documents(pid) == []


def test_missing_file_on_disk_gives_a_plain_404(client, store):
    pid = _place(store)["id"]
    _upload(client, pid)
    doc = store.list_documents(pid)[0]
    (paths.files_dir() / str(pid) / doc["stored_name"]).unlink()
    r = client.get(f"/files/{doc['id']}")
    assert r.status_code == 404 and "missing" in r.text


def test_a_tampered_stored_name_cannot_escape(client, store):
    pid = _place(store)["id"]
    store._exec("INSERT INTO documents(place_id, stored_name, original_name, kind, size, created_at) VALUES (?, '..', 'x', 'other', 1, 'now')", (pid,))
    doc_id = store.list_documents(pid)[0]["id"]
    assert client.get(f"/files/{doc_id}").status_code == 404


# ---- the application checklist
def test_checklist_page_has_defaults_and_the_plain_line(client):
    r = client.get("/checklist")
    assert r.status_code == 200 and "Photo ID ready" in r.text and "0 of 8 ready" in r.text
    assert "keeps this list, not copies of your documents" in r.text


def test_checklist_add_edit_done_move_delete(client, store):
    client.post("/checklist/items", data={"label": "Letter <b>from</b> employer", "note": "HR"})
    items = store.list_checklist()
    new = items[-1]
    assert new["label"] == "Letter <b>from</b> employer" and "<b>from</b>" not in client.get("/checklist").text
    client.post(f"/checklist/items/{new['id']}", data={"label": "Employer letter", "note": "Ask HR"})
    assert store.get_checklist_item(new["id"])["label"] == "Employer letter"
    client.post(f"/checklist/items/{new['id']}/done", data={"value": "1"})
    assert store.get_checklist_item(new["id"])["done"] == 1 and "1 of 9 ready" in client.get("/checklist").text
    client.post(f"/checklist/items/{new['id']}/done", data={"value": "0"})
    assert store.get_checklist_item(new["id"])["done"] == 0
    client.post(f"/checklist/items/{new['id']}/move", data={"direction": "up"})
    assert [i["id"] for i in store.list_checklist()].index(new["id"]) == len(items) - 2
    client.post(f"/checklist/items/{new['id']}/move", data={"direction": "down"})
    assert store.list_checklist()[-1]["id"] == new["id"]
    client.post(f"/checklist/items/{new['id']}/delete")
    assert new["id"] not in [i["id"] for i in store.list_checklist()]


def test_checklist_rejects_empty_and_missing(client, store):
    before = len(store.list_checklist())
    assert client.post("/checklist/items", data={"label": "  "}, follow_redirects=False).status_code == 303
    assert len(store.list_checklist()) == before
    for path in ("", "/done", "/move", "/delete"):
        assert client.post(f"/checklist/items/999{path}", data={}).status_code == 404


def test_moving_the_first_item_up_does_nothing(client, store):
    first = store.list_checklist()[0]
    client.post(f"/checklist/items/{first['id']}/move", data={"direction": "up"})
    assert store.list_checklist()[0]["id"] == first["id"]


def test_checklist_is_in_the_nav(client):
    assert 'href="/checklist"' in client.get("/today").text
