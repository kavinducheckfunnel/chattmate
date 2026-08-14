/*
Copyright 2024-2026 ChatterMate

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

Console-only icons, in the same stroke style as the tenant app's NAV_ICONS so
the two never look like they came from different products. Kept separate rather
than added to that set because nothing outside the console draws them.
*/

import { NAV_ICONS } from '@/components/layout/navIcons'

const CONSOLE_ICONS: Record<string, string> = {
  overview: '<rect x="3" y="3" width="7.5" height="7.5" rx="1.6"/><rect x="13.5" y="3" width="7.5" height="7.5" rx="1.6"/><rect x="3" y="13.5" width="7.5" height="7.5" rx="1.6"/><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.6"/>',
  plans: '<path d="M12 3 21 12l-9 9-9-9z"/><circle cx="12" cy="12" r="2.6"/>',
  billing: '<rect x="2.5" y="5" width="19" height="14" rx="2.5"/><line x1="2.5" y1="9.5" x2="21.5" y2="9.5"/><line x1="6" y1="14.5" x2="10" y2="14.5"/>',
  health: '<path d="M2.5 12h4L9 6.5 12.5 18l2.5-6h6.5"/>',
  backups: '<path d="M20.5 12a8.5 8.5 0 1 1-2.6-6.1"/><path d="M20.5 4v5h-5"/>',
  audit: '<line x1="4" y1="7" x2="20" y2="7"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="17" x2="14" y2="17"/>',
  dollar: '<line x1="12" y1="3" x2="12" y2="21"/><path d="M16.5 7.2A4 4 0 0 0 13 5.5h-1.6a3.2 3.2 0 0 0 0 6.4h1.2a3.3 3.3 0 0 1 0 6.6H11a4 4 0 0 1-3.5-1.8"/>',
  trend: '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
  message: '<path d="M20 4H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3v4l4.5-4H20a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2z"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><line x1="15.3" y1="15.3" x2="21" y2="21"/>',
  download: '<path d="M12 3v12"/><path d="m7.5 10.5 4.5 4.5 4.5-4.5"/><path d="M4 20h16"/>',
  plus: '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
  edit: '<path d="M4 20h4.5L20 8.5a2.5 2.5 0 0 0-3.5-3.5L5 16.5z"/><line x1="14.5" y1="6.5" x2="18" y2="10"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7"/>',
  alert: '<circle cx="12" cy="12" r="9"/><line x1="12" y1="7.5" x2="12" y2="13"/><circle cx="12" cy="16.5" r=".7" fill="currentColor"/>',
  info: '<circle cx="12" cy="12" r="9"/><line x1="12" y1="11" x2="12" y2="16.5"/><circle cx="12" cy="7.6" r=".7" fill="currentColor"/>',
  shield: '<path d="M12 3l7.5 3v5.5c0 4.6-3.1 8.4-7.5 9.5-4.4-1.1-7.5-4.9-7.5-9.5V6z"/>',
  ban: '<circle cx="12" cy="12" r="8.5"/><line x1="6" y1="6" x2="18" y2="18"/>',
  external: '<path d="M14 4h6v6"/><path d="M20 4 11 13"/><path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4"/>',
  menu: '<line x1="4" y1="7" x2="20" y2="7"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="17" x2="20" y2="17"/>',
  cloud: '<path d="M7 18.5a4.5 4.5 0 0 1-.4-9 6 6 0 0 1 11.5 1.6A3.9 3.9 0 0 1 17.5 18.5z"/>',
  key: '<circle cx="8" cy="14" r="4.5"/><path d="m11.4 11.2 8-8"/><path d="m16.5 6.1 2.4 2.4"/><path d="m18.9 3.7 2 2"/>',
}

const ALL: Record<string, string> = { ...NAV_ICONS, ...CONSOLE_ICONS }

const cache = new Map<string, string>()

/**
 * Inline SVG string for `v-html`. Strokes use currentColor so an icon takes the
 * colour of whatever it sits in — muted in a resting nav row, accent when active.
 */
export const pfIcon = (name: string, size = 18): string => {
  const key = `${name}:${size}`
  let svg = cache.get(key)
  if (!svg) {
    svg = `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${ALL[name] || ''}</svg>`
    cache.set(key, svg)
  }
  return svg
}
