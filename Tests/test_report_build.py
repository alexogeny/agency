import re
import subprocess
import struct
import tempfile
import textwrap
import unittest
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_BUILD = ROOT / "Tools/report-build"
SCRATCH = Path.home() / "Scratch"


class ReportBuildApaTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.project = Path(self.temporary.name)
        (self.project / "sections").mkdir()
        (self.project / "assets").mkdir()
        self.write_png(self.project / "assets/figure.png")
        (self.project / "sections/body.md").write_text(
            textwrap.dedent(
                """\
                # Findings

                {cite: {ids: [WEB_ALPHA], mode: narrative}} establishes the first rule.
                The second rule follows {cite: {ids: [WEB_BETA], mode: parenthetical}}.
                The guide remains distinct {cite: {ids: [GUIDE], mode: parenthetical}}.
                The article-number evidence is reported {cite: {ids: [ARTICLE], mode: parenthetical}}.
                The page-range evidence is reported {cite: {ids: [PAGES], mode: parenthetical}}.
                The report supplies context {cite: {ids: [REPORT], mode: parenthetical}}.
                Structured groups are sorted {cite: {ids: [ARTICLE, REPORT, WEB_ALPHA], mode: parenthetical}}.
                Pandoc groups are sorted [@ARTICLE; @REPORT; @WEB_ALPHA].
                The fixture appears in {@fig:fixture}.
                """
            )
        )
        (self.project / "sections/appendix.md").write_text(
            "# Appendix\n\nSupporting material.\n\n"
            "![Two-pixel fixture.](assets/figure.png){#fig:fixture width=25%}\n"
        )
        self.write_index("apa-7")
        self.write_references("apa-7")

    def tearDown(self):
        self.temporary.cleanup()

    def write_png(self, path):
        def chunk(kind, value):
            return (
                struct.pack(">I", len(value))
                + kind
                + value
                + struct.pack(">I", zlib.crc32(kind + value) & 0xFFFFFFFF)
            )

        header = struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)
        pixels = b"\x00\xff\x99\xcc\xff\x99\xcc\x00\xff\x99\xcc\xff\x99\xcc"
        path.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(pixels))
            + chunk(b"IEND", b"")
        )

    def write_index(self, citation_style):
        (self.project / "index.md").write_text(
            textwrap.dedent(
                f"""\
                ---
                schema_version: 2
                title: APA test report
                assessment: Test assessment
                cover_page: {{enabled: true}}
                identities:
                  - {{name: Taylor Example, identifier: n1234567, role: Student}}
                required_identity_fields: [name, identifier]
                institution:
                  name: Example University
                  course: TST101 - Testing Reports
                required_institution_fields: [name, course]
                presentation: {{font_size_pt: 11}}
                citation_style: {citation_style}
                citation_markup:
                  id_source: {{path: references.md, field: id}}
                sections:
                  - {{id: body, order: 1, path: sections/body.md}}
                  - {{id: references, order: 2, path: references.md, include_in_word_count: false}}
                  - {{id: appendix, order: 3, path: sections/appendix.md, include_in_word_count: false}}
                ---
                """
            )
        )

    def write_references(self, citation_style):
        records = """
        ## WEB_BETA

        ```yaml
        id: WEB_BETA
        type: corporate_author_webpage
        authors:
          - {literal: Example Agency}
        issued: {year: 2025, month: 6, day: 4}
        title: Beta guidance
        publisher: Example Agency
        url: https://example.test/beta
        retrieved: {year: 2026, month: 8, day: 27}
        apa7_plain: FLAT BETA PREVIEW
        verified: true
        ```

        ## ARTICLE

        ```yaml
        id: ARTICLE
        type: journal_article
        authors:
          - {family: Smith, given: Alice}
          - {family: Brown, given: Bailey}
          - {family: Chen, given: Casey}
        issued: {year: 2024}
        title: An article-number study
        container_title: Journal of Testing
        volume: "12"
        issue: "3"
        article_number: e42
        doi: doi:10.1234/example.42
        apa7_plain: FLAT ARTICLE PREVIEW
        verified: true
        ```

        ## REPORT

        ```yaml
        id: REPORT
        type: government_report
        authors:
          - {literal: Government Department}
        issued: {year: 2023, month: 9}
        title: Annual evidence report
        publisher: Government Department
        url: https://example.test/report
        apa7_plain: FLAT REPORT PREVIEW
        verified: true
        ```

        ## WEB_ALPHA

        ```yaml
        id: WEB_ALPHA
        type: corporate_author_webpage
        authors:
          - {literal: Example Agency}
        issued: {year: 2025, month: 1, day: 2}
        title: Alpha guidance
        publisher: Example Agency
        url: https://example.test/alpha
        retrieved: {year: 2026, month: 8, day: 27}
        apa7_plain: FLAT ALPHA PREVIEW
        verified: true
        ```

        ## PAGES

        ```yaml
        id: PAGES
        type: journal_article
        authors:
          - {family: Jones, given: Jordan}
        issued: {year: 2022}
        title: A page-range study
        container_title: Review Quarterly
        volume: "7"
        pages: {first: 10, last: 19}
        url: https://example.test/pages
        apa7_plain: FLAT PAGES PREVIEW
        verified: true
        ```

        ## GUIDE

        ```yaml
        id: GUIDE
        type: government_guide
        authors:
          - {literal: Example Agency}
        issued: {year: 2026}
        title: Gamma guide
        version: "1.0"
        publisher: Example Agency
        url: https://example.test/guide
        apa7_plain: FLAT GUIDE PREVIEW
        verified: true
        ```
        """
        (self.project / "references.md").write_text(
            f"---\nschema_version: 2\ncitation_style: {citation_style}\n"
            f"title: References\nrecord_encoding: yaml\n---\n{textwrap.dedent(records)}"
        )

    def run_report(self, *arguments):
        return subprocess.run(
            [str(REPORT_BUILD), *arguments],
            cwd=self.project,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

    def build_html_and_tex(self):
        html_result = self.run_report("build", ".", "--format", "html")
        self.assertEqual(html_result.returncode, 0, html_result.stdout)
        tex_result = self.run_report("build", ".", "--format", "tex")
        self.assertEqual(tex_result.returncode, 0, tex_result.stdout)
        return (
            (self.project / "build/report.html").read_text(),
            (self.project / "build/report.tex").read_text(),
        )

    def test_structured_apa_rendering_and_citation_years(self):
        rendered_html, rendered_tex = self.build_html_and_tex()
        self.assertIn(
            "<em>Journal of Testing</em>, <em>12</em>(3), Article e42.",
            rendered_html,
        )
        self.assertIn(
            "<em>Review Quarterly</em>, <em>7</em>, 10–19.", rendered_html
        )
        self.assertIn("https://doi.org/10.1234/example.42", rendered_html)
        self.assertIn("Example Agency (2025a)", rendered_html)
        self.assertIn(">Example Agency, 2025b</a>)", rendered_html)
        self.assertIn(">Example Agency, 2026</a>)", rendered_html)
        self.assertNotIn("2026a", rendered_html)
        self.assertIn("Example Agency. (2025a, January 2).", rendered_html)
        self.assertIn("Example Agency. (2025b, June 4).", rendered_html)
        self.assertIn("Government Department. (2023).", rendered_html)
        self.assertIn("<em>Gamma guide (Version 1.0)</em>.", rendered_html)
        self.assertNotIn("<em>Gamma guide</em>. (Version 1.0).", rendered_html)
        ordered_group = (
            "Example Agency, 2025a; Government Department, 2023; "
            "Smith et al., 2024"
        )
        plain_html = re.sub(r"<[^>]+>", "", rendered_html)
        self.assertEqual(plain_html.count(ordered_group), 2)
        self.assertNotIn(
            "<em>Annual evidence report</em>. Government Department.", rendered_html
        )
        self.assertNotIn("FLAT", rendered_html)
        self.assertIn(
            r"\emph{Journal of Testing}, \emph{12}(3), Article e42.",
            rendered_tex,
        )
        self.assertIn(r"\emph{Review Quarterly}, \emph{7}, 10–19.", rendered_tex)
        self.assertIn(r"\emph{Gamma guide (Version 1.0)}.", rendered_tex)
        plain_tex = re.sub(
            r"\\hyperlink\{[^}]+\}\{([^{}]+)\}", r"\1", rendered_tex
        )
        self.assertEqual(plain_tex.count(ordered_group), 2)
        self.assertNotIn("FLAT", rendered_tex)

    def test_order_hanging_indent_and_reference_section_position(self):
        rendered_html, rendered_tex = self.build_html_and_tex()
        ordered_ids = [
            "ref-WEB_ALPHA",
            "ref-WEB_BETA",
            "ref-GUIDE",
            "ref-REPORT",
            "ref-PAGES",
            "ref-ARTICLE",
        ]
        positions = [rendered_html.index(f'id="{value}"') for value in ordered_ids]
        self.assertEqual(positions, sorted(positions))
        self.assertIn(
            ".references li { margin: 0 0 .8rem 1.2cm; text-indent: -1.2cm; }",
            rendered_html,
        )
        self.assertLess(
            rendered_html.index("<h2>References</h2>"),
            rendered_html.index(">Appendix</h2>"),
        )
        self.assertIn(r"\begin{hangparas}{1.2cm}{1}", rendered_tex)
        self.assertLess(
            rendered_tex.index(r"\section*{References}"),
            rendered_tex.index(r"\section{Appendix}"),
        )

    def test_native_pdf_build_embeds_fonts_and_links(self):
        result = self.run_report("build", ".", "--format", "pdf")
        self.assertEqual(result.returncode, 0, result.stdout)
        rendered_pdf = (self.project / "build/report.pdf").read_bytes()
        self.assertTrue(rendered_pdf.startswith(b"%PDF-1.7"))
        self.assertGreater(len(rendered_pdf), 100_000)
        self.assertIn(b"/CMUSerif-Italic", rendered_pdf)
        self.assertIn(b"/Subtype /Link", rendered_pdf)
        self.assertIn(b"/Subtype /Image", rendered_pdf)

    def test_native_pdf_repeats_table_header_after_page_break(self):
        rows = "\n".join(
            f"| Row {position} | Evidence item {position} | Recorded outcome {position} |"
            for position in range(1, 81)
        )
        (self.project / "sections/body.md").write_text(
            "# Findings\n\nThe records appear in {@tbl:long-table}.\n\n"
            "| Repeated header | Evidence header | Outcome header |\n"
            "| --- | --- | --- |\n"
            f"{rows}\n\n"
            "Table: A table long enough to cross a page boundary. {#tbl:long-table}\n"
        )
        result = self.run_report("build", ".", "--format", "pdf")
        self.assertEqual(result.returncode, 0, result.stdout)
        extracted = subprocess.run(
            ["pdftotext", "-layout", "build/report.pdf", "-"],
            cwd=self.project,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(extracted.returncode, 0, extracted.stdout)
        self.assertGreaterEqual(extracted.stdout.count("Repeated header"), 2)

    def test_cover_page_is_unnumbered_and_body_numbering_starts_at_one(self):
        result = self.run_report("build", ".", "--format", "pdf")
        self.assertEqual(result.returncode, 0, result.stdout)
        rendered_pdf = (self.project / "build/report.pdf").read_bytes()
        page_count = rendered_pdf.count(b"/Type /Page ")
        streams = re.findall(b"stream\n(.*?)\nendstream", rendered_pdf, re.DOTALL)
        decoded_streams = []
        for stream in streams:
            try:
                decoded_streams.append(zlib.decompress(stream))
            except zlib.error:
                continue
        footer_pattern = re.compile(
            rb"BT /F1 [0-9.]+ Tf 0 0 0 rg 1 0 0 1 [0-9.]+ 35\.433 Tm <[0-9A-F]+> Tj ET"
        )
        page_streams = [stream for stream in decoded_streams if b"BT /F" in stream]
        self.assertEqual(len(page_streams), page_count)
        self.assertIsNone(footer_pattern.search(page_streams[0]))
        self.assertTrue(all(footer_pattern.search(stream) for stream in page_streams[1:]))

    def test_cover_sections_and_institution_render_in_html_and_tex(self):
        rendered_html, rendered_tex = self.build_html_and_tex()
        self.assertIn('<section class="cover-page">', rendered_html)
        self.assertIn("<h2 class=\"cover-label cover-author-label\">Author</h2>", rendered_html)
        self.assertIn("Taylor Example · n1234567 · Student", rendered_html)
        self.assertIn("<h2 class=\"cover-label\">Institution</h2>", rendered_html)
        self.assertIn("Example University", rendered_html)
        self.assertIn("TST101 - Testing Reports", rendered_html)
        self.assertIn(r"\begin{titlepage}", rendered_tex)
        self.assertIn(r"\thispagestyle{empty}", rendered_tex)
        self.assertIn(r"\setcounter{page}{1}", rendered_tex)

    def test_cover_page_can_be_omitted(self):
        index = (self.project / "index.md").read_text().replace(
            "cover_page: {enabled: true}", "cover_page: false"
        )
        (self.project / "index.md").write_text(index)
        rendered_html, rendered_tex = self.build_html_and_tex()
        self.assertNotIn('class="cover-page"', rendered_html)
        self.assertNotIn(r"\begin{titlepage}", rendered_tex)
        result = self.run_report("build", ".", "--format", "pdf")
        self.assertEqual(result.returncode, 0, result.stdout)
        rendered_pdf = (self.project / "build/report.pdf").read_bytes()
        page_count = rendered_pdf.count(b"/Type /Page ")
        streams = re.findall(b"stream\n(.*?)\nendstream", rendered_pdf, re.DOTALL)
        footer_pattern = re.compile(rb" 35\.433 Tm <[0-9A-F]+> Tj ET")
        footers = 0
        for stream in streams:
            try:
                footers += len(footer_pattern.findall(zlib.decompress(stream)))
            except zlib.error:
                continue
        self.assertEqual(footers, page_count)

    def test_decimal_font_and_compact_two_column_profile_render_exactly(self):
        configured = textwrap.dedent(
            """\
            presentation:
              profile: compact
              font_size_pt: 9.2
              margins_mm: {top: 14, right: 13, bottom: 16, left: 15}
              line_height: 1.3
              paragraph_spacing_pt: 2
              heading_spacing_pt: {before: 5, after: 2}
              caption_spacing_pt: {before: 2, after: 3}
              title: {alignment: right, size_pt: 17.5, top_margin_mm: 18}
              columns: 2
              column_gap_mm: 6
            """
        )
        index_path = self.project / "index.md"
        index = index_path.read_text().replace(
            "presentation: {font_size_pt: 11}\n", configured
        )
        index_path.write_text(index)
        rendered_html, rendered_tex = self.build_html_and_tex()
        self.assertIn("font: 9.2pt/1.3", rendered_html)
        self.assertIn("margin: 14mm 13mm 16mm 15mm", rendered_html)
        self.assertIn("column-count: 2", rendered_html)
        self.assertIn("column-gap: 6mm", rendered_html)
        self.assertIn("margin: 0 0 2pt", rendered_html)
        self.assertIn("font-size: 17.5pt; text-align: right", rendered_html)
        self.assertIn(r"\documentclass[10pt,a4paper]{article}", rendered_tex)
        self.assertIn(r"\fontsize{9.2}{11.96}\selectfont", rendered_tex)
        self.assertIn(r"\setlength{\columnsep}{6mm}", rendered_tex)
        self.assertIn(r"\twocolumn", rendered_tex)
        self.assertIn(r"\onecolumn", rendered_tex)
        result = self.run_report("build", ".", "--format", "pdf")
        self.assertEqual(result.returncode, 0, result.stdout)
        streams = re.findall(
            b"stream\n(.*?)\nendstream",
            (self.project / "build/report.pdf").read_bytes(),
            re.DOTALL,
        )
        decoded = []
        for stream in streams:
            try:
                decoded.append(zlib.decompress(stream))
            except zlib.error:
                continue
        self.assertTrue(any(b"/F1 9.2 Tf" in stream for stream in decoded))

    def test_uncited_reference_source_does_not_emit_references_section(self):
        (self.project / "sections/body.md").write_text(
            "# Findings\n\nNo external sources are cited.\n"
        )
        rendered_html, rendered_tex = self.build_html_and_tex()
        self.assertNotIn("<h2>References</h2>", rendered_html)
        self.assertNotIn(r"\section*{References}", rendered_tex)

    def test_academic_outputs_are_monochrome_and_use_typesetting_fonts(self):
        rendered_html, rendered_tex = self.build_html_and_tex()
        self.assertIn('"CMU Serif", "Computer Modern", serif', rendered_html)
        self.assertIn(":root { color: #000; background: #fff;", rendered_html)
        self.assertIn("section p { margin:", rendered_html)
        self.assertIn("text-align: justify;", rendered_html)
        self.assertNotIn("ReportPurple", rendered_tex)
        self.assertNotIn("colorlinks=true", rendered_tex)
        self.assertIn(r"\usepackage{lmodern}", rendered_tex)

    def test_unsupported_citation_style_is_rejected(self):
        self.write_index("vancouver")
        self.write_references("vancouver")
        result = self.run_report("check", ".")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported citation_style: vancouver", result.stdout)

    def test_conflicting_citation_style_is_rejected(self):
        self.write_references("chicago-author-date")
        result = self.run_report("check", ".")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "conflicting citation_style: index uses apa-7, reference database uses chicago-author-date",
            result.stdout,
        )


if __name__ == "__main__":
    unittest.main()
