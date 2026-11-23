"""Tests for the Jamendo collect stage (pure functions, no network)."""

from ml.dataset.collect import TrackTags, _balance_by_genre, _drop_title_duplicates, _map_tags
from ml.dataset.manifest import ManifestRow

TAG_MAP = {
    "genre": {"rock": ["rock"], "poprock": ["pop", "rock"], "hard": ["rock"], "decade80s": None},
    "mood": {"chillout": ["calm"], "unknown": None},
}


def test_map_tags_splits_categories():
    genre, mood = _map_tags(
        ["genre---poprock", "mood/theme---Chillout", "genre---decade80s"], TAG_MAP
    )
    assert genre == ["pop", "rock"]
    assert mood == ["calm"]


def test_map_tags_takes_case_variants_and_drops_unknown():
    genre, mood = _map_tags(
        ["genre---PopRock", "genre---notmapped", "mood/theme---notmapped"], TAG_MAP
    )
    assert genre == ["pop", "rock"]
    assert mood == []


def test_balance_never_exceeds_per_genre():
    def row(title: str, tags: list[str]) -> ManifestRow:
        return ManifestRow(
            url=f"https://example.org/{title}",
            title=title,
            source="archive_org",
            genre=tags,
            label_origin="dataset_tag",
        )

    rows = [
        row("a", ["rock", "pop"]),
        row("b", ["rock"]),
        row("c", ["pop"]),
        row("d", ["rock"]),
    ]
    selected = _balance_by_genre(rows, per_genre=2)
    counts = [0, 0]
    for selected_row in selected:
        counts[0] += "rock" in selected_row.genre
        counts[1] += "pop" in selected_row.genre
    assert counts == [2, 2]
    assert len(selected) == 3  # a covers both genres


def test_drop_title_duplicates_keeps_first():
    rows = [
        ManifestRow(
            url="https://example.org/1",
            title="Same",
            artist="A",
            source="youtube",
            genre=["rock"],
            label_origin="dataset_tag",
        ),
        ManifestRow(
            url="https://example.org/2",
            title="same",
            artist="a",
            source="youtube",
            genre=["rock"],
            label_origin="dataset_tag",
        ),
    ]
    kept = _drop_title_duplicates(rows)
    assert [str(r.url) for r in kept] == ["https://example.org/1"]


def test_track_tags_named_tuple():
    entry = TrackTags(duration=120.0, tags=["genre---rock"])
    assert entry.duration == 120.0 and entry.tags == ["genre---rock"]
