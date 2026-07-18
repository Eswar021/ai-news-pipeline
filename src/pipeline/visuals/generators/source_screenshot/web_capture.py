from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from ...common import clean_text, meaningful_words, source_domain


def capture_source_viewport(
    *,
    context,
    scene: dict[str, Any],
    timeout_ms: int,
    post_load_wait_ms: int,
    capture_mode: str,
    focus_zoom: float = 1.3,
    highlight_target: bool = True,
    raw_capture_path: Path | None = None,
    full_page_debug_path: Path | None = None,
) -> dict[str, Any]:
    payload = scene.get("payload") if isinstance(scene.get("payload"), dict) else {}
    url = clean_text(payload.get("url", ""))
    if not url:
        return {"ok": False, "error": "source_article_scene has no payload.url"}

    page = context.new_page()
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        if post_load_wait_ms:
            page.wait_for_timeout(post_load_wait_ms)
        _dismiss_common_overlays(page)
        http_status = response.status if response else None
        blocked_reason = _capture_block_reason(
            title=clean_text(page.title()),
            body_text=_page_body_text(page),
            http_status=http_status,
            challenge_frame_count=_challenge_frame_count(page),
        )
        if blocked_reason:
            screenshot_bytes = page.screenshot(full_page=False, type="png")
            if raw_capture_path:
                raw_capture_path.parent.mkdir(parents=True, exist_ok=True)
                raw_capture_path.write_bytes(screenshot_bytes)
            if full_page_debug_path:
                full_page_debug_path.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(full_page_debug_path), full_page=True)
            return {
                "ok": False,
                "url": url,
                "domain": source_domain(url),
                "http_status": http_status,
                "title": clean_text(page.title()),
                "blocked": True,
                "error": f"source page is not visually capturable: {blocked_reason}",
            }
        match = {"target_found": False, "matched_text": "", "match_score": 0, "scroll_error": ""}
        if capture_mode in {"article_viewport", "target_text_focus", "headline_then_body"}:
            try:
                match = _scroll_near_target(
                    page,
                    clean_text(payload.get("target_text", "")),
                    focus_zoom=focus_zoom,
                    highlight_target=highlight_target,
                )
            except Exception as exc:  # noqa: BLE001 - still capture if matching flakes.
                match = {
                    "target_found": False,
                    "matched_text": "",
                    "match_score": 0,
                    "scroll_error": f"{type(exc).__name__}: {exc}",
                }
                _scroll_to_article_top(page)
        screenshot_bytes = page.screenshot(full_page=False, type="png")
        if raw_capture_path:
            raw_capture_path.parent.mkdir(parents=True, exist_ok=True)
            raw_capture_path.write_bytes(screenshot_bytes)
        if full_page_debug_path:
            full_page_debug_path.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(full_page_debug_path), full_page=True)
        return {
            "ok": True,
            "url": url,
            "domain": source_domain(url),
            "http_status": http_status,
            "title": clean_text(page.title()),
            "target_found": bool(match.get("target_found")),
            "matched_text": clean_text(match.get("matched_text", "")),
            "match_score": match.get("match_score", 0),
            "focus_zoom": match.get("focus_zoom", focus_zoom),
            "screenshot_bytes": screenshot_bytes,
        }
    except PlaywrightTimeoutError as exc:
        return {"ok": False, "url": url, "error": f"timeout: {exc}"}
    except Exception as exc:  # noqa: BLE001 - keep per-scene failures recoverable.
        return {"ok": False, "url": url, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        page.close()


def _dismiss_common_overlays(page) -> None:
    labels = ["Accept", "Accept all", "I accept", "I agree", "Agree", "Continue", "Got it", "Not now", "Close"]
    for label in labels:
        try:
            button = page.get_by_role("button", name=label, exact=False).first
            if button.count():
                button.click(timeout=700)
                page.wait_for_timeout(250)
                return
        except Exception:
            continue


def _page_body_text(page) -> str:
    try:
        return clean_text(page.locator("body").inner_text(timeout=1_000))[:8_000]
    except Exception:
        return ""


def _challenge_frame_count(page) -> int:
    try:
        return page.locator(
            'iframe[src*="challenges.cloudflare.com"], '
            'iframe[title*="challenge" i], iframe[title*="captcha" i]'
        ).count()
    except Exception:
        return 0


def _capture_block_reason(
    *,
    title: str,
    body_text: str,
    http_status: int | None,
    challenge_frame_count: int,
) -> str:
    combined = f"{title}\n{body_text}".casefold()
    markers = (
        "verify you are human",
        "checking your browser",
        "security verification",
        "enable javascript and cookies to continue",
        "cloudflare ray id",
        "attention required",
        "access denied",
        "complete the captcha",
        "bot verification",
    )
    marker = next((value for value in markers if value in combined), "")
    if challenge_frame_count > 0 and (marker or len(clean_text(body_text)) < 320):
        return "anti-bot challenge frame detected"
    if marker:
        return f"challenge/access page detected ({marker})"
    if http_status in {401, 403, 429}:
        return f"HTTP {http_status}"
    return ""


def _scroll_near_target(
    page,
    target_text: str,
    *,
    focus_zoom: float,
    highlight_target: bool,
) -> dict[str, Any]:
    tokens = meaningful_words(target_text)[:12]
    if not tokens:
        _scroll_to_article_top(page)
        return {
            "target_found": False,
            "matched_text": "",
            "match_score": 0,
            "focus_zoom": focus_zoom,
        }

    result = page.evaluate(
        """
        ({ targetText, tokens, focusZoom, highlightTarget }) => {
          const target = (targetText || '').toLowerCase().trim();
          const elements = Array.from(document.querySelectorAll('article, main, h1, h2, h3, p, li, section, div'));
          let best = null;
          let bestScore = 0;
          for (const element of elements) {
            const text = (element.innerText || '').replace(/\\s+/g, ' ').trim();
            if (text.length < 24 || text.length > 1800) continue;
            const lower = text.toLowerCase();
            let score = 0;
            if (target && lower.includes(target)) score += 100;
            for (const token of tokens) {
              if (lower.includes(token)) score += 1;
            }
            const tagWeights = { H1: 14, H2: 12, H3: 10, P: 8, LI: 7, ARTICLE: 2, MAIN: 2, SECTION: 0, DIV: -3 };
            score += tagWeights[element.tagName] || 0;
            if (text.length > 700) score -= 8;
            if (text.length > 1200) score -= 12;
            if (score > bestScore) {
              best = element;
              bestScore = score;
            }
          }
          if (best) {
            const found = bestScore >= Math.min(5, Math.max(2, tokens.length));
            document.documentElement.style.zoom = String(focusZoom);
            best.scrollIntoView({ block: 'center', inline: 'nearest' });
            if (found && highlightTarget) {
              best.dataset.aiCaptureTarget = 'true';
              best.style.outline = '4px solid rgba(33, 190, 255, 0.92)';
              best.style.outlineOffset = '8px';
              best.style.backgroundColor = 'rgba(33, 190, 255, 0.10)';
              best.style.borderRadius = '8px';
            }
            return {
              target_found: found,
              matched_text: (best.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 500),
              match_score: bestScore,
              focus_zoom: focusZoom
            };
          }
          return { target_found: false, matched_text: '', match_score: 0, focus_zoom: focusZoom };
        }
        """,
        {
            "targetText": target_text,
            "tokens": tokens,
            "focusZoom": focus_zoom,
            "highlightTarget": highlight_target,
        },
    )
    if not result.get("matched_text"):
        _scroll_to_article_top(page)
    page.wait_for_timeout(350)
    return result


def _scroll_to_article_top(page) -> None:
    try:
        page.evaluate(
            """
            () => {
              const element = document.querySelector('article, main, h1');
              if (element) element.scrollIntoView({ block: 'start', inline: 'nearest' });
            }
            """
        )
        page.wait_for_timeout(250)
    except Exception:
        return
