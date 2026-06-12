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
        match = {"target_found": False, "matched_text": "", "match_score": 0, "scroll_error": ""}
        if capture_mode in {"article_viewport", "target_text_focus", "headline_then_body"}:
            try:
                match = _scroll_near_target(page, clean_text(payload.get("target_text", "")))
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
            "http_status": response.status if response else None,
            "title": clean_text(page.title()),
            "target_found": bool(match.get("target_found")),
            "matched_text": clean_text(match.get("matched_text", "")),
            "match_score": match.get("match_score", 0),
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


def _scroll_near_target(page, target_text: str) -> dict[str, Any]:
    tokens = meaningful_words(target_text)[:12]
    if not tokens:
        _scroll_to_article_top(page)
        return {"target_found": False, "matched_text": "", "match_score": 0}

    result = page.evaluate(
        """
        ({ targetText, tokens }) => {
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
            if (score > bestScore) {
              best = element;
              bestScore = score;
            }
          }
          if (best) {
            best.scrollIntoView({ block: 'center', inline: 'nearest' });
            return {
              target_found: bestScore >= Math.min(5, Math.max(2, tokens.length)),
              matched_text: (best.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 500),
              match_score: bestScore
            };
          }
          return { target_found: false, matched_text: '', match_score: 0 };
        }
        """,
        {"targetText": target_text, "tokens": tokens},
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

