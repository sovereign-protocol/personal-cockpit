# Changelog

## 0.1.0a1 - unreleased

- All producer mutations now cross versioned Kanban/Agreement facades through
  Personal Cockpit-owned controller routes; the UI no longer calls producer
  HTTP namespaces.
- Local portfolio state now uses its Session application metadata namespace.
- Core retired the direct HTTP channel. No production change was needed here
  - the Cockpit reads perspectives and never routed anything itself - and a
  peer is now named by its publication identity (`relay:…`) rather than a URL
  wherever one is shown.
- **Fixed: boards off the right-hand edge could not be reached.** The board
  row was sized as `100vh` minus a guessed top-bar height, so it finished a
  scrollbar's width past the bottom of the window - taking its own horizontal
  scrollbar with it. Narrowing the window hid tiles with no way to scroll to
  them. The page is now one viewport tall, with the bar taking what it needs
  and the row taking the rest.
- Agreement tiles carry the same controls as board tiles: move, enlarge,
  share and settings, over a count of divergences and agenda items.
  Enlarging an agreement shows the whole document, read-only; enlarging a
  board still opens its bands.
- Agreements can be deleted, from the same gear icon that deletes a board.
- Creating an agreement leaves you in the Cockpit, as creating a board
  already did, instead of jumping into the new document.
- Board tiles show their agenda-item count beside the divergence count, and
  name divergences as such rather than as "discussion".
- Initial standalone Personal Cockpit with optional S-Kanban facade adapter.
