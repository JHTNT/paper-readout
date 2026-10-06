import copy
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import expect, sync_playwright

from generate import render_html
from test_support import example_paper


class GlossaryBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = sync_playwright().start()
        cls.addClassCleanup(cls.runtime.stop)
        cls.browser = cls.runtime.chromium.launch(
            headless=True, channel=os.getenv("TEST_BROWSER_CHANNEL")
        )
        cls.addClassCleanup(cls.browser.close)
        directory = TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        cls.html = Path(directory.name) / "paper.html"
        paper = example_paper()
        paper["glossary"] = [
            {
                "term": "CNN",
                "zh": "卷積神經網路",
                "full_name": "convolutional neural network",
                "definition": "CNN 的解釋",
                "paper_usage": "本文使用 CNN",
                "page": 3,
            },
            {
                "term": "neural network",
                "zh": "神經網路",
                "full_name": "",
                "definition": "神經網路的解釋",
                "paper_usage": "模型結構",
                "page": 2,
            },
            {
                "term": "FFT",
                "zh": "快速傅立葉轉換",
                "full_name": "",
                "definition": "FFT 的解釋",
                "paper_usage": "頻域分析",
                "page": 4,
            },
        ]
        first = paper["sections"][0]["blocks"][0]
        first.update(
            en=r"A convolutional neural network (CNN) learns. CNN is useful; CNNs ACNN. \(FFT + x\)",
            zh="卷積神經網路會學習。神經網路可用於分類。",
            annotation="CNN 使用卷積層。",
            importance=4,
            en_highlights=["convolutional", "network (CNN) learns", "CNN is useful"],
            figures=[],
            tables=[],
        )
        second = copy.deepcopy(first)
        second.update(
            en="CNN CNN convolutional neural network",
            zh="卷積神經網路",
            importance=5,
            en_highlights=[],
        )
        third = copy.deepcopy(first)
        third.update(
            en=r"CNNs ACNN \(CNN + FFT\)",
            zh="",
            annotation="",
            importance=3,
            en_highlights=[],
        )
        paper["sections"][0]["blocks"] = [first, second, third]
        render_html(paper, cls.html)

    def setUp(self):
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 900})
        self.addCleanup(self.context.close)
        # Tests use only local assets; no CDN or API requests.
        self.context.route("http://**/*", lambda route: route.abort())
        self.context.route("https://**/*", lambda route: route.abort())
        self.page = self.context.new_page()
        errors = []
        self.page.on("pageerror", lambda error: errors.append(str(error)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        self.page.goto(self.html.as_uri())
        self.first = self.page.locator(".pair").nth(0)
        self.trigger = self.first.locator(".term-trigger").first
        self.panel = self.page.locator("#term-panel")

    def test_terms_are_deduplicated_per_block_and_preserve_highlights(self):
        expect(self.first.locator(".term-trigger")).to_have_text(
            ["CNN", "neural network"]
        )
        expect(self.page.locator(".pair").nth(1).locator(".term-trigger")).to_have_text(
            ["CNN"]
        )
        expect(self.page.locator(".pair").nth(2).locator(".block-terms")).to_have_count(
            0
        )
        expect(self.first.locator(".annotation .block-terms")).to_have_count(1)
        expect(self.first.locator("blockquote mark")).to_have_text(
            ["convolutional", "network (CNN) learns", "CNN is useful"]
        )
        self.assertLess(self.trigger.bounding_box()["height"], 28)

    def test_hover_can_enter_card_and_leave_without_moving_focus(self):
        focus = self.page.evaluate("document.activeElement.tagName")
        self.trigger.hover()
        expect(self.panel).to_be_visible()
        self.assertEqual(self.page.evaluate("document.activeElement.tagName"), focus)
        self.panel.locator(".term-text").first.hover()
        self.page.wait_for_timeout(300)  # Must outlast the hover-close delay.
        expect(self.panel).to_be_visible()
        self.page.mouse.move(1, 1)
        expect(self.panel).to_be_hidden()

    def test_scroll_before_hover_card_opens_does_not_cancel_it(self):
        self.trigger.scroll_into_view_if_needed()
        self.trigger.evaluate(
            """el => {
                el.dispatchEvent(new MouseEvent('mouseenter'));
                document.dispatchEvent(new Event('scroll'));
            }"""
        )
        expect(self.panel).to_be_visible()

    def test_click_keyboard_and_outside_close_preserve_reading_position(self):
        self.trigger.scroll_into_view_if_needed()
        scroll = self.page.evaluate("scrollY")
        self.trigger.click()
        expect(self.panel).to_be_visible()
        expect(self.panel.locator('dt [lang="en"]')).to_have_text("CNN")
        self.assertEqual(self.page.evaluate("scrollY"), scroll)
        self.page.mouse.move(1, 1)
        self.page.wait_for_timeout(300)
        expect(self.panel).to_be_visible()
        self.page.keyboard.press("Escape")
        expect(self.panel).to_be_hidden()
        expect(self.trigger).to_be_focused()
        self.page.keyboard.press("Enter")
        expect(self.panel).to_be_visible()
        self.page.mouse.click(1, 1)
        expect(self.panel).to_be_hidden()

    def test_mobile_filter_and_print(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.trigger.click()
        expect(self.panel).to_be_visible()
        box = self.panel.bounding_box()
        self.assertGreaterEqual(box["x"], 0)
        self.assertLessEqual(box["x"] + box["width"], 390)
        self.assertFalse(
            self.page.evaluate("document.documentElement.scrollWidth > innerWidth")
        )
        self.page.mouse.click(1, 1)
        expect(self.panel).to_be_hidden()
        self.page.get_by_role("button", name="核心", exact=True).click()
        expect(self.first).to_be_hidden()
        expect(
            self.page.locator(".pair").nth(1).locator(".block-terms")
        ).to_be_visible()
        self.page.emulate_media(media="print")
        expect(self.page.locator(".pair").nth(1).locator(".block-terms")).to_be_hidden()


if __name__ == "__main__":
    unittest.main()
