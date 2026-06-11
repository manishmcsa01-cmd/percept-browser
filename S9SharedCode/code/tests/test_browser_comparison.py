import pytest
from schemas import BrowserOutput, NodeSpec, AgentResult
from browser.skill import detect_gateway_block, _is_useful_extract

def test_precondition_check():
    # Test CAPTCHA block
    html_captcha = "<html><body>Let's confirm you are human. Please complete the captcha below.</body></html>"
    assert detect_gateway_block(html_captcha) == "captcha"

    # Test Cloudflare WAF block
    html_cf = "<html><body>Checking your browser before accessing. cf-challenge-running</body></html>"
    assert detect_gateway_block(html_cf) == "cloudflare"

    # Test login wall
    html_login = "<html><body>You must be logged in to access this page. Please log in to continue.</body></html>"
    assert detect_gateway_block(html_login) == "login_wall"

    # Test rate limit
    html_limit = "<html><body>Rate limit exceeded. Too many requests.</body></html>"
    assert detect_gateway_block(html_limit) == "rate_limit"

    # Test normal html
    html_normal = "<html><body>Welcome to the home page! Here are some products.</body></html>"
    assert detect_gateway_block(html_normal) is None

def test_keyword_matching():
    # Test keyword matching success with a non-interactive goal
    goal = "Find the parameter count of meta-llama Llama-3-8B-Instruct"
    content_useful = (
        "The model meta-llama Llama-3-8B-Instruct has 8 billion parameters. "
        "These models are highly popular among researchers and developers. HuggingFace provides a great "
        "platform for sharing and testing these models. Many text-generation models are open source and "
        "available for download, featuring outstanding performance in various language tasks."
    )
    assert _is_useful_extract(content_useful, goal) is True

    # Test keyword matching fail (length is > 200, but no keywords from goal)
    content_useless = (
        "This is a random article about cooking recipes. Add some salt and pepper. "
        "Cooking is an art that requires patience and dedication. Mix the ingredients "
        "well, preheat the oven to 350 degrees Fahrenheit, bake for 30 minutes, and "
        "let it cool before serving to your guests."
    )
    assert _is_useful_extract(content_useless, goal) is False

    # Test interactive verbs bypass
    goal_interactive = "Click on the first model card and compare its downloads"
    content_any = "We found several huggingface text-generation models with many likes, such as meta-llama/Llama-3-8B."
    # Interactive verbs should cause _is_useful_extract to return False (forces browser cascade)
    assert _is_useful_extract(content_any, goal_interactive) is False

def test_browser_output_schema():
    # Verify that BrowserOutput handles the blocked path and correct fields
    out = BrowserOutput(
        url="https://huggingface.co/models",
        goal="Compare models",
        path="blocked",
        turns=0,
        content=None,
        actions=[],
        screenshots=[],
        page_states=[],
        extracted_data={},
        final_url=None
    )
    assert out.path == "blocked"
