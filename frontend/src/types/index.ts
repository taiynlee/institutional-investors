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
  chip_ratio_1d: number
  chip_ratio_6d: number
  chip_ratio_12d: number
  chip_ratio_20d: number
  margin_5d_chg: number
  lending_5d_chg: number
  score_a: number
  score_b: number
  dip_bonus: number
  holders_bonus: number
  holders_w2?: number | null
  holders_w3?: number | null
  ma5_days: number
  upper_slope: number
  ma20_slope: number
  close_position: number
  change_pct: number
  appearances_5d: number
  streak: number
  ic_names?: string[]
  volume?: number
  rs_vs_market?: number
}

export interface ResultRow {
  code: string
  name: string
  tags: string
  score_a: number
  score_b: number
  dip_bonus: number
  holders_bonus: number
  streak: number
  bb_position: number
  chip_ratio_6d: number
  prev_close: number
  close: number
  chg_pct: number
  is_top_score: boolean
  is_ai_pick: boolean
}

export interface ResultDateItem {
  date: string
  hold_days: number
}

export interface ResultData {
  pred_date: string | null
  price_date: string | null
  win_count: number
  total_count: number
  rows: ResultRow[]
}

export interface ExitSignal {
  type: string
  label: string
  bb?: number
  peak_bb?: number
  chip_pct?: number
}

export interface ExitAlert {
  code: string
  name: string
  tags: string
  bb: number
  peak_bb: number
  chip_3d_pct: number | null
  last_seen_date: string
  days_off: number
  badges: { type: string; label: string }[]
  current_close: number | null
  chg_since_last: number | null
}

export interface JobStatus {
  name: string
  schedule: string
  status: string
  rows: number
  updated_at: string | null
}

export interface DataSourceInfo {
  label: string
  source: string
  via: string
  rows?: number
  latest_date?: string | null
}

export interface DataStatus {
  date: string
  jobs: JobStatus[]
  is_reliable: boolean
  data_sources: Record<string, DataSourceInfo>
}

export interface SectorFlow {
  sector: string
  net: number
  stock_count: number
}

export interface WatchlistAItem {
  id: number
  code: string
  name: string
  added_date: string
  added_close: number
  added_bb_position: number
  added_score_a: number
  status: string
  triggered_date: string | null
  triggered_close: number | null
  triggered_bb_position: number | null
  current_close: number | null
  current_bb: number | null
  chg_pct: number | null
  chg_basis: 'triggered' | 'added'
}

export interface ScoreCResult {
  calc_date: string
  code: string
  name: string
  score_c: number
  rev_yoy: number
  rev_mom: number
  rev_month: number
  rev_year: number
  eps_q1: number | null
  eps_q2: number | null
  eps_q3: number | null
  eps_q4: number | null
}

export interface IcChainGroup {
  ic_code: string
  ic_name: string
  ic_parent: string | null
  companies: { code: string; name: string; ic_node: string | null }[]
}

export interface HolderRow {
  code: string
  name: string
  sector: string
  report_date: string
  holders: number
  pct: number
  pct_400_lot: number | null
  prev_holders: number | null
  prev_pct: number | null
  holders_chg: number | null
  pct_chg: number | null
}
