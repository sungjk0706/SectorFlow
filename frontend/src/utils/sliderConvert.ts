/** 서버값(0.0~1.0) → 화면값(0~100) */
export function toDisplayValue(v: number): number {
  return Math.round(v * 100)
}

/** 화면값(0~100) → 서버값(0.0~1.0) */
export function toServerValue(v: number): number {
  return v / 100
}
