"""Session 9: the Browser skill — cascade wrapper around the layered drivers.

The wrapper translates the orchestrator's NodeSpec contract into the
typed BrowserOutput / AgentResult contract, and owns the layer cascade:

    Layer 1  — HTML extract via trafilatura (no LLM)
    Layer 2a — deterministic selectors (only if metadata.selectors is given)
    Layer 2b — A11yDriver        (text-only, V9 /v1/chat)
    Layer 3  — SetOfMarksDriver  (vision, V9 /v1/vision)

Escalation rule: a layer escalates when its output is empty or evidently
insufficient. The skill stops at the first layer that produces a useful
answer.

Gateway-access is a first-class failure: if Layer 1's fetch returns a
known CAPTCHA / login-wall / hCaptcha marker, the skill returns
immediately with error_code="gateway_blocked" and does not attempt
the later layers. The orchestrator's recovery path picks this up via
the failure_report (it contains the literal token "gateway_blocked")
and re-invokes the Planner.

This file is the ONLY new code in the integration. The four files
already on disk (client.py, dom.py, highlight.py, driver.py) are
ported verbatim from S9SharedCode/code/browser/ and untouched.
"""
from __future__ import annotations

import os
import asyncio
import time
import re
import shutil
from pathlib import Path
from typing import Any, Literal

import httpx
import trafilatura
from playwright.async_api import async_playwright

from schemas import AgentResult, BrowserOutput, NodeSpec

from .client import V9Client
from .driver import A11yDriver, DriverConfig, DriverResult, SetOfMarksDriver


# ── gateway-block detection ──────────────────────────────────────────────────
# Kept here (next to the cascade that uses it) rather than mutating the
# ported dom.py.  Short, obvious patterns — when this list grows past a
# screenful we should consolidate, but for now explicit is better.
_GATEWAY_BLOCK_MARKERS = (
    # Generic CAPTCHA / hCaptcha / reCAPTCHA. Needles MUST be specific
    # enough that an article ABOUT captchas does not false-positive — we
    # match on class/attribute strings the widgets emit, not their names.
    ("captcha",                "Let's confirm you are human"),
    ("captcha",                "Enter the characters you see below"),
    ("captcha",                "Robot Check"),
    ("captcha",                "Please verify you are a human"),
    ("captcha",                "/errors/validateCaptcha"),
    ("hcaptcha",               'class="h-captcha"'),
    ("hcaptcha",               "data-hcaptcha-widget-id"),
    ("recaptcha",              'class="g-recaptcha"'),
    ("recaptcha",              "g-recaptcha-response"),
    # Cloudflare interstitials.
    ("cloudflare",             "Checking your browser before accessing"),
    ("cloudflare",             "cf-browser-verification"),
    ("cloudflare",             "cf-challenge-running"),
    ("cloudflare",             "cloudflare ray id"),
    # Login walls.  Conservative — only the literal sign-in-required pages.
    ("login_wall",             "You must be logged in"),
    ("login_wall",             "Sign in to continue"),
    ("login_wall",             "Please log in to continue"),
    ("login_wall",             "please sign in to continue"),
    # Access Denied / WAF.
    ("access_denied",          "access denied"),
    ("access_denied",          "error 403"),
    ("access_denied",          "forbidden"),
    ("access_denied",          "waf block"),
    # Rate Limits.
    ("rate_limit",             "rate limit exceeded"),
    ("rate_limit",             "too many requests"),
    ("rate_limit",             "error 429"),
    # Bot detection.
    ("bot_detection",          "bot detection"),
    ("bot_detection",          "automated requests"),
)


def detect_gateway_block(html: str) -> str | None:
    """Return the block type when `html` looks like a gateway-access page
    (CAPTCHA / Cloudflare / login wall), else None. Conservative — false
    positives would mis-route real content to recovery."""
    if not html:
        return None
    h = html.lower()
    for kind, needle in _GATEWAY_BLOCK_MARKERS:
        if needle.lower() in h:
            return kind
    return None


# ── Layer 1: pure-HTTP extraction ────────────────────────────────────────────
_UA = (
    "Mozilla/5.0 (compatible; S9-Browser-Skill/0.1; +llm_gatewayV9)"
)


async def _fetch_html(url: str, timeout: float = 30.0) -> tuple[str, str]:
    """Returns (html, final_url)."""
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True,
                                 headers={"User-Agent": _UA}) as c:
        r = await c.get(url)
        r.raise_for_status()
        return r.text, str(r.url)


def _extract(html: str) -> str:
    text = trafilatura.extract(
        html, include_links=True, include_formatting=False, favor_recall=True,
    )
    return (text or "").strip()


def _extract_keywords(text: str) -> set[str]:
    stopwords = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "with", "by", "of", 
        "about", "is", "are", "was", "were", "be", "been", "have", "has", "had", "do", "does", 
        "did", "from", "sorted", "top", "compare", "list", "show", "give", "find", "get", "extract"
    }
    words = []
    clean_text = re.sub(r"[^\w\s]", " ", text.lower())
    for w in clean_text.split():
        if len(w) > 2 and w.isalpha() and w not in stopwords:
            words.append(w)
    return set(words)


def _is_useful_extract(content: str, goal: str) -> bool:
    """Coarse usefulness check. We trust the gateway/recovery to catch
    genuine no-content failures; this gate only filters obvious nothing
    (< ~200 chars) or the case where the page rendered but the goal asks
    for an interaction (`click`, `fill`, `select`, etc.) — for those goals
    extraction is never sufficient regardless of content length."""
    if len(content) < 200:
        return False
    interactive_verbs = ("click", "fill", "select", "type", "drag",
                         "filter", "sort", "submit", "navigate", "open")
    if any(v in goal.lower() for v in interactive_verbs):
        return False
        
    # Keyword check
    keywords = _extract_keywords(goal)
    if keywords:
        content_lower = content.lower()
        if not any(kw in content_lower for kw in keywords):
            return False
            
    return True


DISTILLER_SYSTEM_PROMPT = (
    "You are a data extraction agent. Your job is to read a web browser interaction history "
    "and extract the structured comparison data as requested by the original goal.\n"
    "You must return a JSON object containing the key 'entities' (a list of dictionaries, "
    "where each dictionary represents a compared item with its attributes like name, description, "
    "likes, downloads, price, free_plan, paid_plan, etc.) and 'comparison_table' (a markdown "
    "table comparing these entities)."
)


# ── the skill ────────────────────────────────────────────────────────────────
class BrowserSkill:
    NAME = "browser"

    def __init__(self, *, gateway_url: str = "http://localhost:8109",
                 agent_tag: str = "browser",
                 a11y_provider_pin: str | None = None,
                 vision_provider_pin: str | None = None,
                 artifacts_root: str | None = None,
                 max_steps_a11y: int = 12,
                 max_steps_vision: int = 12,
                 wall_clock_s: float = 180.0,
                 session: str | None = None):
        self.gateway_url = gateway_url
        self.agent_tag = agent_tag
        self.a11y_provider_pin = a11y_provider_pin or os.getenv("A11Y_PROVIDER", "nvidia")
        self.vision_provider_pin = vision_provider_pin or os.getenv("VISION_PROVIDER", "openrouter")
        self.artifacts_root = Path(artifacts_root) if artifacts_root else None
        self.max_steps_a11y = max_steps_a11y
        self.max_steps_vision = max_steps_vision
        self.wall_clock_s = wall_clock_s
        # Forwarded to V9 so the gateway ledger can attribute each call to
        # the orchestrator session that drove it.
        self.session = session


    # ── public entry point ─────────────────────────────────────────────────
    async def run(self, node: NodeSpec) -> AgentResult:
        url = node.metadata.get("url") or (node.inputs[0] if node.inputs else "")
        goal = node.metadata.get("goal") or "extract main content"
        

        force_path = node.metadata.get("force_path")
        if not url:
            return self._pack_error("", goal, "interaction_failed",
                                    "no url given (metadata.url or inputs[0])")
        t0 = time.time()
        client = V9Client(base_url=self.gateway_url, agent=self.agent_tag,
                          session=self.session)
        artifacts_dir = (
            str(self.artifacts_root / f"browser_{int(t0)}")
            if self.artifacts_root else None
        )

        # ── Layer 1: extract ────────────────────────────────────────────────
        # When the bare GET fails (403/405 from a WAF, connection refused, …)
        # we do NOT bail out: anti-bot edges often serve a CAPTCHA *page* to
        # a real browser session that they refuse via bare GET. Falling
        # through to the Playwright layers lets _drive() detect the rendered
        # CAPTCHA and surface gateway_blocked properly.
        layer1_http_error: str | None = None
        try:
            html, final_url = await _fetch_html(url)
        except httpx.HTTPError as e:
            layer1_http_error = f"layer1 fetch failed: {e}"
            html, final_url = "", url

        if html:
            block = detect_gateway_block(html)
            if block:
                return self._pack_error(url, goal, "gateway_blocked",
                                        f"gateway_blocked: {block} marker on {final_url}",
                                        elapsed=time.time() - t0)
            # trafilatura is fundamentally broken for e-commerce grids. 
            # Skip Layer 1 for these sites to force Playwright (Layer 2b/3)
            if "amazon" in url.lower() or "flipkart" in url.lower():
                content = ""
            else:
                content = _extract(html)
            
            if content and _is_useful_extract(content, goal):
                return self._pack(url, goal, "extract", turns=0,
                                  content=content, final_url=final_url,
                                  elapsed=time.time() - t0)

        # ── Layer 2a: deterministic selectors (only if caller gave any) ────
        selectors = node.metadata.get("selectors") or []
        if selectors:
            det = await self._try_deterministic(url, goal, selectors)
            if det is not None:
                if det.success:
                    content = det.output.get("content") or ""
                    final_url = det.output.get("final_url") or url
                    return self._pack(
                        url, goal, "deterministic", turns=len(selectors),
                        content=content, final_url=final_url,
                        elapsed=time.time() - t0,
                    )
                else:
                    return self._pack_error(
                        url, goal, "interaction_failed",
                        det.error or "deterministic path failed",
                        elapsed=time.time() - t0,
                    )

        # ── Layer 2b: a11y ──────────────────────────────────────────────────
        if force_path == "vision":
            # Skip a11y entirely — caller wants Layer 3 explicitly.
            a11y_result = DriverResult(success=False, note="skipped by force_path=vision")
        else:
            a11y_result = await self._drive(
                A11yDriver, url, goal, client, artifacts_dir,
                self.a11y_provider_pin, self.max_steps_a11y,
            )
        if getattr(a11y_result, "gateway_blocked", False):
            return self._pack_error(url, goal, "gateway_blocked",
                                    a11y_result.note or "gateway_blocked after JS render",
                                    elapsed=time.time() - t0)
        if a11y_result.success:
            return await self._pack_driver(client, "a11y", url, goal, a11y_result,
                                     final_url=a11y_result.final_url,
                                     elapsed=time.time() - t0)

        # ── Layer 3: vision ─────────────────────────────────────────────────
        try:
            vis_result = await self._drive(
                SetOfMarksDriver, url, goal, client, artifacts_dir,
                self.vision_provider_pin, self.max_steps_vision,
            )
            if getattr(vis_result, "gateway_blocked", False):
                return self._pack_error(url, goal, "gateway_blocked",
                                        vis_result.note or "gateway_blocked after JS render",
                                        elapsed=time.time() - t0)
            if vis_result.success:
                return await self._pack_driver(client, "vision", url, goal, vis_result,
                                         final_url=vis_result.final_url,
                                         elapsed=time.time() - t0)
            vis_note = vis_result.note
        except Exception as e:
            vis_note = f"vision exception: {e}"

        # If we reach here, neither succeeded perfectly, but a11y might have
        # successfully rendered and extracted the page. We should return that
        # content so the pipeline can continue.
        if getattr(a11y_result, "extracted", None):
            return await self._pack_driver(client, "a11y", url, goal, a11y_result,
                                     final_url=getattr(a11y_result, "final_url", url),
                                     elapsed=time.time() - t0)

        last_err = (vis_note or a11y_result.note
                    or layer1_http_error or "all layers exhausted")
        return self._pack_error(url, goal, "interaction_failed",
                                f"all layers exhausted; last: {last_err}",
                                elapsed=time.time() - t0)

    # ── per-layer driver runs ──────────────────────────────────────────────
    async def _drive(self, DriverCls, url, goal, client, artifacts_dir,
                     provider_pin, max_steps):
        # Place each layer's per-turn artifacts under its own subdir so
        # turn_##_* filenames from one layer don't overwrite another's.
        if artifacts_dir:
            from pathlib import Path as _P
            sub = _P(artifacts_dir) / DriverCls.LAYER_NAME
            sub.mkdir(parents=True, exist_ok=True)
            artifacts_dir = str(sub)
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context(
                viewport={"width": 1366, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                locale="en-US",
            )
            await ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',"
                "{get:()=>undefined});"
            )
            page = await ctx.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                # Last-chance gateway-block check on the rendered page (some
                # walls only show up after JS executes).
                kind = detect_gateway_block(await page.content())
                if kind:
                    await browser.close()
                    out = DriverResult(
                        success=False,
                        note=f"gateway_blocked ({kind}) detected after JS render at {page.url}",
                    )
                    # Annotation BrowserSkill reads to propagate the code.
                    out.gateway_blocked = True
                    return out
                await asyncio.sleep(1.0)
                cfg = DriverConfig(
                    goal=goal, max_steps=max_steps, max_failures=3,
                    artifacts_dir=artifacts_dir, provider=provider_pin,
                )
                drv = DriverCls(page, client, cfg)
                result = await drv.run()
                result.final_url = page.url
                result.extracted = ""
                try:
                    result.extracted = _extract(await page.content())
                except Exception:                          # noqa: BLE001
                    pass
                result.turns = len(drv.steps)
                result.actions = [
                    {"turn": s.turn, "actions": s.actions, "outcome": s.outcome}
                    for s in drv.steps
                ]
                result.artifacts_dir = artifacts_dir
                return result
            finally:
                await browser.close()

    async def _try_deterministic(self, url, goal, selectors) -> AgentResult | None:
        """Runs caller-supplied selector instructions through Playwright. Each
        step is `{action, selector, value?}`. Returns AgentResult on success
        or None to let the cascade fall through to a11y."""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context(
                viewport={"width": 1366, "height": 900},
            )
            page = await ctx.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                for i, step in enumerate(selectors, start=1):
                    sel = step.get("selector")
                    if not sel:
                        await browser.close()
                        return None
                    loc = page.locator(sel).first
                    try:
                        await loc.wait_for(state="visible", timeout=8000)
                    except Exception:                          # noqa: BLE001
                        await browser.close()
                        return None
                    if step.get("action") == "fill":
                        await loc.fill(step.get("value", ""))
                    elif step.get("action") == "click":
                        await loc.click()
                    elif step.get("action") == "key":
                        await page.keyboard.press(step.get("value", "Enter"))
                content = _extract(await page.content())
                final = page.url
                await browser.close()
                return self._pack(
                    url, goal, "deterministic", turns=len(selectors),
                    content=content, final_url=final, elapsed=0.0,
                )
            except Exception:                          # noqa: BLE001
                await browser.close()
                return None

    # ── packers ────────────────────────────────────────────────────────────
    async def _distill_comparison(self, client: V9Client, steps_text: str, content: str, goal: str, url: str) -> dict:
        prompt = (
            f"You are Distiller. The user wanted to achieve this goal on {url}:\n"
            f"GOAL: {goal}\n\n"
            f"We drove a browser to find the data. Here are the interaction steps we took:\n"
            f"{steps_text}\n\n"
            f"And here is the raw extracted text from the final page state:\n"
            f"{content[:15000]}\n\n"
            "Extract the items and their stats. Return a JSON object containing EXACTLY two keys:\n"
            "1. 'comparison_table': a formatted Markdown table comparing the top items (include Rank, Name, Params, Likes, etc. whatever is relevant to the goal).\n"
            "2. 'summary': a 2-3 sentence textual summary of the findings.\n"
        )
        schema = {
            "type": "object",
            "required": ["comparison_table", "summary"],
            "properties": {
                "comparison_table": {"type": "string"},
                "summary": {"type": "string"}
            }
        }
        try:
            res = await client.chat(
                prompt, system="You are a data extractor. You must extract the models and their stats from the provided text into a comparison table. The text contains the models, their parameters, downloads, and likes. Output the table directly.", schema=schema, schema_name="Extraction", max_tokens=1024
            )
            return res.parsed or {}
        except Exception:
            return {}

    def _pack(self, url, goal, path, *, turns, content=None, actions=None,
              final_url=None, elapsed=0.0) -> AgentResult:
        extracted_data = {}
        if "cost_summary" not in extracted_data:
            extracted_data["cost_summary"] = {
                "path": path,
                "turns": turns,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost": 0.0,
                "wall_clock_time": elapsed
            }
        out = BrowserOutput(
            url=url, goal=goal, path=path, turns=turns,
            content=content, actions=actions or [], final_url=final_url,
            screenshots=[], page_states=[], extracted_data=extracted_data,
        )
        return AgentResult(
            success=True, agent_name=self.NAME,
            output=out.model_dump(), elapsed_s=elapsed,
        )

    async def _pack_driver(self, client: V9Client, path, url, goal, drv_result,
                     *, final_url, elapsed) -> AgentResult:
        screenshots = []
        page_states = []
        
        artifacts_dir = getattr(drv_result, "artifacts_dir", None)
        if artifacts_dir:
            from pathlib import Path as _P
            import shutil
            src_dir = _P(artifacts_dir)
            dest_dir = _P(__file__).parent.parent / "state" / "artifacts" / "screenshots"
            dest_dir.mkdir(parents=True, exist_ok=True)
            
            for s in getattr(drv_result, "steps", []):
                turn = s.turn
                raw_name = f"turn_{turn:02d}_raw.png"
                src_raw = src_dir / raw_name
                if src_raw.exists():
                    dest_name = f"{self.session or 'default'}_{path}_turn_{turn:02d}_raw.png"
                    dest_path = dest_dir / dest_name
                    try:
                        shutil.copy2(src_raw, dest_path)
                        screenshots.append(f"state/artifacts/screenshots/{dest_name}")
                    except Exception:
                        pass
                
                marked_name = f"turn_{turn:02d}_marked.png"
                src_marked = src_dir / marked_name
                if src_marked.exists():
                    dest_name_m = f"{self.session or 'default'}_{path}_turn_{turn:02d}_marked.png"
                    dest_path_m = dest_dir / dest_name_m
                    try:
                        shutil.copy2(src_marked, dest_path_m)
                        screenshots.append(f"state/artifacts/screenshots/{dest_name_m}")
                    except Exception:
                        pass

        steps_text = ""
        for s in getattr(drv_result, "steps", []):
            page_states.append({
                "turn": s.turn,
                "url": getattr(s, "url", ""),
                "title": getattr(s, "title", ""),
                "path": path,
                "a11y_summary": getattr(s, "a11y_summary", []),
            })
            steps_text += f"Turn {s.turn}: {s.outcome}\n"

        total_input_tokens = sum(s.tokens_in for s in getattr(drv_result, "steps", []))
        total_output_tokens = sum(s.tokens_out for s in getattr(drv_result, "steps", []))
        
        tot_cost = 0.0
        try:
            from llm_gatewayV9.pricing import estimate_usd
            for s in getattr(drv_result, "steps", []):
                tot_cost += estimate_usd(s.provider, s.tokens_in, s.tokens_out)
        except Exception:
            pass

        final_a11y = ""
        if getattr(drv_result, "steps", []):
            final_a11y = "\n".join(drv_result.steps[-1].a11y_summary)
        
        note = getattr(drv_result, "extracted", "")
        raw_extracted = f"Agent Note: {note}\n\n{final_a11y}" if note else final_a11y

        extracted_data = await self._distill_comparison(
            client, steps_text, raw_extracted, goal, url
        )
        extracted_data["cost_summary"] = {
            "path": path,
            "turns": len(getattr(drv_result, "steps", [])),
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "cost": tot_cost,
            "wall_clock_time": elapsed
        }

        report = []
        report.append("=" * 80)
        report.append(" BROWSER AGENT REPLAY REPORT")
        report.append("=" * 80)
        report.append(f"1. Original user goal: {goal}")
        report.append("-" * 80)
        report.append("2. Planner DAG: planner ──> Browser ──> distiller ──> formatter")
        report.append("-" * 80)
        report.append(f"3. Browser path chosen: {path}")
        report.append("-" * 80)
        report.append("4. Browser actions taken:")
        for s in getattr(drv_result, "steps", []):
            acts = ", ".join(f"{a.get('type')}({a.get('mark') or a.get('value', '')})" for a in s.actions)
            report.append(f"  [Turn {s.turn}] {acts} ──> {s.outcome}")
        if not getattr(drv_result, "steps", []):
            report.append("  (No actions logged)")
        report.append("-" * 80)
        report.append("5. Screenshots or page-state logs:")
        for turn_idx, s in enumerate(screenshots, start=1):
            report.append(f"  [Screenshot {turn_idx}] {s}")
        for st in page_states:
            report.append(f"  [Turn {st['turn']}] URL: {st['url']}")
        report.append("-" * 80)
        report.append("6. Extracted Data:")
        report.append("  (Structured data available in JSON output)")
        report.append("-" * 80)
        report.append("7. Final comparison table:")
        if extracted_data.get("comparison_table"):
            report.append(extracted_data.get("comparison_table"))
        else:
            report.append("  (No comparison table generated)")
        report.append("-" * 80)
        report.append("8. Turn count and cost summary:")
        report.append(f"  Total Turns:     {len(getattr(drv_result, 'steps', []))}")
        report.append(f"  Input Tokens:    {total_input_tokens}")
        report.append(f"  Output Tokens:   {total_output_tokens}")
        report.append(f"  Estimated Cost:  ${tot_cost:.6f}")
        report.append(f"  Wall Clock Time: {elapsed:.2f}s")
        report.append("=" * 80)

        # Provide ONLY the comparison table and replay report to downstream nodes to avoid token limits!
        final_content = "\n".join(report)
        
        # Explicitly print the report to stdout because the orchestrator truncates FINAL to 600 chars
        print(f"\n{final_content}\n")

        out = BrowserOutput(
            url=url, goal=goal, path=path,
            turns=len(getattr(drv_result, "steps", [])),
            content=final_content,
            actions=[{"turn": s.turn, "actions": s.actions, "outcome": s.outcome} for s in getattr(drv_result, "steps", [])],
            screenshots=screenshots,
            page_states=page_states,
            extracted_data=extracted_data,
            final_url=final_url,
        )
        return AgentResult(
            success=True, agent_name=self.NAME,
            output=out.model_dump(), elapsed_s=elapsed,
            cost=tot_cost,
        )

    def _pack_error(self, url, goal, code, msg, *, elapsed=0.0) -> AgentResult:
        path = "blocked" if code == "gateway_blocked" else "extract"
        out = BrowserOutput(
            url=url or "", goal=goal, path=path, turns=0, content=None,
            actions=[], screenshots=[], page_states=[], extracted_data={},
        )
        return AgentResult(
            success=False, agent_name=self.NAME,
            output=out.model_dump(), error=msg, error_code=code,
            elapsed_s=elapsed,
        )
