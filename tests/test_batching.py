from industrial_flow.utils.batching import chunked


def test_chunked():
    assert list(chunked([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]
