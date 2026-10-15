# Fortune Dataset — 53 divination engines + Gemini report pipeline

[日本語](README.md)

A Python package and Kaggle Notebook that computes **53 kinds of divination** deterministically
from a person's birth data and name, asks the Google Gemini API for the written readings, and
bundles everything into a **single HTML report with images**. All astronomical / calendrical
computation is done without an LLM and is reproducible. The reports are written in Japanese.

- Calculation engines in `fortunelib/` (Four Pillars, Western astrology, Zi Wei Dou Shu, I Ching, numerology, name analysis, ...)
- Report pipeline: Stage A (one reading per divination) → Stage B (cluster summaries) → Stage C (axis summaries and final synthesis) → Stage D (three readable tones)
- Image decks shipped with the dataset (tarot, runes, omikuji, Chinese zodiac, ...) plus charts drawn at run time
- A Kaggle Notebook (8 cells) and a CPU-only self-test suite
- Input is one CSV file (several people at once, with optional partner data for compatibility readings)

> **Divination is entertainment and a tool for reflection.** The generated texts are not medical,
> legal or financial advice and nothing here guarantees accuracy or future events.

## License

| Scope | License |
|---|---|
| Python code, Notebook, tests, scripts | [GNU AGPL-3.0](LICENSE) |
| Image decks created for this project, intro video, prompts, this project's own data | [CC BY 4.0](LICENSE-ASSETS) |
| Third-party data (KANJIDIC2 CC BY-SA 4.0, Unihan, the 1954/55 Japanese Colloquial Bible, fonts under OFL 1.1, public-domain tarot scans, ...) | [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) |

The code is AGPL because the dependency pyswisseph (Swiss Ephemeris) is AGPL-3.0.

**Trademarks**: "Gene Keys", "Human Design", "動物占い" and "六星占術" are trademarks or registered
trademarks of their respective owners. This project is not affiliated with or endorsed by them; the
names are used only to identify the kind of divination. All calculations and interpretations are this
project's own implementation.

## The 53 divinations

| Group | Divinations |
|---|---|
| G1 Birth date (14) | Sun sign, Chinese zodiac, Nine Star Ki, birth-date numerology, Tantric numerology, Anka Shastra, blood type, 動物占い (animal fortune), 六星占術, Weton, Primbon (Javanese), power stones, omikuji, Gene Keys |
| G2 Name (4) | Seimei handan (kanji stroke analysis), name numerology, Kabbalah numerology, Chaldean numerology |
| G3 Charts (8) | Four Pillars (BaZi), Western astrology, natal chart, transits, Vedic astrology, Zi Wei Dou Shu, Sanmeigaku, Human Design |
| G4 Cards and oracles (13) | I Ching, Liu Yao, Mei Hua Yi Shu, Qi Men Dun Jia, tarot, Tarot de Marseille, Lenormand, Kipper, oracle cards, angel cards, cartomancy, modern tarot + astrology, runes |
| G5 Compatibility (2) | Synastry, Parimicham |
| G6 Symbols and ancient methods (12) | Christian meditation (Bible verses), crystal healing, crystal ball, pendulum, talisman, traditional African cowrie divination, haruspicy, Mesopotamian celestial omens, Delphic oracle, ornithomancy, astragalomancy, "Top 10 deities connected to you" |

Definitions live in `fortune_dataset/fortunelib/registry.py` (slug, prompt id, required inputs).
Blood type, the name-based group and the two compatibility methods only run when the CSV provides
the corresponding input.

## How it works

```
people.csv ──▶ Stage A  52 individual readings (calculation → prompt → two Gemini Flash-Lite lanes)
               Stage B  11 cluster reports (5 on the "method" axis + 6 on the "culture" axis)
               Stage C  2 axis summaries → final synthesis → top-10 deities
               Stage D  readable versions in 3 tones (standard / easy / spiritual)
           ──▶ output/<person_id>/  Markdown, JSON and one self-contained HTML with embedded images
```

`fortune_dataset/data/model_plan.json` is the single source of truth for model assignment
(lanes, fallbacks, timeouts). See [docs/architecture.md](docs/architecture.md) (Japanese).

## Quick start on Kaggle

1. Add this repository as a Kaggle Dataset (ZIP of the repository) or Add Input the published dataset
2. Import `fortune_dataset/kaggle/fortune_notebook.ipynb` as a Notebook (accelerator **None**)
3. Register `GOOGLE_API_KEY` (a Gemini API key) under **Add-ons → Secrets** — it is the only secret needed
4. Run the cells in order: **Cell 0 (bootstrap) → Cell 0.1 (self-test) → Cell 1 (CSV input + Stage A) → Cell N2 (Stage B/C/D + HTML)**
5. Results are written to `/kaggle/working/output/<person_id>/` (`<person_id>_report.html` and more)

Details and the CSV columns: [docs/kaggle_setup.md](docs/kaggle_setup.md).

## Running locally

```bash
git clone https://github.com/jack4andmanastalk-byte/FortuneTelling.git
cd FortuneTelling
bash verify/env_setup.sh            # installs sxtwl, pyswisseph, iztro-py, ...
cd fortune_dataset && python3 -m pytest -q tests && cd ..
python3 tools/demo_local_html.py --out demo_out   # builds the HTML with dummy text, no API calls
```

To call Gemini locally, set the environment variable `GOOGLE_API_KEY` and use
`fortunelib.mts.run_person_mts` (Notebook cells 1 and N2 are the reference implementation).
Never put API keys in code or logs.

## Repository layout

| Path | Contents |
|---|---|
| `fortune_dataset/fortunelib/` | calculation engines, prompt assembly, MTS pipeline, tone rewriting, HTML report |
| `fortune_dataset/data/` | divination data, prompts (`prompts.json`), model plan (`model_plan.json`), version stamp (`dataset_version.json`), image mapping (`image_mapping.json`) |
| `fortune_dataset/kaggle/` | the Notebook, its cell sources, `build_notebook.py`, sample input `people_sample.csv` |
| `fortune_dataset/assets/` | image decks (`images/`), subset fonts (`fonts/`), intro video (`video/`) |
| `fortune_dataset/tests/` | pytest suite (the Kaggle self-test runs the same tests) |
| `tools/` | distribution ZIP build/verify, Notebook regeneration, dictionary and font builders, local demo, text checker |
| `verify/` | dependency installer, image checksums, image-matching audit, run-output verifier |
| `docs/` | architecture, Kaggle setup, data sources, images (Japanese) |

Counts (divinations, tests, decks, notebook cells) are defined in `fortune_dataset/data/dataset_version.json`.

## Contributing

Run the checks in [CONTRIBUTING.md](CONTRIBUTING.md) (pytest, compileall, Notebook sync check,
distribution ZIP verification) before opening a pull request. History: [CHANGELOG.md](CHANGELOG.md).
