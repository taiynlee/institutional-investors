export interface ScreenerResult {
  code: string
  name: string
  calc_date: string
  tags: string[]
  bb_position: number
  bb_peak: number
  peak_days_ago: number
  is_squeeze: boolean
  vol_ratio: number
  foreign_6d_net: number
  trust_6d_net: number
  chip_ratio_6d: number
  chip_ratio_12d: number
  margin_5d_chg: number
  score: number
}

export interface DataStatus {
  date: string
  jobs: { name: string; status: string; rows: number }[]
  is_reliable: boolean
}
