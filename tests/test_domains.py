"""modules/domains.py — списки lists/*.txt: чтение, нормализация, разделение
доменов и IP/подсетей, дедуп. Все файловые операции — через monkeypatch
LISTS_DIR на временную папку, реальный lists/ не трогаем.
"""

import pytest

from modules import domains


@pytest.fixture
def lists_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(domains, "LISTS_DIR", tmp_path)
    return tmp_path


def write_list(lists_dir, name, text):
    (lists_dir / f"{name}.txt").write_text(text, encoding="utf-8")


# --- load_list: комментарии, пустые строки -----------------------------------


def test_load_list_strips_comments_and_blank_lines(lists_dir):
    write_list(lists_dir, "svc", "# заголовок\nexample.com\n\n  \nfoo.example # инлайн-коммент\n")
    assert domains.load_list("svc") == ["example.com", "foo.example"]


def test_load_list_missing_raises(lists_dir):
    with pytest.raises(FileNotFoundError):
        domains.load_list("nope")


def test_load_list_inline_comment_stripped_and_whitespace_trimmed(lists_dir):
    write_list(lists_dir, "svc", "example.com   # почему бы и нет\n")
    assert domains.load_list("svc") == ["example.com"]


# --- load_lists: объединение без дублей, порядок ------------------------------


def test_load_lists_merges_without_duplicates_preserving_order(lists_dir):
    write_list(lists_dir, "a", "one.com\ntwo.com\n")
    write_list(lists_dir, "b", "two.com\nthree.com\n")
    assert domains.load_lists(["a", "b"]) == ["one.com", "two.com", "three.com"]


# --- available_lists / list_info ----------------------------------------------


def test_available_lists_sorted(lists_dir):
    write_list(lists_dir, "zeta", "a.com\n")
    write_list(lists_dir, "alpha", "b.com\n")
    assert domains.available_lists() == ["alpha", "zeta"]


def test_list_info_counts(lists_dir):
    write_list(lists_dir, "svc", "a.com\nb.com\n# comment\n")
    info = domains.list_info()
    assert info == [{"name": "svc", "count": 2}]


# --- CRUD: create/save/delete/rename ------------------------------------------


def test_create_list_writes_header_comment(lists_dir):
    res = domains.create_list("new")
    assert res == {"name": "new", "count": 0}
    assert (lists_dir / "new.txt").read_text(encoding="utf-8") == "# new\n"


def test_create_list_existing_raises(lists_dir):
    write_list(lists_dir, "svc", "a.com\n")
    with pytest.raises(ValueError):
        domains.create_list("svc")


def test_save_raw_normalizes_crlf_and_trailing_newline(lists_dir):
    write_list(lists_dir, "svc", "old\n")
    res = domains.save_raw("svc", "a.com\r\nb.com\r\n\r\n")
    assert (lists_dir / "svc.txt").read_text(encoding="utf-8") == "a.com\nb.com\n"
    assert res == {"name": "svc", "count": 2}


def test_delete_list(lists_dir):
    write_list(lists_dir, "svc", "a.com\n")
    domains.delete_list("svc")
    assert not (lists_dir / "svc.txt").exists()


def test_delete_list_missing_is_noop(lists_dir):
    domains.delete_list("nope")  # не должно бросать


def test_rename_list(lists_dir):
    write_list(lists_dir, "old", "a.com\n")
    res = domains.rename_list("old", "new")
    assert res == {"name": "new", "count": 1}
    assert not (lists_dir / "old.txt").exists()
    assert (lists_dir / "new.txt").exists()


def test_rename_list_missing_source_raises(lists_dir):
    with pytest.raises(FileNotFoundError):
        domains.rename_list("nope", "new")


def test_rename_list_target_exists_raises(lists_dir):
    write_list(lists_dir, "a", "x.com\n")
    write_list(lists_dir, "b", "y.com\n")
    with pytest.raises(ValueError):
        domains.rename_list("a", "b")


def test_rename_list_same_name_is_allowed(lists_dir):
    write_list(lists_dir, "a", "x.com\n")
    res = domains.rename_list("a", "a")
    assert res == {"name": "a", "count": 1}


# --- имя списка: только безопасные символы ------------------------------------


@pytest.mark.parametrize("bad_name", ["../evil", "a/b", "a\\b", "", "  ", "a b"])
def test_unsafe_name_rejected(lists_dir, bad_name):
    with pytest.raises(ValueError):
        domains.create_list(bad_name)


def test_safe_name_with_dot_dash_underscore(lists_dir):
    domains.create_list("my-list_v2.final")
    assert (lists_dir / "my-list_v2.final.txt").exists()


# --- as_network ----------------------------------------------------------------


def test_as_network_bare_ipv4_becomes_slash32():
    net = domains.as_network("1.2.3.4")
    assert str(net) == "1.2.3.4/32"


def test_as_network_cidr_normalized():
    net = domains.as_network("10.0.0.5/24")
    assert str(net) == "10.0.0.0/24"


def test_as_network_ipv6():
    net = domains.as_network("2001:db8::1")
    assert str(net) == "2001:db8::1/128"


def test_as_network_domain_is_none():
    assert domains.as_network("example.com") is None


def test_as_network_numeric_looking_domain_is_none():
    """'123.example.com' не должен приниматься ipaddress как IP."""
    assert domains.as_network("123.example.com") is None


# --- split_entries / split_lists -----------------------------------------------


def test_split_entries_separates_domains_and_nets():
    dom, nets = domains.split_entries(["Example.COM", "1.2.3.4", "10.0.0.0/24", ".foo.com"])
    assert dom == ["example.com", "foo.com"]
    assert nets == ["1.2.3.4/32", "10.0.0.0/24"]


def test_split_entries_dedup_within_each_half():
    dom, nets = domains.split_entries(["a.com", "A.COM", "1.1.1.1", "1.1.1.1/32"])
    assert dom == ["a.com"]
    assert nets == ["1.1.1.1/32"]


def test_split_entries_ignores_blank_lines():
    dom, nets = domains.split_entries(["", "  ", "a.com"])
    assert dom == ["a.com"]
    assert nets == []


def test_split_entries_strips_leading_dot_from_domain():
    dom, _ = domains.split_entries([".example.com"])
    assert dom == ["example.com"]


def test_split_lists_over_multiple_files(lists_dir):
    write_list(lists_dir, "a", "example.com\n1.2.3.4\n")
    write_list(lists_dir, "b", "example.com\n10.0.0.0/8\n")
    dom, nets = domains.split_lists(["a", "b"])
    assert dom == ["example.com"]
    assert nets == ["1.2.3.4/32", "10.0.0.0/8"]


# --- validate_list -----------------------------------------------------------------

def problems(res, key="errors"):
    return [(p["line"], p["problem"]) for p in res[key]]


def test_validate_clean_list_counts_domains_and_networks(lists_dir):
    write_list(lists_dir, "svc", "# svc\nexample.com\nsub.example.org # коммент\n\n1.2.3.4\n10.0.0.0/8\n")

    res = domains.validate_list("svc")

    assert res["ok"] is True and res["errors"] == [] and res["warnings"] == []
    assert (res["entries"], res["domains"], res["networks"]) == (4, 2, 2)


def test_validate_reports_bad_entries_with_line_numbers(lists_dir):
    write_list(lists_dir, "svc", "good.com\nhttps://bad.com/path\n*.wild.com\nhas space.com\n"
               "300.1.1.1\n10.0.0.0/33\nbad..dots.com\n-lead.com\n")

    res = domains.validate_list("svc")

    assert res["ok"] is False
    assert [e["line"] for e in res["errors"]] == [2, 3, 4, 5, 6, 7, 8]
    assert all(e["problem"] for e in res["errors"])
    assert "URL" in res["errors"][0]["problem"]
    assert "*" in res["errors"][1]["problem"]
    assert "IP" in res["errors"][4]["problem"]


def test_validate_accepts_idn_and_underscore(lists_dir):
    write_list(lists_dir, "svc", "пример.рф\n_dmarc.example.com\nxn--e1afmkfd.xn--p1ai\n")

    assert domains.validate_list("svc")["ok"] is True


def test_validate_duplicates_are_warnings_after_normalisation(lists_dir):
    write_list(lists_dir, "svc", "Example.com\nexample.com\n.example.com\n1.2.3.4\n1.2.3.4/32\nother.com\n")

    res = domains.validate_list("svc")

    assert res["ok"] is True
    assert [w["line"] for w in res["warnings"]] == [2, 3, 5]
    assert "строке 1" in res["warnings"][0]["problem"]


def test_validate_flags_non_utf8_file(lists_dir):
    (lists_dir / "svc.txt").write_bytes("привет.рф\n".encode("cp1251"))

    res = domains.validate_list("svc")

    assert res["ok"] is False
    assert "UTF-8" in res["errors"][0]["problem"]


def test_validate_flags_bom(lists_dir):
    (lists_dir / "svc.txt").write_bytes(b"\xef\xbb\xbfexample.com\n")

    res = domains.validate_list("svc")

    assert res["ok"] is False and "BOM" in res["errors"][0]["problem"]


def test_validate_accepts_crlf(lists_dir):
    (lists_dir / "svc.txt").write_bytes(b"a.com\r\nb.com\r\n")

    assert domains.validate_list("svc")["entries"] == 2


def test_validate_bad_name_and_missing_file_raise(lists_dir):
    with pytest.raises(ValueError):
        domains.validate_list("../etc")
    with pytest.raises(FileNotFoundError):
        domains.validate_list("nope")
