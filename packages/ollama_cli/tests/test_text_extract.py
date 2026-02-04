import re

from ollama_cli.text_extract import html_to_text


def test_html_to_text_strips_scripts_and_tags() -> None:
    html = """
    <html>
      <head>
        <title>Example</title>
        <script>console.log('x');</script>
        <style>body{display:none}</style>
      </head>
      <body>
        <h1>Hello</h1>
        <p>World &amp; beyond</p>
      </body>
    </html>
    """
    text = html_to_text(html)
    assert "Hello" in text
    assert "World" in text
    assert "&" in text
    assert "<script" not in text.lower()
    assert re.search(r"<\w+", text) is None
