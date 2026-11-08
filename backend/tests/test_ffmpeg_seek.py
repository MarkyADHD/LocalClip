from src.media.ffmpeg import _seek_to_first_range


def test_seeks_to_just_before_earliest_range_and_shifts_ranges():
    seek, ranges = _seek_to_first_range([(16368.5, 16372.0), (16337.0, 16360.0)])
    assert seek == ["-ss", "16336.000"]
    assert ranges == [(32.5, 36.0), (1.0, 24.0)]


def test_no_seek_near_the_start():
    assert _seek_to_first_range([(0.5, 3.0)]) == ([], [(0.5, 3.0)])
