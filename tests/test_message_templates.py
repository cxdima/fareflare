"""The template engine substitutes values and nothing else: no code, no attribute access."""

from html.parser import HTMLParser

import pytest

from fareflare.message_templates import (
    MAX_PLACEHOLDERS,
    MAX_TEMPLATE_LENGTH,
    MAX_TEMPLATE_LINES,
    Run,
    TemplateError,
    normalize_template,
    parse_template,
    render,
)

WORDS = frozenset({"price", "fare", "route", "link", "note"})


class Parsed(HTMLParser):
    """Fails on unbalanced markup, which Telegram would reject outright."""

    def __init__(self, value):
        super().__init__(convert_charrefs=True)
        self.open, self.text, self.links = [], [], []
        self.feed(value)
        self.close()
        assert not self.open, f"unclosed tags: {self.open}"

    def handle_starttag(self, tag, attrs):
        assert tag in ("b", "i", "code", "a")
        self.open.append(tag)
        self.links += [value for name, value in attrs if name == "href"]

    def handle_endtag(self, tag):
        assert self.open and self.open[-1] == tag
        self.open.pop()

    def handle_data(self, data):
        self.text.append(data)


def show(template, **values):
    return render(template, values, WORDS)


def test_placeholders_are_replaced_in_plain_text_and_escaped_in_markup():
    result = show("Now {price} on {route}", price="USD 191.00", route="<b>DEN & DFW</b>")
    assert result.text == "Now USD 191.00 on <b>DEN & DFW</b>"
    assert result.html == "Now USD 191.00 on &lt;b&gt;DEN &amp; DFW&lt;/b&gt;"
    assert result.used == {"price", "route"}


def test_emphasis_becomes_balanced_telegram_markup():
    result = show("**{price}** __fare {fare}__ `{route}`", price="$1", fare="Economy", route="A")
    assert result.text == "$1 fare Economy A"
    assert result.html == "<b>$1</b> <i>fare Economy</i> <code>A</code>"
    nested = show("**bold __both__**")
    assert nested.html == "<b>bold </b><b><i>both</i></b>"
    assert Parsed(nested.html).text == ["bold ", "both"]


def test_monospace_never_nests_other_emphasis():
    # Telegram does not allow code inside bold, so the inner style wins.
    assert show("**a `b` c**").html == "<b>a </b><code>b</code><b> c</b>"
    assert show("`**{price}**`", price="$1").html == "<code>**$1**</code>"


def test_optional_group_needs_every_placeholder_inside_it():
    template = "{price}[ · Fare: {fare}][ ({note})]"
    assert show(template, price="$1", fare="Economy", note="low").text == "$1 · Fare: Economy (low)"
    assert show(template, price="$1", fare="", note="low").text == "$1 (low)"
    assert show(template, price="$1").text == "$1"
    both = "[{fare} / {note}]"
    assert show("x" + both, fare="Economy").text == "x"
    assert show("x" + both, fare="Economy", note="low").text == "xEconomy / low"


def test_whitespace_only_values_count_as_missing():
    assert show("{price}[ {fare}]", price="$1", fare="   ").text == "$1"


def test_lines_without_content_disappear_and_blank_lines_collapse():
    template = "{price}\n\n{fare}\n[Note: {note}]\n\n{route}\n\n"
    assert show(template, price="$1", route="DEN").text == "$1\n\nDEN"
    assert show(template, price="$1", fare="Economy", route="DEN").text == "$1\n\nEconomy\n\nDEN"
    # A literal line is the author's own text and always stays.
    assert show("{fare}\nThanks!\n{note}").text == "Thanks!"
    assert show("{fare}").text == ""


def test_literal_label_without_a_group_is_kept_so_groups_are_the_way_to_hide_it():
    assert show("Fare: {fare}").text == "Fare:"
    assert show("[Fare: {fare}]").text == ""


def test_multi_line_values_keep_their_own_styles_and_line_breaks():
    itinerary = (Run("DEN → DFW", bold=True), Run(" · Mar 14"), Run("\nDFW → DEN", bold=True))
    result = render("__{route}__", {"route": itinerary}, WORDS)
    assert result.text == "DEN → DFW · Mar 14\nDFW → DEN"
    assert result.html == "<b><i>DEN → DFW</i></b><i> · Mar 14</i>\n<b><i>DFW → DEN</i></b>"


def test_links_escape_their_address_and_may_be_bold_but_never_monospace():
    link = (Run("Open", href='https://example.test/?a=1&b="2"'),)
    result = render("**{link}** `{link}`", {"link": link}, WORDS)
    parsed = Parsed(result.html)
    assert parsed.links == ['https://example.test/?a=1&b="2"'] * 2
    assert "&amp;b=&quot;2&quot;" in result.html
    assert "<code>" not in result.html and result.text == "Open Open"


def test_backslash_makes_syntax_characters_literal():
    result = show(r"\[{price}\] \{price\} \*\*not bold\*\* \\ \`", price="$1")
    assert result.text == r"[$1] {price} **not bold** \ `"
    assert "<" not in result.html


def test_single_markers_and_ordinary_punctuation_are_literal():
    assert show("5 * 3 = 15, snake_case, a_b").text == "5 * 3 = 15, snake_case, a_b"


def test_trailing_spaces_left_by_dropped_groups_are_trimmed_but_indentation_stays():
    assert show("  • {price}  [{fare}]", price="$1").text == "  • $1"


@pytest.mark.parametrize(
    "template",
    [
        "{price.__class__}",  # attribute access
        "{price!r}",  # conversion flag
        "{price:>10}",  # format specification
        "{0}",  # positional argument
        "{}",  # empty name
        "{{ 7*7 }}",  # another engine's expression
        "{% for x in y %}",  # another engine's statement
        "{Price}",  # names are exact and lower case
        "{secret}",  # outside the vocabulary
        "{price",  # never closed
    ],
)
def test_anything_beyond_a_known_placeholder_name_is_rejected(template):
    with pytest.raises(TemplateError):
        parse_template(template, WORDS)


@pytest.mark.parametrize(
    "template, message",
    [
        ("price}", "Unmatched }"),
        ("[{price}", "missing its closing ]"),
        ("{price}]", "Unmatched ]"),
        ("[{price}[{fare}]]", "cannot be nested"),
        ("[only words]", "needs a placeholder"),
        ("**{price}", "Close \\*\\*bold\\*\\*"),
        ("__{price}", "Close __italic__"),
        ("`{price}", "Close `monospace`"),
        ("**a __b** c__", "overlap"),
        ("[**{price}]**", "before the end of its optional group"),
        ("**[{price}**]", "overlap"),
        ("ends with \\", "backslash"),
    ],
)
def test_malformed_templates_explain_what_to_fix(template, message):
    with pytest.raises(TemplateError, match=message):
        parse_template(template, WORDS)


def test_emphasis_and_groups_must_close_on_their_own_line():
    with pytest.raises(TemplateError):
        parse_template("**{price}\n{fare}**", WORDS)
    with pytest.raises(TemplateError):
        parse_template("[{price}\n{fare}]", WORDS)


@pytest.mark.parametrize("character", ["\t", "\r", "\x00", "\x7f", "\u202e", "\u2066", "\u200f"])
def test_control_and_direction_characters_are_rejected(character):
    with pytest.raises(TemplateError, match="control or text-direction"):
        parse_template("{price}" + character, WORDS)


def test_size_limits_bound_every_rendered_message():
    parse_template("x" * MAX_TEMPLATE_LENGTH, WORDS)
    with pytest.raises(TemplateError, match="characters"):
        parse_template("x" * (MAX_TEMPLATE_LENGTH + 1), WORDS)
    parse_template("\n".join("x" * MAX_TEMPLATE_LINES), WORDS)
    with pytest.raises(TemplateError, match="lines"):
        parse_template("\n".join("x" * (MAX_TEMPLATE_LINES + 1)), WORDS)
    assert len("{fare}" * MAX_PLACEHOLDERS) <= MAX_TEMPLATE_LENGTH
    parse_template("{fare}" * MAX_PLACEHOLDERS, WORDS)
    with pytest.raises(TemplateError, match="placeholders"):
        parse_template("{fare}" * (MAX_PLACEHOLDERS + 1), WORDS)
    with pytest.raises(TemplateError, match="must be text"):
        parse_template(None, WORDS)  # type: ignore[arg-type]


def test_values_are_data_and_are_never_parsed_as_template_syntax():
    hostile = "{price} [x] **bold** `code` \\ <script>"
    result = show("{note}", note=hostile, price="SHOULD NOT APPEAR")
    assert result.text == hostile
    assert "SHOULD NOT APPEAR" not in result.html and "<script>" not in result.html
    assert Parsed(result.html).text == [hostile]


def test_stored_form_is_canonical():
    assert normalize_template("\r\n\r\n{price}  \r\n{fare}\n\n") == "{price}\n{fare}"
    # A lone carriage return is a line break too, so normalizing twice changes nothing.
    assert normalize_template("{price}\r{fare}\r \n") == "{price}\n{fare}"
    assert normalize_template("") == ""
    with pytest.raises(TemplateError):
        normalize_template(7)  # type: ignore[arg-type]


def test_rendered_markup_is_always_well_formed():
    template = "**{price}**[ __({note})__]\n[{fare}][  ·  `{route}`]\n{link}"
    for values in (
        {},
        {"price": "$1"},
        {"price": "<", "note": ">", "fare": "&", "route": '"'},
        {"price": "$1", "link": (Run("Open", href="https://example.test/"),)},
    ):
        Parsed(render(template, values, WORDS).html)
