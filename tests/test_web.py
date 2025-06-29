# SPDX-License-Identifier: MIT

from app.web import _licenses_to_html


def test_licenses_to_html() -> None:
    assert _licenses_to_html([]) == ""
    assert _licenses_to_html(["FOO"]) == "FOO"
    assert _licenses_to_html(["FOO", "BAR"]) == "FOO OR BAR"
    assert _licenses_to_html(["FOO", "&", "<", ">"]) == \
        "FOO OR &amp; OR &lt; OR &gt;"
    assert _licenses_to_html(["spdx:FOO-BAR.OK"]) == (
        '<a href="https://spdx.org/licenses/FOO-BAR.OK.html">FOO-BAR.OK</a>')
    assert _licenses_to_html(["spdx:< > &"]) == '&lt; &gt; &amp;'
    assert _licenses_to_html(["spdx:(FOO)"]) == \
        '(<a href="https://spdx.org/licenses/FOO.html">FOO</a>)'
    assert _licenses_to_html(["spdx:FOO", "spdx:BAR"]) == (
        '<a href="https://spdx.org/licenses/FOO.html">FOO</a> OR '
        '<a href="https://spdx.org/licenses/BAR.html">BAR</a>')
    assert _licenses_to_html(["custom:BLA", "GPL"]) == "custom:BLA OR GPL"
    assert _licenses_to_html(["spdx:BLA", "GPL"]) == \
        '<a href="https://spdx.org/licenses/BLA.html">BLA</a> OR GPL'
    assert _licenses_to_html(["spdx:MIT OR BSD-3-Clause", "GPL"]) == (
        '(<a href="https://spdx.org/licenses/MIT.html">MIT</a> OR '
        '<a href="https://spdx.org/licenses/BSD-3-Clause.html">BSD-3-Clause</a>) OR GPL')
    assert _licenses_to_html(["&<>"]) == "&amp;&lt;&gt;"
    assert _licenses_to_html(["spdx:GPL-2.0-or-later WITH Autoconf-exception-2.0"]) == (
        '<a href="https://spdx.org/licenses/GPL-2.0-or-later.html">GPL-2.0-or-later</a> WITH '
        '<a href="https://spdx.org/licenses/Autoconf-exception-2.0.html">Autoconf-exception-2.0</a>'
    )
    assert _licenses_to_html(["spdx:GPL-2.0+"]) == (
        '<a href="https://spdx.org/licenses/GPL-2.0%2B.html">GPL-2.0+</a>'
    )
    assert _licenses_to_html(["spdx:StandardML-NJ"]) == (
        '<a href="https://spdx.org/licenses/StandardML-NJ.html">StandardML-NJ</a>'
    )
    assert _licenses_to_html(["spdx:LicenseRef-foobar"]) == 'foobar'
