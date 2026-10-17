from atlas.kernel.model_call import classify_error


def test_content_filter_is_a_terminal_model_error():
    category, retryable, status = classify_error(
        RuntimeError("content_filter: response blocked by policy")
    )

    assert category == "content_filter"
    assert retryable is False
    assert status is None
