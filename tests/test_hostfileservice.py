import pytest

import hostfileservice as h

ORIGINAL = "127.0.0.1 localhost\n# a comment\n127.0.0.1 example.dev\n"


@pytest.fixture
def hosts(tmp_path, monkeypatch):
    """A throwaway hosts file. The real one is never touched, and ipconfig never runs."""
    path = tmp_path / "hosts"
    path.write_text(ORIGINAL)
    monkeypatch.setattr(h, "HOST_PATH", str(path))
    monkeypatch.setattr(h, "dnsflush", lambda: None)
    return path


# ---------- normalizedomain ----------

@pytest.mark.parametrize("raw, expected", [
    ("youtube.com", "youtube.com"),
    ("  YouTube.COM  ", "youtube.com"),
    ("https://youtube.com/watch?v=1", "youtube.com"),
    ("http://www.youtube.com:8080/x#top", "www.youtube.com"),
    ("https://user:pw@news.example.co.uk/a", "news.example.co.uk"),
    ("youtube.com.", "youtube.com"),
    ("xn--mnchen-3ya.de", "xn--mnchen-3ya.de"),
])
def test_normalizedomain_accepts_and_cleans(raw, expected):
    assert h.normalizedomain(raw) == expected


@pytest.mark.parametrize("raw", [
    "",
    "   ",
    "localhost",
    "127.0.0.1",
    "not a site",
    "good.com\n127.0.0.1 bank.com",  # must not be able to smuggle in a second hosts line
    "-bad.com",
    "bad-.com",
    "a_b.com",
    "a..com",
    "https://",
    "x" * 64 + ".com",
])
def test_normalizedomain_rejects(raw):
    with pytest.raises(ValueError):
        h.normalizedomain(raw)


# ---------- domainexpansion ----------

def test_domainexpansion_adds_www_twin():
    assert h.domainexpansion(["youtube.com"]) == ["youtube.com", "www.youtube.com"]
    assert h.domainexpansion(["www.youtube.com"]) == ["www.youtube.com", "youtube.com"]


def test_domainexpansion_dedupes_and_skips_blanks():
    result = h.domainexpansion(["youtube.com", "WWW.youtube.com", "", "  "])
    assert result == ["youtube.com", "www.youtube.com"]


def test_domainexpansion_rejects_invalid():
    with pytest.raises(ValueError):
        h.domainexpansion(["good.com", "bad site"])


# ---------- block ----------

def test_block_appends_tagged_entries_and_keeps_existing_lines(hosts):
    added = h.block(["youtube.com"])

    assert added == ["youtube.com", "www.youtube.com"]
    assert hosts.read_text() == (
        ORIGINAL
        + "127.0.0.1 youtube.com # XAMGUARD\n"
        + "127.0.0.1 www.youtube.com # XAMGUARD\n"
    )


def test_block_twice_adds_nothing_the_second_time(hosts):
    h.block(["youtube.com"])
    after_first = hosts.read_text()

    assert h.block(["youtube.com"]) == []
    assert hosts.read_text() == after_first


def test_block_cleans_pasted_urls(hosts):
    h.block(["https://www.Twitter.com/home?lang=en"])
    assert h.list_blocked() == ["twitter.com"]


def test_block_with_one_bad_site_writes_nothing(hosts):
    with pytest.raises(ValueError):
        h.block(["good.com", "bad site"])
    assert hosts.read_text() == ORIGINAL


def test_block_nothing_does_nothing(hosts):
    assert h.block([]) == []
    assert h.block(["", "  "]) == []
    assert hosts.read_text() == ORIGINAL


def test_block_handles_file_without_trailing_newline(hosts):
    hosts.write_text("127.0.0.1 localhost")  # no \n at the end
    h.block(["a.com"])
    assert hosts.read_text() == (
        "127.0.0.1 localhost\n"
        "127.0.0.1 a.com # XAMGUARD\n"
        "127.0.0.1 www.a.com # XAMGUARD\n"
    )


def test_block_creates_missing_hosts_file(tmp_path, monkeypatch):
    path = tmp_path / "does_not_exist_yet"
    monkeypatch.setattr(h, "HOST_PATH", str(path))
    monkeypatch.setattr(h, "dnsflush", lambda: None)

    assert h.list_blocked() == []
    h.block(["a.com"])
    assert h.list_blocked() == ["a.com"]


# ---------- list_blocked ----------

def test_list_blocked_is_sorted_deduped_and_only_shows_our_lines(hosts):
    h.block(["youtube.com", "twitter.com"])
    # example.dev is in the file but XamGuard didn't write it, so it isn't listed.
    assert h.list_blocked() == ["twitter.com", "youtube.com"]


def test_list_blocked_survives_a_restart(hosts):
    """The old bug: blocked sites lived in a Python list and were forgotten on restart."""
    h.block(["youtube.com"])
    # "restart" = nothing in memory; everything must come from the file
    assert h.list_blocked() == ["youtube.com"]


# ---------- unblock ----------

def test_unblock_removes_both_variants_and_restores_the_file(hosts):
    h.block(["youtube.com"])

    removed = h.unblock(["youtube.com"])

    assert removed == ["youtube.com", "www.youtube.com"]
    assert hosts.read_text() == ORIGINAL


def test_unblock_accepts_pasted_urls(hosts):
    h.block(["youtube.com"])
    h.unblock(["https://www.youtube.com/watch?v=1"])
    assert h.list_blocked() == []


def test_unblock_only_removes_the_requested_site(hosts):
    h.block(["a.com", "b.com"])
    h.unblock(["a.com"])
    assert h.list_blocked() == ["b.com"]


def test_unblock_never_touches_lines_xamguard_did_not_write(hosts):
    """The old bug: unblock('example.dev') deleted a hand-written, untagged line."""
    assert h.unblock(["example.dev"]) == []
    assert hosts.read_text() == ORIGINAL


def test_unblock_of_site_that_is_not_blocked_returns_empty(hosts):
    assert h.unblock(["never-blocked.com"]) == []
    assert hosts.read_text() == ORIGINAL


def test_unblock_can_remove_junk_an_older_version_wrote(hosts):
    hosts.write_text(
        ORIGINAL
        + "127.0.0.1 https://youtube.com/watch?v=1 # XAMGUARD\n"
        + "127.0.0.1 www.https://youtube.com/watch?v=1 # XAMGUARD\n"
    )

    shown = h.list_blocked()
    assert shown == ["https://youtube.com/watch?v=1"]

    # Whatever the app shows in its list, the app must be able to remove.
    h.unblock(shown)
    assert hosts.read_text() == ORIGINAL


# ---------- DNS flush ----------

def test_block_and_unblock_flush_dns(hosts, monkeypatch):
    calls = []
    monkeypatch.setattr(h, "dnsflush", lambda: calls.append("flush"))

    h.block(["a.com"])
    h.unblock(["a.com"])

    assert calls == ["flush", "flush"]


def test_dnsflush_does_not_crash():
    """Regression: used to raise TypeError (get_output= instead of capture_output=).

    This one calls the real function. On Windows that really runs `ipconfig /flushdns`
    (harmless, it just clears the DNS cache); on other systems it does nothing.
    """
    h.dnsflush()
