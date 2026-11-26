from ml.dataset.clean_seeds import clean, normalize, split_song

OVERRIDES = {"artists": {normalize("Kraftwerk"): ["electronic"]}, "songs": {}}


def test_split_song_repairs_double_dash_and_missing_space():
    assert split_song("Autechre - - Incunabula") == ("Autechre", "Incunabula")
    assert split_song("Cyndi Lauper- Girls Just Want to Have Fun") == (
        "Cyndi Lauper",
        "Girls Just Want to Have Fun",
    )


def test_duplicate_spellings_merge_with_union_of_genres_and_moods():
    lines = [
        "Journey - Dont Stop Believin | rock",
        "Journey - Don't Stop Believin' | rock|pop | happy",
    ]
    cleaned, renames, dropped = clean(lines, OVERRIDES, {})
    assert cleaned == ["Journey - Don't Stop Believin' | rock|pop | happy"]
    assert len(renames) == 1 and not dropped


def test_artist_override_and_parent_genres():
    lines = ["Kraftwerk - The Model | techno", "Fisher - Losing It | house"]
    cleaned, _, _ = clean(lines, OVERRIDES, {})
    assert cleaned[0].startswith("Kraftwerk - The Model | electronic")
    assert cleaned[1].startswith("Fisher - Losing It | house|electronic")


def test_lines_without_a_title_are_dropped():
    cleaned, _, dropped = clean(["M83 | electronic", " | experimental"], OVERRIDES, {})
    assert cleaned == [] and len(dropped) == 2
