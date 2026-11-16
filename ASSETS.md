# Assets and attribution

This inventory records sources and notices bundled with the project. Per-file
and adventure-manifest declarations remain the reference for redistribution.
Original developer: **Jean Schmitz**. Fork creator and maintainer: **Anton Kuprin**.

## Branding and story artwork

- The fork owner's [VisualNovel PNG](docs/branding/visualnovel.png) is the default
  source for desktop icons in [build_desktop.py](scripts/build_desktop.py).
  The login screen uses its copy under
  [frontend branding assets](frontend/src/assets/branding/visualnovel.png).
  The repository also retains the [JPG](docs/branding/visualnovel.jpg).
- The original asset notes credit Black Forest Labs FLUX and OpenAI image APIs
  for generated imagery and Recraft for assisted vector work. These tool names
  identify production methods; they do not establish a universal public-domain
  license for every image. Consult the containing adventure and individual notices.
- Shipped default/sample adventure archives declare **CC BY-NC 4.0** in their
  manifests. The [combat test adventure](adventures/default/combat_test_adventure.adv)
  declares **MIT** and credits Antigravity. Community packages can declare other
  licenses; catalog installation and compatible export retain their attribution.
- Account-avatar fallbacks request DiceBear's `avataaars` style. These are external
  runtime requests, rather than a bundled collection of NPC portraits. Use the
  [DiceBear style documentation](https://www.dicebear.com/styles/avataaars/) for
  attribution and style-specific terms. NPC portraits use the configured image
  providers and task workflows.

Generated session art and uploaded user images retain their own provenance.
The code license does not replace an image provider's terms or an uploaded asset's
individual notice.

## Icons and browser libraries

- **Lucide:** [bundled ISC / MIT notice](frontend/public/assets/licenses/lucide-vue-next-LICENSE.txt).
- **RPG Awesome:** [bundled upstream notice](frontend/public/assets/fonts/licenses/RPG-AWESOME-LICENSE.md)
  is BSD 2-Clause, copyright 2014 Daniela Howe. Component headers and font metadata
  contain differing MIT/OFL notices. Preserve those notices rather than treating
  this summary as a replacement license for the font, CSS or individual artwork.
- Other shipped browser-library notices are listed in
  [licenseCatalog.ts](frontend/src/utils/licenseCatalog.ts) and bundled under
  [assets/licenses](frontend/public/assets/licenses). The portal's **Licenses**
  window displays those local texts.

## Fonts

The following families ship local license texts under **SIL Open Font License 1.1**:

| Family | Bundled notice |
| --- | --- |
| Acme | [ACME-LICENSE.txt](frontend/public/assets/fonts/licenses/ACME-LICENSE.txt) |
| Newsreader | [NEWSREADER-LICENSE.txt](frontend/public/assets/fonts/licenses/NEWSREADER-LICENSE.txt) |
| Orbitron | [ORBITRON-LICENSE.txt](frontend/public/assets/fonts/licenses/ORBITRON-LICENSE.txt) |
| Press Start 2P | [PRESS-START-2P-LICENSE.txt](frontend/public/assets/fonts/licenses/PRESS-START-2P-LICENSE.txt) |
| Alegreya Sans | [OFL.txt](frontend/public/assets/fonts/session/alegreya-sans/OFL.txt) |
| Baloo Bhaijaan 2 | [OFL.txt](frontend/public/assets/fonts/session/baloo-bhaijaan-2/OFL.txt) |
| M PLUS Rounded 1c | [OFL.txt](frontend/public/assets/fonts/session/m-plus-rounded-1c/OFL.txt) |
| Noto Sans SC | [OFL.txt](frontend/public/assets/fonts/session/noto-sans-sc/OFL.txt) |
| Noto Sans TC | [OFL.txt](frontend/public/assets/fonts/session/noto-sans-tc/OFL.txt) |
| Noto Sans KR | [OFL.txt](frontend/public/assets/fonts/session/noto-sans-kr/OFL.txt) |

See the [font-file index](frontend/public/assets/fonts/licenses/README.txt) and
[session-font guide](frontend/public/assets/fonts/session/README.md) for filenames,
script coverage and language-based selection. Keep the bundled copyright and OFL
texts with redistributed font files.

## License entry points

- [Code: MIT](LICENSE).
- [Adventure/story content: CC BY-NC 4.0](LICENSE-CC-BY-NC-4.0).
