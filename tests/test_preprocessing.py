from pathlib import Path

import pytest

from novel_tts.preprocessing import format_processed, preprocess_text, read_processed


def test_preprocess_example() -> None:
    source = (
        "小明是一个小学生，住在翻斗大街1001号。\n"
        "小明今天遇到了小红，对他说：“嗨，早上好！”\n"
        "“嗨，早上好！”小红说。\n"
    )
    result = preprocess_text(source)
    assert result.warnings == []
    assert result.lines == [
        "小明是一个小学生，住在翻斗大街1001号。",
        "小明今天遇到了小红，对他说：",
        "“嗨，早上好！”",
        "“嗨，早上好！”",
        "小红说。",
    ]
    assert format_processed(result.lines).splitlines()[-1] == "5-小红说。"


def test_multiple_and_nested_quotes() -> None:
    result = preprocess_text("他说：“她喊‘快走’，然后跑了。”“知道了。”")
    assert result.lines == ["他说：", "“她喊‘快走’，然后跑了。”", "“知道了。”"]
    assert result.warnings == []


def test_blank_lines_and_unclosed_quote() -> None:
    result = preprocess_text("\n  \n他说：“没有结束\n")
    assert result.lines == ["他说：", "“没有结束"]
    assert "unclosed quote" in result.warnings[0]


def test_read_processed_rejects_malformed_line(tmp_path: Path) -> None:
    path = tmp_path / "001.txt"
    path.write_text("1-good\nbad\n", encoding="utf-8")
    with pytest.raises(ValueError, match="physical line 2"):
        read_processed(path)
