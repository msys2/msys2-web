# SPDX-License-Identifier: MIT

from fastapi import Request

from app.web import licenses_to_html


def test_licenses_to_html() -> None:
    r = Request({"type": "http"})
    assert licenses_to_html(r, []) == ""
    assert licenses_to_html(r, ["FOO"]) == "FOO"
    assert licenses_to_html(r, ["FOO", "BAR"]) == "BAR OR FOO"
    assert licenses_to_html(r, ["FOO", "&", "<", ">"]) == \
        "&amp; OR &lt; OR &gt; OR FOO"
    assert licenses_to_html(r, ["spdx:FOO-BAR.OK"]) == (
        '<a href="https://spdx.org/licenses/FOO-BAR.OK.html">FOO-BAR.OK</a>')
    assert licenses_to_html(r, ["spdx:< > &"]) == '&lt; &gt; &amp;'
    assert licenses_to_html(r, ["spdx:(FOO)"]) == \
        '(<a href="https://spdx.org/licenses/FOO.html">FOO</a>)'
    assert licenses_to_html(r, ["spdx:FOO", "spdx:BAR"]) == (
        '<a href="https://spdx.org/licenses/BAR.html">BAR</a> OR '
        '<a href="https://spdx.org/licenses/FOO.html">FOO</a>')
    assert licenses_to_html(r, ["custom:BLA", "GPL"]) == "GPL OR custom:BLA"
    assert licenses_to_html(r, ["spdx:BLA", "GPL"]) == \
        'GPL OR <a href="https://spdx.org/licenses/BLA.html">BLA</a>'
    assert licenses_to_html(r, ["spdx:MIT OR BSD-3-Clause", "GPL"]) == (
        'GPL OR (<a href="https://spdx.org/licenses/MIT.html">MIT</a> OR '
        '<a href="https://spdx.org/licenses/BSD-3-Clause.html">BSD-3-Clause</a>)')
    assert licenses_to_html(r, ["&<>"]) == "&amp;&lt;&gt;"
    assert licenses_to_html(r, ["spdx:GPL-2.0-or-later WITH Autoconf-exception-2.0"]) == (
        '<a href="https://spdx.org/licenses/GPL-2.0-or-later.html">GPL-2.0-or-later</a> WITH '
        '<a href="https://spdx.org/licenses/Autoconf-exception-2.0.html">Autoconf-exception-2.0</a>'
    )
    assert licenses_to_html(r, ["spdx:GPL-2.0+"]) == (
        '<a href="https://spdx.org/licenses/GPL-2.0%2B.html">GPL-2.0+</a>'
    )
    assert licenses_to_html(r, ["spdx:StandardML-NJ"]) == (
        '<a href="https://spdx.org/licenses/StandardML-NJ.html">StandardML-NJ</a>'
    )
    assert licenses_to_html(r, ["spdx:LicenseRef-foobar"]) == 'foobar'
