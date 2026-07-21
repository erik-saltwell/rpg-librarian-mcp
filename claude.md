# RPG-Librarian
## Role and Goal
You are a librarian and expert coder. Your job is to help me organize my digital archive of RPG related content.  This content includes things like:
* Rulebooks, adventrures, supplements
* GM advice
* Maps and map collections
* audio files for creating sound tracks and sournd effects
* Handouts 
* 3d models of miniatures, props and terrain
* An extensive library of travel guides used as setting books for modern day earth settings
These files have a bunch of formats:
* image files
* audio files
* pdfs and other text formats like modi, ebook, docx, txt...
* 3d models like .stl and .lys
These files currently live at c:\rpg.  
In c:\rpg is a folder called .catalog that currently has metadata about the library:
* the index.json file lists every file (called a catalog item) along with metadata about the item.
* there is a text fragments directory that has ocr'd text for pdf files.  Each file in that directory has a filename that links to the item of the item in the catalog (aka index.json)
Our goal is to get them all organized with metadata in order to make the lirbrary more usable.

## Target Organization Scheme
Our goal is to organize this content into the following structure:
* Place all content into c:\rpg_organized
* content is first organized into a set of top level folders under c:\rpg_organized based on the system they are a part of.  System agnostic content is organized into a folder called 'system agnostic'.  Other content is placed into a folder with the name of the system.
* System agnostic content is organized into a three tier hierarchy:
  * the first tier is the media type (media type is in the catalog entry metadata)
  * the second tier is the name of the publisher.   If the publisher is unknown it is placed in a 'misc' folder
  * third tier is the product name.   See below for a definition of product.  
* System specific content is classified by content role and then product:
  * Content roles are one of:
      * Core Rules
	  * Adventures and scenarios
	  * Settings and Supplements
	  * GM and Player Aids
	  * Extras
  * Inside of role, the content is classified by product (see definition below)
  
### Definition of product
A product is a collection of content that is sold or distributed as a unit.  This is intended to be the regular, everyday meaning of the word.  It is important that some products are single files (like a pdf rulebook) and some are a collection.   The multiple files may have multiple media types, for example an adventure may include a pdf book and a collection of maps or handouts.

## Current Organization
The current collection, located at c:\rpg, is only loosely organized, with many organization errors and no seperation of products.

# Current Structure of c:\rpg

Snapshot date: 2026-07-15. Describes the folder structure as it exists today, before reorganization into `c:\rpg_organized`. This is a structural/pattern description, not an exhaustive path listing — for the precise inventory of ~14,200 directories and ~76,000 files, see `.catalog\index.json` (excluded from this document; it is the librarian tool's own metadata store, not library content).

Total: 5 top-level content branches, no loose files at the `c:\rpg` root.

| Branch | Dirs | Files |
|---|---:|---:|
| `DriveThruRPG\` | 2,407 | 13,635 |
| `Maps\` | 754 | 4,861 |
| `audio\` | 380 | 14,938 |
| `books\` | 1,778 | 19,985 |
| `stl\` | 8,874 | 22,869 |

---

## `DriveThruRPG\`
**Pattern:** `DriveThruRPG\<Publisher>\<Product>\...`
This is the store of all content I have purchased on DriveThruRPG

- Tier 1 (227 folders): publisher name, matching DriveThruRPG's own vendor names (e.g. `Chaosium`, `Kobold Press`, `Free League Publishing`).
- Tier 2 (1,126 folders): one folder per purchased product, e.g. `DriveThruRPG\Chaosium\Petersen's Abominations`.
- Tier 3+ (1,053 folders below that): varies by product. Simple products are a flat pile of PDFs in the tier-2 folder. Larger products add subfolders for their own parts, e.g. `...\Petersen's Abominations\Petersen's Abominations Character Sheets\` holding dozens of pre-generated character PDFs.
- No files sit directly under a publisher folder (tier 1) — every product is in its own tier-2 folder. This is the cleanest, most consistent branch in the library and maps closely onto the "product" concept in the target org scheme, with publisher already captured as metadata.

## `books\`
**Pattern:** inconsistent — two competing organizational schemes coexist.
PDF and other text content
- `books\5eDnD\` — a D&D 5e-specific tree, subdivided by **content type** (`Adventures`, `Bestiary`, `Core Manuals`, `Magazines`, `Maps`, `NPCs`, `PC Options`, `Settings`, `Spells`, `3rd_Party_Supplements`, humble-bundle dumps, etc.). 18 subfolders.
- `books\Systems\` — a general "one folder per game system" tree (130+ systems: `Call of Cthulhu`, `Blades in the Dark`, `Shadowrun`, `Pathfinder`, `FATE`, etc., 1,377 dirs total below it). Depth and internal organization vary wildly per system: some are a flat pile of PDFs (`Call of Cthulhu\`), some have sub-genre folders (`Call Of Cthulu\CoC 1890s\`, `...\CoC_7th_ed\`), some have content-type subfolders. There is also a `books\Systems\5eDnD\` — organized by content type again but with a different, only partially overlapping set of subfolders than top-level `books\5eDnD\` (`Dark Sun`, `OneDnD`, `Prerelease Packet`, `ultimate`, etc.).
- `books\Generic\` — system-agnostic material, subdivided by content type (`Adventures`, `Monsters`, `NPCs`, `Maps`, `Fonts`, `Conlanging`) plus a set of underscore-prefixed design-guide folders (`_AdventureDesign`, `_DungeonDesign`, `_EncounterDesign`, `_SettingDesign`, `_Treasure`, `_WorldDesign`).
- `books\GM Advice\` - system agnostic GM advicce
- `books\Ken Writes About Stuff\` The ken writes about stuff line of content.  most of them are playable in Gumshoe GAMES, 
- `books\Indie Bundle Of Holding\` — a collection of indie core rulebooks, that are each their own product

## `audio\`
**Pattern:** `audio\<pack-name>\...`, mostly one folder per purchased sound/music pack (32 packs), each internally organized by the vendor's own scheme (e.g. `80ssynthwavefusion\80s SYNTHWAVE Fusion\01.FULL TRACKS\`, `02.BUILDING BLOCKS\`, `03.BONUS\`).
Sound effects and soundtracks
- `audio\audio\` — a nested folder that is itself a flat collection of ~19 more music packs (`Dark Fantasy Studio - ...`), i.e. one extra unnecessary level of nesting relative to its siblings.
- `audio\Open Ocean\` — a single pack, capitalized/spaced differently from the all-lowercase-no-spaces naming used by most other pack folders (`epicorchestralactionmusicpack`, `retrosfxsoundpack`, etc.), suggesting inconsistent extraction/import naming over time.

## `Maps\`
**Pattern:** inconsistent, mixes raw vendor asset packs with pre-built map sets.

- `Maps\Dynamic Dungeons\` — one subfolder per encounter/location map set (110+ subfolders, e.g. `GOBLIN_CAVE_LN`, `WIZARDSTOWER`), each a self-contained product.
- `Maps\Dungendraft\` — Dungeondraft map-editor asset/source packs, organized by asset source/vendor (`Sourcesets`, `Two minute tabletop`, `Saltworks`, etc.), not by finished map.
- `Maps\BattlfinderAm\` — flat pile of `.ai`/`.pdf` source files, no subfolders.
- `Maps\Modern City\` maps usable in modern day city environments
- `Maps\Duskvol\` — A single product containing maps of the city of duskvol used in Blades in the dark
- `Maps\Dungeond_Draft_Maps\` — a separate, similarly-named folder to `Dungendraft\`, apparent duplicate/overlap in naming intent.

## `stl\`
**Pattern:** inconsistent; largest branch by directory count (8,874 dirs, dominated by miniature part folders).

- `stl\Loot\` stl files acquired by participating in Loot's Patreon, 
- `stl\Dragons Rest\` stl files made by publisher Dragons Rest 
- `stl\STL Miniatures\` — one folder per miniature/character set (150+ sets), frequently duplicated as a `<Set>` / `<Set>_Supported` pair (unsupported vs. print-supported STL variants of the same product).
- `stl\3D Props\` — a flat list of ~50 individual prop/creature folders (`Goblin`, `Minotaur`, `Tavern Bar`, `Skeleton Construct`), each apparently its own small product rather than grouped under a purchased pack name.
- `stl\CastnPlay\` - stls made by publisher "Cast n Play" as part of their kickstarter, subdivided by the vendor's own tiers (`Core_Set`, `Stretch_Goals_Tier_1..5`), reflecting Kickstarter reward-tier structure rather than product content.
- `stl\3D Printable Fantasy Props\` —  stls made by publisher "3D Printable Fantasy Props" as part of their kickstarter, subdivided by the vendor's own tiers (`Core_Set`, `Stretch_Goals_Tier_1..5`), reflecting Kickstarter reward-tier structure rather than product content.
- `stl\Terrain\` - my own collection of stl files i use as part of my own custom terrain set.
- `stl\Miniature Holder\` — a single product

---

## Inconsistencies and anomalies to resolve before/during reorganization

1. **`books\5eDnD\` vs `books\Systems\5eDnD\`** — two separate, partially-overlapping D&D 5e trees at different points in the hierarchy. Content type folders differ between them (e.g. `Dark Sun`, `OneDnD` only exist under `Systems\5eDnD\`). Needs a merge decision.
2. **Spelling/casing variants of the same system** — `books\Systems\Call of Cthulhu\` vs `books\Systems\Call Of Cthulu\` (missing "h", different capitalization) are almost certainly meant to be one system folder.
3. **`audio\audio\`** — an extra, redundant nesting level containing ~19 packs that logically belong alongside their siblings directly under `audio\`.
4. **`Maps\Dungendraft\` vs `Maps\Dungeond_Draft_Maps\`** — similarly-named folders, likely duplicate/overlapping intent, need reconciliation.
5. **`audio\potrace-1.16.win64\`** — this is the Potrace bitmap-tracing command-line utility (an `.exe` tool with license files), not an audio asset. Appears to be stray, non-library software mixed into the content tree.
6. **`DriveThruRPG\cone of negative energy\`** — lowercase publisher name, inconsistent with the title-case convention used by all 226 other publisher folders (likely a typo/manual entry rather than the vendor's actual store name).
7. **`stl\STL Miniatures\` `<Set>` / `<Set>_Supported` pairs** — these are two variants of the same product (unsupported vs. presupported STL files), not two separate products; worth deciding whether they merge into one product folder with variant subfolders.
8. **No consistent "content role" or "media type" tiering** — none of the five branches currently reflect the target scheme's Core Rules / Adventures / Settings / GM Aids / Extras role split, or a clean system-agnostic vs. system-specific split. `books\Generic\` and `books\Systems\System Agnostic\` both hold system-agnostic content but at different tree positions.

---

# Other Important File Locations
- c:\proj\rpg-librarian: The old version of this project, we will be moving code from there into this mcp-first archirecture in this directory
- c:\rpg: This is the location of our current rpg digital archive
- /.planning/ - this location has files that describe our plan. It includes
  - /.planning/architecture-brainstorm.md - describes the architecture we are building
  - /.planning/current_structure.md - describes how c:\rpg is currently organized.