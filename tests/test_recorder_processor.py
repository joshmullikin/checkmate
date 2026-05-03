from agent.nodes.recorder_processor import RecorderEventProcessor


def test_relative_path_conversion_and_navigate_dedup():
    processor = RecorderEventProcessor(base_url="https://example.com")

    step1 = processor.process_event({"type": "navigate", "url": "https://example.com/dashboard"})
    assert step1.action == "navigate"
    assert step1.value == "/dashboard"

    # Duplicate navigate should be ignored
    step2 = processor.process_event({"type": "navigate", "url": "https://example.com/dashboard"})
    assert step2 is None


def test_link_click_followed_by_navigate_merges_and_adds_wait():
    processor = RecorderEventProcessor(base_url="https://example.com")

    buffered = processor.process_event(
        {
            "type": "click",
            "tag": "A",
            "text": "Sign in",
            "selector": "a[href='/login']",
            "timestamp": 1000,
        }
    )
    assert buffered is None

    merged = processor.process_event(
        {
            "type": "navigate",
            "url": "https://example.com/login",
            "timestamp": 1200,
        }
    )
    assert merged is not None
    assert merged.action == "click"
    assert merged.causes_navigation is True
    assert processor.steps[-1].action == "wait_for_page"


def test_type_password_masks_value():
    processor = RecorderEventProcessor()
    step = processor.process_event(
        {
            "type": "type",
            "text": "Password",
            "value": "plain-secret",
            "is_password": True,
        }
    )
    assert step.action == "type"
    assert step.value == "{{password}}"
    assert step.is_credential is True


def test_scroll_events_are_collapsed():
    processor = RecorderEventProcessor()
    first = processor.process_event({"type": "scroll"})
    second = processor.process_event({"type": "scroll"})

    assert first is not None
    assert first.action == "scroll"
    assert second is None


def test_get_all_steps_flushes_pending_click():
    processor = RecorderEventProcessor()
    processor.process_event(
        {
            "type": "click",
            "tag": "A",
            "text": "Docs",
            "selector": "a[href='/docs']",
            "timestamp": 1000,
        }
    )

    steps = processor.get_all_steps()
    assert len(steps) == 1
    assert steps[0].action == "click"


def test_should_add_wait_for_page_true_when_last_navigate():
    from agent.nodes.recorder_processor import ProcessedStep

    processor = RecorderEventProcessor()
    processor.steps.append(ProcessedStep(action="navigate", value="/dashboard", description="nav"))
    assert processor._should_add_wait_for_page() is True


def test_pending_link_click_then_late_navigate_flushes_click():
    """If navigate arrives after 500ms, merge does not occur and pending click is flushed."""
    processor = RecorderEventProcessor(base_url="https://example.com")
    processor.process_event(
        {
            "type": "click",
            "tag": "A",
            "text": "Reports",
            "selector": "a[href='/reports']",
            "timestamp": 1000,
        }
    )

    out = processor.process_event(
        {
            "type": "navigate",
            "url": "https://example.com/reports",
            "timestamp": 1700,
        }
    )

    # Returns flushed click, while navigate + wait_for_page are still appended.
    assert out is not None
    assert out.action == "click"
    actions = [s.action for s in processor.steps]
    assert actions == ["click", "navigate", "wait_for_page"]


def test_pending_click_navigate_merge_without_url_still_flushes_click():
    """When merged navigate has no URL/value, click is still emitted as nav-causing."""
    processor = RecorderEventProcessor(base_url="https://example.com")
    processor.process_event(
        {
            "type": "click",
            "tag": "A",
            "text": "Home",
            "selector": "a[href='/']",
            "timestamp": 1000,
        }
    )

    out = processor.process_event(
        {
            "type": "navigate",
            "timestamp": 1200,
        }
    )

    assert out is not None
    assert out.action == "click"
    assert out.causes_navigation is True


def test_navigate_suppressed_after_nav_causing_click_adds_wait_if_missing():
    from agent.nodes.recorder_processor import ProcessedStep

    processor = RecorderEventProcessor(base_url="https://example.com")
    # Simulate previous merged click without an existing wait step.
    processor.steps.append(
        ProcessedStep(
            action="click",
            target="Sign in",
            description='Click "Sign in"',
            causes_navigation=True,
        )
    )

    out = processor.process_event({"type": "navigate", "url": "https://example.com/login"})
    assert out is None
    assert processor.steps[-1].action == "wait_for_page"


def test_make_click_step_builds_css_text_and_aria_locators():
    processor = RecorderEventProcessor()
    step = processor._make_click_step(
        {
            "tag": "BUTTON",
            "text": "Open",
            "selector": "button.open",
            "ariaPath": "main > button:nth-child(1)",
            "timestamp": 1234,
        }
    )
    assert step.locators is not None
    assert step.locators["css"] == "button.open"
    assert step.locators["text"] == "Open"
    assert step.locators["ariaPath"] == "main > button:nth-child(1)"


def test_make_click_step_input_submit_branch():
    """Covers INPUT submit special-case target/description branch."""
    processor = RecorderEventProcessor()
    step = processor._make_click_step(
        {
            "tag": "INPUT",
            "type": "submit",
            "text": "",
            "selector": "input[type='submit']",
            "timestamp": 1000,
        }
    )
    assert step.action == "click"
    assert step.target == "Submit"
    assert step.description == "Click submit button"


def test_should_add_wait_for_page_true_when_last_navigate():
    from agent.nodes.recorder_processor import ProcessedStep

    processor = RecorderEventProcessor()
    processor.steps.append(ProcessedStep(action="navigate", value="/dashboard", description="nav"))
    assert processor._should_add_wait_for_page() is True


def test_pending_link_click_then_late_navigate_flushes_click():
    """If navigate arrives after 500ms, merge does not occur and pending click is flushed."""
    processor = RecorderEventProcessor(base_url="https://example.com")
    processor.process_event(
        {
            "type": "click",
            "tag": "A",
            "text": "Reports",
            "selector": "a[href='/reports']",
            "timestamp": 1000,
        }
    )

    out = processor.process_event(
        {
            "type": "navigate",
            "url": "https://example.com/reports",
            "timestamp": 1700,
        }
    )

    # Returns flushed click, while navigate + wait_for_page are still appended.
    assert out is not None
    assert out.action == "click"
    actions = [s.action for s in processor.steps]
    assert actions == ["click", "navigate", "wait_for_page"]


def test_pending_click_navigate_merge_without_url_still_flushes_click():
    """When merged navigate has no URL/value, click is still emitted as nav-causing."""
    processor = RecorderEventProcessor(base_url="https://example.com")
    processor.process_event(
        {
            "type": "click",
            "tag": "A",
            "text": "Home",
            "selector": "a[href='/']",
            "timestamp": 1000,
        }
    )

    out = processor.process_event(
        {
            "type": "navigate",
            "timestamp": 1200,
        }
    )

    assert out is not None
    assert out.action == "click"
    assert out.causes_navigation is True


def test_navigate_suppressed_after_nav_causing_click_adds_wait_if_missing():
    from agent.nodes.recorder_processor import ProcessedStep

    processor = RecorderEventProcessor(base_url="https://example.com")
    # Simulate previous merged click without an existing wait step.
    processor.steps.append(
        ProcessedStep(
            action="click",
            target="Sign in",
            description='Click "Sign in"',
            causes_navigation=True,
        )
    )

    out = processor.process_event({"type": "navigate", "url": "https://example.com/login"})
    assert out is None
    assert processor.steps[-1].action == "wait_for_page"


def test_make_click_step_builds_css_text_and_aria_locators():
    processor = RecorderEventProcessor()
    step = processor._make_click_step(
        {
            "tag": "BUTTON",
            "text": "Open",
            "selector": "button.open",
            "ariaPath": "main > button:nth-child(1)",
            "timestamp": 1234,
        }
    )
    assert step.locators is not None
    assert step.locators["css"] == "button.open"
    assert step.locators["text"] == "Open"
    assert step.locators["ariaPath"] == "main > button:nth-child(1)"


def test_make_click_step_input_submit_branch():
    """Covers INPUT submit special-case target/description branch."""
    processor = RecorderEventProcessor()
    step = processor._make_click_step(
        {
            "tag": "INPUT",
            "type": "submit",
            "text": "",
            "selector": "input[type='submit']",
            "timestamp": 1000,
        }
    )
    assert step.action == "click"
    assert step.target == "Submit"
    assert step.description == "Click submit button"


def test_to_relative_path_same_origin():
    """_to_relative_path converts same-origin URL to relative path."""
    processor = RecorderEventProcessor(base_url="https://example.com")
    assert processor._to_relative_path("https://example.com/login") == "/login"
    assert processor._to_relative_path("https://example.com/") == "/"
    # Path is empty after stripping origin
    assert processor._to_relative_path("https://example.com") == "/"


def test_to_relative_path_different_origin():
    """_to_relative_path returns full URL for a different origin."""
    processor = RecorderEventProcessor(base_url="https://example.com")
    external = "https://other.example.com/page"
    assert processor._to_relative_path(external) == external


def test_to_relative_path_no_base_url():
    """_to_relative_path returns URL unchanged when no base_url configured."""
    processor = RecorderEventProcessor(base_url="")
    url = "https://example.com/page"
    assert processor._to_relative_path(url) == url


def test_should_add_wait_for_page_after_navigate():
    """_should_add_wait_for_page returns True after a navigate step."""
    processor = RecorderEventProcessor(base_url="https://example.com")
    processor.process_event({"type": "navigate", "url": "https://example.com/home"})
    # After navigate, wait_for_page is auto-inserted, so the last step is wait_for_page
    # _should_add_wait_for_page should return False (already waiting)
    assert processor._should_add_wait_for_page() is False


def test_should_add_wait_for_page_empty_steps():
    """_should_add_wait_for_page returns False for empty step list."""
    processor = RecorderEventProcessor()
    assert processor._should_add_wait_for_page() is False


def test_click_with_data_testid_selector():
    """_make_click_step uses data-testid selector as target."""
    processor = RecorderEventProcessor()
    step = processor.process_event({
        "type": "click",
        "tag": "BUTTON",
        "text": "Submit",
        "selector": '[data-testid="submit-button"]',
        "timestamp": 1000,
    })
    assert step.action == "click"
    assert step.target == '[data-testid="submit-button"]'


def test_click_button_with_text():
    """_make_click_step uses text as target for BUTTON elements."""
    processor = RecorderEventProcessor()
    step = processor.process_event({
        "type": "click",
        "tag": "BUTTON",
        "text": "Login",
        "selector": "button.login-btn",
        "timestamp": 1000,
    })
    assert step.action == "click"
    assert step.target == "Login"


def test_click_submit_input():
    """_make_click_step handles INPUT type=submit."""
    processor = RecorderEventProcessor()
    step = processor.process_event({
        "type": "click",
        "tag": "INPUT",
        "type": "submit",
        "text": "",
        "selector": "input[type='submit']",
        "timestamp": 1000,
    })
    assert step.action == "click"
    assert step.target in ("Submit", "input[type='submit']")


def test_click_with_coordinates_and_locators():
    """_make_click_step preserves coordinates and locators."""
    processor = RecorderEventProcessor()
    step = processor.process_event({
        "type": "click",
        "tag": "DIV",
        "text": "Some div",
        "selector": "div.container",
        "coordinates": {"x": 100, "y": 200},
        "ariaPath": "div > span",
        "timestamp": 1000,
    })
    assert step.coordinates == {"x": 100, "y": 200}
    assert step.locators is not None
    assert "css" in step.locators
    assert step.locators["ariaPath"] == "div > span"


def test_click_unknown_tag_long_text():
    """_make_click_step uses selector when text is long."""
    processor = RecorderEventProcessor()
    step = processor.process_event({
        "type": "click",
        "tag": "SPAN",
        "text": "This is a very long text that is definitely more than 50 chars long yes it is",
        "selector": "span.verbose",
        "timestamp": 1000,
    })
    assert step.action == "click"
    assert step.target == "span.verbose"


def test_hover_event():
    """_process_hover creates hover step."""
    processor = RecorderEventProcessor()
    step = processor.process_event({
        "type": "hover",
        "text": "Menu",
        "selector": "nav.menu",
    })
    assert step.action == "hover"
    assert step.target == "Menu"


def test_select_event():
    """_process_select creates select step."""
    processor = RecorderEventProcessor()
    step = processor.process_event({
        "type": "select",
        "text": "Country",
        "value": "Canada",
        "selector": "select#country",
    })
    assert step.action == "select"
    assert step.value == "Canada"
    assert step.target == "Country"


def test_select_event_no_label_uses_selector():
    """_process_select uses selector when text is empty."""
    processor = RecorderEventProcessor()
    step = processor.process_event({
        "type": "select",
        "text": "",
        "value": "US",
        "selector": "#region",
    })
    assert step.target == "#region"


def test_unknown_event_type():
    """_process_unknown creates low-confidence click step."""
    processor = RecorderEventProcessor()
    step = processor.process_event({"type": "custom_event", "selector": ".custom"})
    assert step.action == "click"
    assert step.confidence == 0.4


def test_type_event_no_label_uses_selector():
    """_process_type uses selector when text is empty."""
    processor = RecorderEventProcessor()
    step = processor.process_event({
        "type": "type",
        "text": "",
        "value": "hello",
        "selector": "#username",
    })
    assert step.action == "type"
    assert step.target == "#username"


def test_navigate_without_url_returns_none():
    """_process_navigate returns None when no URL provided."""
    processor = RecorderEventProcessor()
    step = processor.process_event({"type": "navigate", "url": ""})
    assert step is None


def test_navigate_cross_origin_is_not_deduped():
    """Navigate to a cross-origin URL is not collapsed."""
    processor = RecorderEventProcessor(base_url="https://example.com")
    step1 = processor.process_event({"type": "navigate", "url": "https://example.com/page"})
    assert step1 is not None
    # Navigate to a different origin should not be deduplicated
    step2 = processor.process_event({"type": "navigate", "url": "https://other.com/page"})
    assert step2 is not None


def test_process_event_flushes_pending_click_before_type():
    """A pending click from an <a> tag is flushed before the next non-navigate event."""
    processor = RecorderEventProcessor()
    # Buffer a click on <A>
    processor.process_event({
        "type": "click",
        "tag": "A",
        "text": "Profile",
        "selector": "a.profile",
        "timestamp": 1000,
    })
    # Process a type event — pending click should be flushed first
    processor.process_event({
        "type": "type",
        "text": "Name",
        "value": "Alice",
        "timestamp": 2000,
    })
    actions = [s.action for s in processor.steps]
    assert "click" in actions
    assert "type" in actions
    click_idx = actions.index("click")
    type_idx = actions.index("type")
    assert click_idx < type_idx


def test_navigate_suppression_keeps_existing_wait_step():
    from agent.nodes.recorder_processor import ProcessedStep
    processor = RecorderEventProcessor(base_url="https://example.com")
    processor.steps.append(ProcessedStep(action="click", target="Go", description='Click "Go"', causes_navigation=True))
    processor.steps.append(ProcessedStep(action="wait_for_page", value="load", description="Wait for page to finish loading"))
    out = processor.process_event({"type": "navigate", "url": "https://example.com/next"})
    assert out is None
    waits = [s for s in processor.steps if s.action == "wait_for_page"]
    assert len(waits) == 1


def test_make_click_step_without_selector_uses_text_locator_only():
    processor = RecorderEventProcessor()
    step = processor._make_click_step({"tag": "BUTTON", "text": "Continue", "selector": "", "timestamp": 42})
    assert step.locators is not None
    assert "css" not in step.locators
    assert step.locators["text"] == "Continue"


def test_get_all_steps_no_pending_click_returns_existing():
    processor = RecorderEventProcessor()
    processor.process_event({"type": "scroll"})
    steps = processor.get_all_steps()
    assert len(steps) == 1
    assert steps[0].action == "scroll"
