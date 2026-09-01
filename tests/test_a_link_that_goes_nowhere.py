"""Every module in the sidebar must have a front door.

Reported by pointing at the dentistry link: *"لما بتغط عليها مش بتجيب حاجه"*.
The link was there, the module was on, the per-patient screens were built —
and the link went to `#`, because nothing had ever given the module a landing
page. `shell.html` does that on purpose: a module with no entry in
`MODULE_ENDPOINTS` renders `href="#"` with a "coming soon" tooltip.

That is a reasonable fallback for a module that is genuinely unfinished. It is
a terrible one for a module that is finished everywhere *except* its front
door, because nothing anywhere says so — the module ships, the sidebar shows
it, and the only symptom is a link that does nothing when you click it.

So this asks the question nobody was asking: for every module the sidebar is
willing to show, is there somewhere to go? It checks all three links in the
chain, because each can break without the others noticing — the name is
mapped, the endpoint exists, and the page actually answers.
"""
import pytest

from app.models.permissions import MODULES


def _endpoints(app):
    """The map the sidebar reads, taken from the app itself."""
    with app.test_request_context("/"):
        for processor in app.template_context_processors[None]:
            context = processor()
            if "MODULE_ENDPOINTS" in context:
                return context["MODULE_ENDPOINTS"]
    raise AssertionError("the sidebar's endpoint map is not in the context")


@pytest.fixture
def endpoints(clinic):
    return _endpoints(clinic["app"])


# ------------------------------------------------------- link one: a name ---
@pytest.mark.parametrize("module", MODULES)
def test_every_module_is_mapped_to_an_endpoint(endpoints, module):
    assert endpoints.get(module), (
        f"'{module}' is in the sidebar with no landing page — it will render "
        "as a link that does nothing"
    )


# -------------------------------------------------- link two: it resolves ---
@pytest.mark.parametrize("module", MODULES)
def test_every_endpoint_actually_exists(clinic, endpoints, module):
    """A mapped name that no route registers raises inside `url_for` — which
    means the sidebar, not one screen, is what breaks."""
    registered = {rule.endpoint for rule in clinic["app"].url_map.iter_rules()}
    assert endpoints[module] in registered


# --------------------------------------------------- link three: it opens ---
@pytest.mark.parametrize("module", MODULES)
def test_every_landing_page_answers(clinic, endpoints, module):
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set(f"mod_enabled:{module}", "1")
        clinic["db"].session.commit()

    with clinic["app"].test_request_context("/"):
        from flask import url_for
        address = url_for(endpoints[module])

    response = clinic["sign_in"]("boss").get(address)
    assert response.status_code == 200, (
        f"the sidebar sends {module} to {address}, which answers "
        f"{response.status_code}"
    )


# --------------------------------------------------- and what it looks like -
def test_the_sidebar_renders_no_dead_links_for_enabled_modules(clinic):
    """The symptom itself, at the level the user saw it.

    Not a restatement of the tests above: those read the map, this reads the
    HTML that was actually produced. A `#` here is the exact thing that was
    reported."""
    from app.models import Setting

    with clinic["app"].app_context():
        for module in MODULES:
            Setting.set(f"mod_enabled:{module}", "1")
        clinic["db"].session.commit()

    page = clinic["sign_in"]("boss").get(
        "/dashboard").get_data(as_text=True)
    nav = page[page.index('class="sidebar__nav'):page.index("</nav>")]
    assert 'href="#"' not in nav
