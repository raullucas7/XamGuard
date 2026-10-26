import pytest

from xamguard import hostfileservice as h

ORIGINAL = "127.0.0.1 localhost\n# a comment\n127.0.0.1 example.dev\n"


@pytest.fixture
def hosts(tmp_path, monkeypatch):
    """Fake hosts file, so the real one is never touched."""
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
    "good.com\n127.0.0.1 bank.com",  # can't sneak in a second line
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


def test_plainsites_hides_www_twins_and_keeps_order():
    entries = ["youtube.com", "www.youtube.com", "www.a.com", "b.com"]
    assert h.plainsites(entries) == ["youtube.com", "a.com", "b.com"]


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
    """Old bug: the list lived in memory and was lost on restart."""
    h.block(["youtube.com"])
    # nothing in memory, so it has to come from the file
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
    """Old bug: this deleted lines XamGuard didn't write."""
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

    # anything shown in the list has to be removable
    h.unblock(shown)
    assert hosts.read_text() == ORIGINAL


# ---------- timed blocks ----------

def test_parseentry_reads_permanent_and_timed_lines():
    assert h.parseentry("127.0.0.1 youtube.com # XAMGUARD\n") == ("youtube.com", None)
    assert h.parseentry("127.0.0.1 youtube.com # XAMGUARD until=1761500000\n") == (
        "youtube.com",
        1761500000,
    )


@pytest.mark.parametrize("line", [
    "127.0.0.1 localhost",
    "# a comment",
    "",
    "127.0.0.1 example.dev # not ours",
    "127.0.0.1 a.com # XAMGUARD until=soon",  # mangled, so not ours and never deleted
])
def test_parseentry_ignores_lines_that_are_not_ours(line):
    assert h.parseentry(line) is None


def test_block_with_until_writes_the_end_time(hosts):
    h.block(["youtube.com"], until=1_000_300.7)

    assert hosts.read_text() == (
        ORIGINAL
        + "127.0.0.1 youtube.com # XAMGUARD until=1000300\n"
        + "127.0.0.1 www.youtube.com # XAMGUARD until=1000300\n"
    )


def test_list_blocked_until_shows_end_times(hosts):
    h.block(["a.com"])
    h.block(["b.com"], until=2_000_000)

    assert h.list_blocked_until() == {"a.com": None, "b.com": 2_000_000}
    assert h.list_blocked() == ["a.com", "b.com"]


def test_list_blocked_until_merges_www_twins(hosts):
    hosts.write_text(
        ORIGINAL
        + "127.0.0.1 a.com # XAMGUARD until=100\n"
        + "127.0.0.1 www.a.com # XAMGUARD until=200\n"
        + "127.0.0.1 b.com # XAMGUARD until=100\n"
        + "127.0.0.1 www.b.com # XAMGUARD\n"
        + "127.0.0.1 www.c.com # XAMGUARD\n"
        + "127.0.0.1 c.com # XAMGUARD until=100\n"
    )
    # later time wins, and permanent wins whichever twin comes first
    assert h.list_blocked_until() == {"a.com": 200, "b.com": None, "c.com": None}


def test_unblock_expired_removes_only_timed_blocks_that_are_up(hosts):
    h.block(["done.com"], until=1000)
    h.block(["later.com"], until=5000)
    h.block(["forever.com"])

    assert h.unblock_expired(now=2000) == ["done.com"]
    assert h.list_blocked_until() == {"later.com": 5000, "forever.com": None}


def test_unblock_expired_counts_the_exact_end_second_as_up(hosts):
    h.block(["a.com"], until=1000)
    assert h.unblock_expired(now=999) == []
    assert h.unblock_expired(now=1000) == ["a.com"]


def test_unblock_expired_leaves_the_rest_of_the_file_alone(hosts):
    h.block(["a.com"], until=1000)
    h.unblock_expired(now=2000)
    assert hosts.read_text() == ORIGINAL


def test_unblock_expired_with_nothing_due_does_not_touch_the_file(hosts):
    h.block(["a.com"], until=5000)
    before = hosts.read_text()

    assert h.unblock_expired(now=1) == []
    assert hosts.read_text() == before


def test_unblock_expired_ignores_lines_that_are_not_ours(hosts):
    hosts.write_text(ORIGINAL + "127.0.0.1 x.com # until=5\n")
    assert h.unblock_expired(now=2000) == []
    assert "x.com" in hosts.read_text()


def test_unblock_expired_uses_the_real_clock_by_default(hosts):
    h.block(["old.com"], until=1)  # 1970
    h.block(["far.com"], until=9_999_999_999)  # year 2286
    assert h.unblock_expired() == ["old.com"]


def test_timed_blocks_can_still_be_unblocked_early(hosts):
    h.block(["a.com"], until=9_999_999_999)
    assert h.unblock(["a.com"]) == ["a.com", "www.a.com"]
    assert h.list_blocked() == []


def test_blocking_an_already_timed_site_keeps_its_original_end_time(hosts):
    h.block(["a.com"], until=1000)
    assert h.block(["a.com"], until=9000) == []
    assert h.list_blocked_until() == {"a.com": 1000}


def test_unblock_expired_only_flushes_dns_when_it_removed_something(hosts, monkeypatch):
    calls = []
    monkeypatch.setattr(h, "dnsflush", lambda: calls.append("flush"))

    h.block(["a.com"], until=1000)  # flush 1
    h.unblock_expired(now=1)  # nothing due, no flush
    h.unblock_expired(now=2000)  # flush 2

    assert calls == ["flush", "flush"]


# ---------- DNS flush ----------

def test_block_and_unblock_flush_dns(hosts, monkeypatch):
    calls = []
    monkeypatch.setattr(h, "dnsflush", lambda: calls.append("flush"))

    h.block(["a.com"])
    h.unblock(["a.com"])

    assert calls == ["flush", "flush"]


def test_dnsflush_does_not_crash():
    """Used to crash (get_output instead of capture_output).

    Runs the real ipconfig /flushdns on Windows, which is harmless.
    """
    h.dnsflush()
