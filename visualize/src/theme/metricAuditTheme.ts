/** Trait-axis palettes: score magnitude within a semantic family (not risk red/green). */

export type StrengthBand = 'VERY_LOW' | 'LOW' | 'MID' | 'HIGH' | 'VERY_HIGH'

export const STRENGTH_BANDS: StrengthBand[] = ['VERY_LOW', 'LOW', 'MID', 'HIGH', 'VERY_HIGH']

/** Index 0 = low score … 4 = high score — saturated enough to read on white UI */
export const TRAIT_PALETTES: Record<string, readonly string[]> = {
  dispersion: ['#6eb0d8', '#4a9fd0', '#2d86be', '#1a6fa8', '#0f558c'],
  concentration: ['#c9a06a', '#b3864f', '#9a6f3c', '#805a30', '#684826'],
  reuse: ['#b39fd4', '#9a82c4', '#8268b0', '#6a5296', '#564078'],
  hub_in: ['#6ec4b0', '#4aad94', '#35947c', '#287a66', '#1f6352'],
  hub_out: ['#a4c078', '#88a85c', '#709048', '#5c763a', '#4a6030'],
  asymmetry: ['#c0a4bc', '#a886a4', '#906e8c', '#765874', '#604660'],
  structure: ['#94a4b4', '#788a9c', '#607080', '#4c5c6e', '#3c4a58'],
  density: ['#72aac4', '#5494b0', '#407c98', '#326680', '#285268'],
  unidirectional: ['#b090cc', '#9874b8', '#805ea2', '#684a86', '#523a6c'],
  burst: ['#e0a858', '#cc8c38', '#b47424', '#965e1c', '#7c4c18'],
  time_spread: ['#68b0dc', '#4598d0', '#2a80b8', '#1868a0', '#0f5488'],
  time_concentration: ['#d09878', '#bc7c5c', '#a46448', '#885038', '#704030'],
  neutral: ['#a8a6a1', '#918f89', '#787672', '#605e59', '#4c4a46'],
}

export function scoreToPaletteIndex(score: number): number {
  const s = Math.max(0, Math.min(100, score))
  if (s < 20) return 0
  if (s < 40) return 1
  if (s < 60) return 2
  if (s < 80) return 3
  return 4
}

export function metricBarColor(traitAxis: string | undefined, score: number): string {
  const palette = TRAIT_PALETTES[traitAxis ?? 'neutral'] ?? TRAIT_PALETTES.neutral
  return palette[scoreToPaletteIndex(score)]
}

/** Darken hex ~12% for badge border */
function darkenHex(hex: string, factor = 0.85): string {
  const n = parseInt(hex.slice(1), 16)
  const r = Math.max(0, Math.min(255, Math.floor(((n >> 16) & 0xff) * factor)))
  const g = Math.max(0, Math.min(255, Math.floor(((n >> 8) & 0xff) * factor)))
  const b = Math.max(0, Math.min(255, Math.floor((n & 0xff) * factor)))
  return `#${((r << 16) | (g << 8) | b).toString(16).padStart(6, '0')}`
}

export function metricBadgeStyle(traitAxis: string | undefined, score: number): {
  background: string
  color: string
  border: string
} {
  const bg = metricBarColor(traitAxis, score)
  const useLightText = score >= 35
  return {
    background: bg,
    color: useLightText ? '#ffffff' : '#1f1f1f',
    border: `1px solid ${darkenHex(bg, 0.82)}`,
  }
}
