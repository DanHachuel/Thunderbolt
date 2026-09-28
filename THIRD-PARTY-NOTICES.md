# Third-party notices

## Niche-Finder

Thunderbolt adapts the data-analysis ideas and parts of the clustering/tag-association logic from [johanfortus/Niche-Finder](https://github.com/johanfortus/Niche-Finder), Copyright (c) 2024 Johan Fortus and Vincent Milland. The original project is licensed under the MIT License. Thunderbolt does not include the original Flask server, HTML templates, JavaScript/D3 visualizations or route layer; the functionality was adapted to the existing Streamlit process.

> Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## yt-dlp

Thunderbolt depends on and embeds the Python API of [yt-dlp](https://github.com/yt-dlp/yt-dlp) for public media downloads. yt-dlp is distributed under [The Unlicense](https://github.com/yt-dlp/yt-dlp/blob/master/LICENSE), subject to the notices and licensing information maintained by the upstream project. This dependency is separate from Thunderbolt's MIT License.

## ytmusicapi

Thunderbolt depends on [sigma67/ytmusicapi](https://github.com/sigma67/ytmusicapi) for the optional YouTube Music browser-authenticated music-upload workflow. Consulte a licença MIT, os avisos e as condições de distribuição mantidos no projecto upstream. Esta dependência é separada da licença MIT do Thunderbolt.

## Pushtunes

Thunderbolt depends on [Psy-Q/pushtunes](https://pypi.org/project/pushtunes/) for the optional library-synchronisation workflow between local Subsonic/Jellyfin/CSV sources and Spotify, YouTube Music or Tidal. Pushtunes is distributed under the GNU Affero General Public License v3.0 or later; this notice does not change Thunderbolt's own licence and users should consult the complete upstream licence and notices before redistributing the combined runtime.

## JewelMusic SDK

The JewelMusic upload adapter follows the documented HTTP contract and API examples from [jewelmusic/sdk](https://github.com/jewelmusic/sdk), which is published under the MIT License. The Python package `jewelmusic-sdk` was not available on PyPI at implementation time, so Thunderbolt does not bundle that unavailable package; the adapter uses the documented `POST /v1/tracks/upload` request directly and retains attribution to the upstream SDK repository.

## supabase-py

Thunderbolt optionally depends on [supabase-py](https://github.com/supabase/supabase-py) for the AI Influencers Supabase backend. The package is distributed under the MIT License. The SQLite backend uses Python's standard library and does not require a remote service.

## bilibili-api-python

Thunderbolt depends optionally on [bilibili-api-python](https://pypi.org/project/bilibili-api-python/) for the Bilibili video-upload adapter. The package is distributed under the GNU General Public License v3 or later and its upstream repository [Nemo2011/bilibili-api](https://github.com/Nemo2011/bilibili-api) was archived and announced as closed on 2026-07-06. This dependency is separate from Thunderbolt's MIT License; consult the complete upstream licence and use the integration only with accounts and content you are authorised to operate.

## social-auto-upload

Thunderbolt installs the upstream `social-auto-upload` CLI from the pinned source snapshot `dreammis/social-auto-upload` commit `0012d2c355f88f683cc38dde2a2db209e14091bc`; the source is installed as a Python runtime dependency and is not vendored into the npm archive. The upstream project is distributed under the MIT License, Copyright (c) 2023 dreammis. The MIT permission notice and warranty disclaimer in the upstream `LICENSE` apply to that dependency and remain separate from Thunderbolt's own licence.

## Playwright
Thunderbolt optionally depends on [Playwright for Python](https://playwright.dev/python/) to open the DistroKid upload form and load local tracks. The adapter does not submit the final form automatically. Playwright's own licence and browser distribution terms remain applicable.

## musikai
The DistroKid workflow is conceptually adapted from [igolaizola/musikai](https://github.com/igolaizola/musikai), an MIT-licensed Go project. Thunderbolt does not bundle musikai or its Go binaries; only the documented browser-assisted upload concept and metadata flow are adapted.
