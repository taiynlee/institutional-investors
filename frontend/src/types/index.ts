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
  lending_5d_chg: number
  score: number
  dip_bonus: number
  holders_bonus: number
  appearances_5d: number
  streak: number
}

export interface ResultRow {
  code: string
  name: string
  tags: string
  score: number
  dip_bonus: number
  holders_bonus: number
  streak: number
  prev_close: number
  close: number
  chg_pct: number
}

export interface ResultData {
  pred_date: string | null
  price_date: string | null
  rows: ResultRow[]
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
