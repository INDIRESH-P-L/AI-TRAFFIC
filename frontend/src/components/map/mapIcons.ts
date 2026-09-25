/**
 * TRAFFICINTEL AI - Map Marker Glyphs
 *
 * Leaflet's `divIcon` takes a raw HTML string, not a React element, so the
 * per-layer icons already chosen for the map legend (`LAYER_META` in
 * OperationsMap.tsx) cannot be dropped in directly. This module renders the
 * same glyphs as inline SVG markup instead.
 *
 * The path data below is copied verbatim from the installed lucide-react
 * icons (git-commit, triangle-alert, camera, radio, cloud, bus) rather than
 * approximated, so a marker on the map is visually identical to its entry in
 * the legend - an operator learns the shape once and it means the same thing
 * everywhere. Copied rather than rendered through `react-dom/server` to avoid
 * pulling React's server-rendering code into the client bundle for six static
 * shapes that never change at runtime.
 */

import type { LayerId } from './OperationsMap';

const GLYPH_INNER: Record<LayerId, string> = {
  // git-commit: a hub with two stubs, reading as "a point on the network".
  junctions:
    '<circle cx="12" cy="12" r="3"/><line x1="3" y1="12" x2="9" y2="12"/><line x1="15" y1="12" x2="21" y2="12"/>',

  // triangle-alert
  incidents:
    '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/>' +
    '<path d="M12 9v4"/><path d="M12 17h.01"/>',

  // camera
  cameras:
    '<path d="M13.997 4a2 2 0 0 1 1.76 1.05l.486.9A2 2 0 0 0 18.003 7H20a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h1.997a2 2 0 0 0 1.759-1.048l.489-.904A2 2 0 0 1 10.004 4z"/>' +
    '<circle cx="12" cy="13" r="3"/>',

  // radio (concentric signal arcs)
  sensors:
    '<path d="M16.247 7.761a6 6 0 0 1 0 8.478"/><path d="M19.075 4.933a10 10 0 0 1 0 14.134"/>' +
    '<path d="M4.925 19.067a10 10 0 0 1 0-14.134"/><path d="M7.753 16.239a6 6 0 0 1 0-8.478"/>' +
    '<circle cx="12" cy="12" r="2"/>',

  // cloud
  weather: '<path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/>',

  // bus
  transit:
    '<path d="M8 6v6"/><path d="M15 6v6"/><path d="M2 12h19.6"/>' +
    '<path d="M18 18h3s.5-1.7.8-2.8c.1-.4.2-.8.2-1.2 0-.4-.1-.8-.2-1.2l-1.4-5C20.1 6.8 19.1 6 18 6H4a2 2 0 0 0-2 2v10h3"/>' +
    '<circle cx="7" cy="18" r="2"/><path d="M9 18h5"/><circle cx="16" cy="18" r="2"/>',
};

/**
 * Renders a layer's glyph as a standalone `<svg>` markup string, sized and
 * stroked for embedding in a Leaflet divIcon.
 *
 * `strokeWidth` widens automatically at small sizes: lucide's default 2px
 * stroke all but disappears once the whole icon is under ~14px on screen, and
 * a marker whose icon cannot be read at the console's default zoom is not an
 * improvement over the plain dot it replaces.
 */
export function renderLayerGlyph(
  layerId: LayerId,
  sizePx: number,
  color: string,
): string {
  const strokeWidth = sizePx <= 14 ? 2.75 : sizePx <= 20 ? 2.25 : 2;
  return (
    `<svg width="${sizePx}" height="${sizePx}" viewBox="0 0 24 24" fill="none" ` +
    `stroke="${color}" stroke-width="${strokeWidth}" stroke-linecap="round" ` +
    `stroke-linejoin="round" aria-hidden="true">${GLYPH_INNER[layerId]}</svg>`
  );
}
