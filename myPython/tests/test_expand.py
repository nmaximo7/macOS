"""content_expand (reading, cleaning, the quality gate, saving), openrouter.call_openrouter and the prompts."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import content_expand as E
import mymessages
import openrouter


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


ARTICLE = (
    "# Faraday\n\nFaraday's law links a changing flux to an electric field.\n\n"
    "See [the notes](https://example.org/notes) and ![plot](/img/plot.png).\n\n"
    "{{< youtube abc123 >}}\n\n## The law\n\n$$\\oint E\\cdot dl = -\\frac{d\\Phi}{dt}$$\n"
)


class ArticleBody(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_front_matter_is_dropped(self):
        page = write(self.dir / "a.md", "---\ntitle: T\n---\n\nBody text here.\n")
        self.assertEqual(E.article_body(page), "Body text here.")

    def test_page_without_front_matter(self):
        page = write(self.dir / "a.md", "Just text\n\nmore\n")
        self.assertEqual(E.article_body(page), "Just text\n\nmore")

    def test_crlf_and_bom(self):
        page = self.dir / "a.md"
        page.write_bytes("﻿---\r\ntitle: T\r\n---\r\nBody\r\n".encode("utf-8"))
        self.assertEqual(E.article_body(page), "Body")

    def test_dashes_inside_the_body_are_kept(self):
        page = write(self.dir / "a.md", "---\ntitle: T\n---\nA\n\n---\n\nB\n")
        self.assertEqual(E.article_body(page), "A\n\n---\n\nB")


class CleanAnswer(unittest.TestCase):
    def test_plain_answer_is_untouched(self):
        text, notes = E.clean_answer("# Title\n\nSome text.\n")
        self.assertEqual(text, "# Title\n\nSome text.")
        self.assertEqual(notes, [])

    def test_think_block_removed(self):
        text, notes = E.clean_answer("<think>hmm\nhmm</think>\n\n# Title\n\nBody")
        self.assertEqual(text, "# Title\n\nBody")
        self.assertTrue(any("think" in n for n in notes))

    def test_wrapping_fence_removed(self):
        text, notes = E.clean_answer("```markdown\n# Title\n\nBody\n```")
        self.assertEqual(text, "# Title\n\nBody")
        self.assertTrue(notes)

    def test_article_made_of_code_is_not_unwrapped(self):
        code = "```python\nprint(1)\n```"
        self.assertEqual(E.clean_answer(code)[0], code)

    def test_inner_code_blocks_survive_unwrapping(self):
        raw = "```markdown\nText\n\n```python\nx = 1\n```\n\nMore\n```"
        self.assertEqual(E.clean_answer(raw)[0], "Text\n\n```python\nx = 1\n```\n\nMore")

    def test_unbalanced_fence_is_left_alone(self):
        raw = "```\nText\n```python\nx\n```"  # an odd number of fence lines inside: not a wrapper
        self.assertEqual(E.clean_answer(raw)[0], raw)

    def test_front_matter_removed(self):
        text, notes = E.clean_answer("---\ntitle: X\n---\n\n# Real\n\nBody")
        self.assertEqual(text, "# Real\n\nBody")
        self.assertTrue(any("front matter" in n for n in notes))

    def test_chatty_first_line_removed(self):
        text, notes = E.clean_answer("Here is the expanded article:\n\n# Title\n\nBody")
        self.assertEqual(text, "# Title\n\nBody")
        self.assertTrue(any("introductory" in n for n in notes))

    def test_a_heading_that_starts_with_here_is_kept(self):
        raw = "# Here is how it works\n\nBody"
        self.assertEqual(E.clean_answer(raw)[0], raw)

    def test_empty_answer(self):
        self.assertEqual(E.clean_answer("")[0], "")
        self.assertEqual(E.clean_answer(None)[0], "")


class CompareTexts(unittest.TestCase):
    def good(self):
        return ARTICLE + "\n" + "More explanation of the law and its meaning. " * 20

    def test_a_good_expansion_has_no_warnings(self):
        warnings, notes = E.compare_texts(ARTICLE, self.good())
        self.assertEqual(warnings, [])
        self.assertTrue(any("->" in n for n in notes))

    def test_shorter_answer(self):
        warnings, _ = E.compare_texts(ARTICLE, "# Faraday\n\nShort.")
        self.assertTrue(any("SHORTER" in w for w in warnings))

    def test_barely_longer_answer(self):
        original = "word " * 100
        warnings, _ = E.compare_texts(original, "word " * 105)
        self.assertFalse(any("longer" in w for w in warnings), "little growth is a caution, not a problem")
        self.assertIn("only 5% longer", E.growth_caution(100, 105))
        self.assertEqual(E.growth_caution(100, 130), "")
        self.assertEqual(E.growth_caution(100, 90), "")  # shorter is a real warning, reported elsewhere
        self.assertEqual(E.growth_caution(0, 10), "")

    def test_empty_answer(self):
        self.assertEqual(E.compare_texts(ARTICLE, "  ")[0], ["the answer is empty"])

    def test_placeholders_are_found(self):
        for bad in ("Proof: (insert proof here)", "TODO: finish", "The details are to be completed.", "Steps omitted for brevity: proof omitted", "[...]"):
            with self.subTest(bad=bad):
                warnings, _ = E.compare_texts(ARTICLE, self.good() + "\n" + bad)
                self.assertTrue(any("placeholder" in w for w in warnings), warnings)

    def test_a_placeholder_already_in_the_original_is_not_blamed_on_the_model(self):
        original = ARTICLE + "\nTODO: my own note\n"
        warnings, _ = E.compare_texts(original, self.good() + "\nTODO: my own note\n")
        self.assertFalse(any("placeholder" in w for w in warnings))

    def test_lost_link_and_image(self):
        expanded = self.good().replace("https://example.org/notes", "https://other.org").replace("/img/plot.png", "/img/x.png")
        warnings, _ = E.compare_texts(ARTICLE, expanded)
        self.assertTrue(any("missing" in w for w in warnings))
        self.assertTrue(any("NEW link" in w for w in warnings))

    def test_new_bare_url_is_flagged(self):
        warnings, _ = E.compare_texts(ARTICLE, self.good() + "\nSee https://invented.example/paper.pdf.")
        self.assertTrue(any("invented.example" in w for w in warnings))

    def test_lost_shortcode(self):
        warnings, _ = E.compare_texts(ARTICLE, self.good().replace("{{< youtube abc123 >}}", ""))
        self.assertTrue(any("shortcode" in w for w in warnings))

    def test_wrong_math_delimiters(self):
        warnings, _ = E.compare_texts(ARTICLE, self.good() + "\n\\(x^2\\) and \\[y\\]")
        self.assertTrue(any("math" in w for w in warnings))

    def test_renamed_heading_is_only_a_note(self):
        warnings, notes = E.compare_texts(ARTICLE, self.good().replace("## The law", "## The statement"))
        self.assertEqual(warnings, [])
        self.assertTrue(any("heading" in n for n in notes))


class OutputDir(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        (self.root / "site" / "content").mkdir(parents=True)

    def settings(self, out):
        return SimpleNamespace(expand_output_dir=out, hugo_root=self.root / "site", expand_provider="openrouter")

    def test_custom_folder(self):
        with mock.patch.object(E, "get_settings", return_value=self.settings(self.root / "out")):
            self.assertEqual(E.output_dir(), self.root / "out")

    def test_default_is_in_the_home_folder(self):
        with mock.patch.object(E, "get_settings", return_value=self.settings(None)):
            self.assertEqual(E.output_dir(), E.DEFAULT_OUTPUT_DIR.resolve())

    def test_inside_content_is_refused(self):
        for inside in (self.root / "site" / "content", self.root / "site" / "content" / "calculus"):
            with self.subTest(inside=inside), mock.patch.object(E, "get_settings", return_value=self.settings(inside)):
                with self.assertRaises(E.ExpandError):
                    E.output_dir()

    def test_inside_the_site_but_outside_content_is_allowed(self):
        with mock.patch.object(E, "get_settings", return_value=self.settings(self.root / "site" / "drafts")):
            self.assertEqual(E.output_dir(), self.root / "site" / "drafts")

    def test_slug(self):
        self.assertEqual(E._slug(Path("content/calculus/maxwell faraday.md")), "maxwell-faraday")
        self.assertEqual(E._slug(Path(self.root / "site" / "content" / "topic" / "index.md")), "topic")


class ExpandArticle(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.page = write(self.root / "site" / "content" / "calculus" / "faraday.md", "---\ntitle: F\n---\n" + ARTICLE)
        self.out = self.root / "out"
        settings = SimpleNamespace(expand_output_dir=self.out, hugo_root=self.root / "site", expand_provider="openrouter",
                                   model_query="local-model", openrouter_model="openrouter/free")
        p = mock.patch.object(E, "get_settings", return_value=settings)
        p.start()
        self.addCleanup(p.stop)
        self.expanded = ARTICLE + "\n" + "A long careful explanation of the law. " * 30

    def run_expand(self, answer=None, **kwargs):
        answer = self.expanded if answer is None else answer
        with mock.patch.object(E, "_ask_openrouter", return_value=(answer, "vendor/model:free", 1)) as ask, \
                contextlib.redirect_stdout(io.StringIO()):
            result = E.expand_article(self.page, **kwargs)
        return result, ask

    def test_only_the_body_is_sent(self):
        _, ask = self.run_expand()
        sent = ask.call_args.args[0]
        self.assertNotIn("title: F", sent)
        self.assertTrue(sent.startswith("# Faraday"))

    def test_result_is_saved_outside_content_and_the_page_is_untouched(self):
        before = self.page.read_text()
        result, _ = self.run_expand()
        self.assertEqual(result.model, "vendor/model:free")
        self.assertEqual(result.provider, "openrouter")
        self.assertTrue(result.saved_to.is_file())
        self.assertEqual(result.saved_to.parent, self.out)
        self.assertTrue(result.saved_to.name.startswith("faraday-expanded-"))
        self.assertEqual(result.saved_to.read_text(), result.text + "\n")
        self.assertEqual(self.page.read_text(), before)
        self.assertFalse(result.serious, result.warnings)
        self.assertGreater(result.words_after, result.words_before)

    def test_no_save(self):
        result, _ = self.run_expand(save=False)
        self.assertIsNone(result.saved_to)
        self.assertFalse(self.out.exists())

    def test_bad_answer_is_flagged_not_hidden(self):
        result, _ = self.run_expand(answer="# Faraday\n\nShort (insert proof here).")
        self.assertTrue(result.serious)

    def test_cleaning_is_applied(self):
        result, _ = self.run_expand(answer="```markdown\n" + self.expanded + "\n```")
        self.assertFalse(result.text.startswith("```"))
        self.assertTrue(any("fence" in n for n in result.notes))

    def test_copy(self):
        with mock.patch.object(E, "copy_to_clipboard", return_value=True) as clip:
            result, _ = self.run_expand(copy=True)
        clip.assert_called_once_with(result.text)
        self.assertTrue(result.copied)

    def test_copy_not_available(self):
        with mock.patch.object(E, "copy_to_clipboard", return_value=False):
            result, _ = self.run_expand(copy=True)
        self.assertFalse(result.copied)
        self.assertTrue(any("clipboard" in n for n in result.notes))

    def test_provider_ollama_uses_the_local_function(self):
        with mock.patch.object(E, "_ask_ollama", return_value=(self.expanded, "local-model", 1)) as local, \
                mock.patch.object(E, "_ask_openrouter") as hosted, contextlib.redirect_stdout(io.StringIO()):
            result = E.expand_article(self.page, provider="ollama")
        local.assert_called_once()
        hosted.assert_not_called()
        self.assertEqual(result.provider, "ollama")

    def test_unknown_provider(self):
        with self.assertRaises(E.ExpandError):
            E.expand_article(self.page, provider="bing")

    def test_page_without_article(self):
        stub = write(self.root / "stub.md", "---\ntitle: x\n---\n")
        with self.assertRaises(E.ExpandError):
            E.expand_article(stub)

    def test_page_too_long(self):
        huge = write(self.root / "huge.md", "x " * (E.MAX_BODY_CHARS // 2 + 10))
        with self.assertRaises(E.ExpandError) as ctx:
            E.expand_article(huge)
        self.assertIn("too long", str(ctx.exception))

    def test_missing_page(self):
        with self.assertRaises(E.ExpandError):
            E.expand_article(self.root / "nope.md")

    def test_empty_answer_is_an_error(self):
        with mock.patch.object(E, "_ask_openrouter", return_value=("<think>x</think>", "m", 1)):
            with self.assertRaises(E.ExpandError):
                E.expand_article(self.page, save=False)

    def test_bad_output_folder_fails_before_asking_the_model(self):
        bad = SimpleNamespace(expand_output_dir=self.root / "site" / "content" / "x", hugo_root=self.root / "site",
                              expand_provider="openrouter", model_query="m", openrouter_model="o")
        with mock.patch.object(E, "get_settings", return_value=bad), mock.patch.object(E, "_ask_openrouter") as ask:
            with self.assertRaises(E.ExpandError):
                E.expand_article(self.page)
        ask.assert_not_called()

    def test_openrouter_errors_become_expand_errors(self):
        def boom(*a, **k):
            raise openrouter.OpenRouterError("No OpenRouter API key found.")

        with mock.patch("openrouter.call_openrouter", side_effect=boom), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(E.ExpandError) as ctx:
                E.expand_article(self.page, save=False)
        self.assertIn("API key", str(ctx.exception))

    def test_openrouter_wiring(self):
        with mock.patch("openrouter.call_openrouter", return_value=(self.expanded, "vendor/m")) as call, \
                contextlib.redirect_stdout(io.StringIO()):
            result = E.expand_article(self.page, model="vendor/m", temperature=0.2, save=False)
        self.assertEqual(call.call_args.kwargs["prompt"], "expand_article")
        self.assertEqual(call.call_args.kwargs["model"], "vendor/m")
        self.assertEqual(call.call_args.kwargs["temperature"], 0.2)
        self.assertEqual(result.model, "vendor/m")


class Prompts(unittest.TestCase):
    def test_expand_article_is_a_selectable_prompt(self):
        self.assertIn("expand_article", mymessages.available_prompts())
        self.assertEqual({"query_expand", "check_proof", "expand_article"} - set(mymessages.available_prompts()), set())

    def test_the_helpers_are_not_listed_as_prompts(self):
        for name in ("available_prompts", "resolve_prompt", "sys"):
            self.assertNotIn(name, mymessages.available_prompts())

    def test_prompt_says_what_you_asked(self):
        text = mymessages.expand_article["content"]
        for phrase in ("fully rewritten, highly expanded, and polished", "copy and paste directly", "placeholders", "every single step"):
            self.assertIn(phrase, text)

    def test_resolve(self):
        self.assertIs(mymessages.resolve_prompt("expand_article"), mymessages.expand_article)
        own = {"role": "system", "content": "x"}
        self.assertIs(mymessages.resolve_prompt(own), own)
        with self.assertRaises(ValueError) as ctx:
            mymessages.resolve_prompt("nope")
        self.assertIn("expand_article", str(ctx.exception))
        with self.assertRaises(ValueError):
            mymessages.resolve_prompt({"role": "system"})


class FakeResponse:
    ok = True
    status_code = 200
    text = "{}"

    def __init__(self, content="Answer", model="vendor/model:free"):
        self._data = {"choices": [{"message": {"content": content}}], "model": model}

    def json(self):
        return self._data


class CallOpenRouter(unittest.TestCase):
    def setUp(self):
        settings = SimpleNamespace(openrouter_model="vendor/default", openrouter_timeout=123.0, openrouter_max_tokens=4000)
        for target, kwargs in (("myconfig.get_settings", {"return_value": settings}), ("openrouter.get_api_key", {"return_value": "k"})):
            p = mock.patch(target, create=True, **kwargs)
            p.start()
            self.addCleanup(p.stop)

    def post(self, response=None):
        return mock.patch("openrouter.requests.post", return_value=response or FakeResponse())

    def test_payload_uses_the_named_prompt_and_the_settings(self):
        with self.post() as post:
            text, model = openrouter.call_openrouter("My article", prompt="expand_article")
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["model"], "vendor/default")
        self.assertEqual(body["messages"][0], {"role": "system", "content": mymessages.expand_article["content"]})
        self.assertEqual(body["messages"][1], {"role": "user", "content": "My article"})
        self.assertEqual(body["max_tokens"], 4000)
        self.assertEqual(body["temperature"], 0.7)
        self.assertEqual(post.call_args.kwargs["timeout"], 123.0)
        self.assertEqual((text, model), ("Answer", "vendor/model:free"))

    def test_arguments_override_the_settings(self):
        with self.post() as post:
            openrouter.call_openrouter("x", model="other/model", timeout=5, max_tokens=10, temperature=0)
        kw = post.call_args.kwargs
        self.assertEqual(kw["json"]["model"], "other/model")
        self.assertEqual(kw["json"]["max_tokens"], 10)
        self.assertEqual(kw["json"]["temperature"], 0)
        self.assertEqual(kw["timeout"], 5)

    def test_api_key_goes_in_the_header_only(self):
        with self.post() as post:
            openrouter.call_openrouter("x")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer k")
        self.assertNotIn("k", str(post.call_args.kwargs["json"]).replace("max_tokens", "").replace("task", ""))

    def test_thinking_is_stripped(self):
        with self.post(FakeResponse("<think>secret reasoning</think>\nFinal")):
            text, _ = openrouter.call_openrouter("x")
        self.assertEqual(text, "Final")

    def test_bad_arguments(self):
        with self.assertRaises(ValueError):
            openrouter.call_openrouter("   ")
        with self.assertRaises(ValueError):
            openrouter.call_openrouter("x", prompt="no_such_prompt")
        with self.assertRaises(ValueError):
            openrouter.call_openrouter("x", temperature=5)
        with self.assertRaises(ValueError):
            openrouter.call_openrouter("x" * (openrouter.MAX_CONTENT_CHARS + 1))

    def test_http_error_becomes_openrouter_error(self):
        bad = FakeResponse()
        bad.ok, bad.status_code = False, 429
        with self.post(bad):
            with self.assertRaises(openrouter.OpenRouterError) as ctx:
                openrouter.call_openrouter("x")
        self.assertIn("rate limit", str(ctx.exception))

    def test_ask_openrouter_without_options_sends_neither(self):
        with self.post() as post:
            openrouter.ask_openrouter("hi")
        body = post.call_args.kwargs["json"]
        self.assertNotIn("temperature", body)
        self.assertNotIn("max_tokens", body)

    def test_cli_with_a_system_prompt(self):
        with self.post() as post, contextlib.redirect_stdout(io.StringIO()) as out:
            code = openrouter.cli(["Hello", "--system", "check_proof"])
        self.assertEqual(code, 0)
        self.assertEqual(post.call_args.kwargs["json"]["messages"][0]["content"], mymessages.check_proof["content"])
        self.assertIn("Model used", out.getvalue())

    def test_cli_unknown_system_prompt_is_a_clean_error(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(openrouter.cli(["Hello", "--system", "nope"]), 1)
        self.assertIn("unknown prompt", err.getvalue())


if __name__ == "__main__":
    unittest.main()


class RetryWhenNoAnswer(unittest.TestCase):
    """A free model that gives no answer is asked again after EXPAND_RETRY_WAIT seconds."""

    def setUp(self):
        self.settings = SimpleNamespace(openrouter_model="openrouter/free", expand_retries=2, expand_retry_wait=300.0)
        for p in (mock.patch.object(E, "get_settings", return_value=self.settings),
                  mock.patch.object(E, "_sleep")):
            p.start()
            self.addCleanup(p.stop)
        self.sleeps = E._sleep
        self.out = contextlib.redirect_stdout(io.StringIO())
        self.out.__enter__()
        self.addCleanup(self.out.__exit__, None, None, None)

    def ask(self, side_effect):
        with mock.patch("openrouter.call_openrouter", side_effect=side_effect) as call:
            try:
                return E._ask_openrouter("body", None, None), call
            except E.ExpandError as exc:
                return exc, call

    def test_empty_then_answer_waits_five_minutes_once(self):
        result, call = self.ask([openrouter.OpenRouterError("empty", retryable=True), ("good text", "m:free")])
        self.assertEqual(result, ("good text", "m:free", 2))
        self.assertEqual(call.call_count, 2)
        self.assertEqual(sum(c.args[0] for c in self.sleeps.call_args_list), 300)  # 5 minutes in total

    def test_blank_text_counts_as_no_answer(self):
        result, call = self.ask([("   ", "m"), ("real", "m")])
        self.assertEqual(result[2], 2)

    def test_gives_up_after_the_retries(self):
        error = openrouter.OpenRouterError("busy", retryable=True)
        result, call = self.ask([error, error, error])
        self.assertIsInstance(result, E.ExpandError)
        self.assertEqual(call.call_count, 3)  # 1 + EXPAND_RETRIES
        self.assertIn("gave up", str(result))
        self.assertEqual(sum(c.args[0] for c in self.sleeps.call_args_list), 600)

    def test_a_wrong_key_is_not_retried(self):
        result, call = self.ask([openrouter.OpenRouterError("HTTP 401", retryable=False, status=401)])
        self.assertIsInstance(result, E.ExpandError)
        self.assertEqual(call.call_count, 1)
        self.sleeps.assert_not_called()

    def test_retries_can_be_switched_off(self):
        self.settings.expand_retries = 0
        result, call = self.ask([openrouter.OpenRouterError("busy", retryable=True)])
        self.assertIsInstance(result, E.ExpandError)
        self.assertEqual(call.call_count, 1)

    def test_openrouter_marks_what_is_worth_retrying(self):
        self.assertTrue({429, 503, 504} <= openrouter.RETRYABLE_STATUS)
        self.assertFalse({400, 401, 402, 403, 404} & openrouter.RETRYABLE_STATUS)


class _Resp:
    """A response with any status and JSON payload."""

    def __init__(self, status=200, payload=None):
        self.status_code = status
        self.ok = status < 400
        self._payload = payload if payload is not None else {}
        self.text = str(self._payload)

    def json(self):
        return self._payload


class OpenRouterAnswers(unittest.TestCase):
    """ask_openrouter marks free-model failures as retryable."""

    def setUp(self):
        p = mock.patch("openrouter.get_api_key", return_value="k")
        p.start()
        self.addCleanup(p.stop)

    def run_with(self, response):
        with mock.patch("openrouter.requests.post", return_value=response):
            try:
                return openrouter.ask_openrouter("hello"), None
            except openrouter.OpenRouterError as exc:
                return None, exc

    def test_empty_content_is_retryable(self):
        _, exc = self.run_with(_Resp(payload={"choices": [{"message": {"content": ""}}], "model": "m"}))
        self.assertTrue(exc.retryable)
        _, exc = self.run_with(_Resp(payload={"choices": [{"message": {"content": None}}], "model": "m"}))
        self.assertTrue(exc.retryable)

    def test_error_object_in_a_200_is_retryable(self):
        _, exc = self.run_with(_Resp(payload={"error": {"message": "Provider returned error", "code": 502}}))
        self.assertTrue(exc.retryable)
        self.assertIn("Provider returned error", str(exc))

    def test_http_statuses(self):
        for status, expected in ((429, True), (503, True), (401, False), (402, False)):
            _, exc = self.run_with(_Resp(status=status, payload={"error": {"message": "x"}}))
            self.assertEqual(exc.retryable, expected, status)
            self.assertEqual(exc.status, status)

    def test_a_good_answer_passes(self):
        result, exc = self.run_with(_Resp(payload={"choices": [{"message": {"content": "hi"}}], "model": "m"}))
        self.assertEqual(result, ("hi", "m"))
