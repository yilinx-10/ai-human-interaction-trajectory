<script>
  import { beliefFilter } from '../../stores.js'

  const DATES = [
    '2026-03-27','2026-03-30','2026-04-02','2026-04-03',
    '2026-04-04','2026-04-10','2026-04-15','2026-04-16',
    '2026-04-18','2026-04-19','2026-04-20','2026-04-21','2026-04-22',
  ]
  const fmt = d => {
    const [, m, day] = d.split('-')
    const mon = ['','Jan','Feb','Mar','Apr','May'][+m]
    return `${mon} ${+day}`
  }

  let startIdx = 0
  let endIdx = DATES.length - 1

  function update() {
    if (startIdx > endIdx) [startIdx, endIdx] = [endIdx, startIdx]
    beliefFilter.set({ startIdx, endIdx })
  }
</script>

<div class="slider-wrap">
  <span class="label">Filter by date:</span>
  <div class="range-row">
    <span class="date">{fmt(DATES[startIdx])}</span>
    <div class="sliders">
      <input type="range" min="0" max={DATES.length - 1} bind:value={startIdx} on:input={update} />
      <input type="range" min="0" max={DATES.length - 1} bind:value={endIdx}   on:input={update} />
    </div>
    <span class="date">{fmt(DATES[endIdx])}</span>
  </div>
  <span class="count">
    {$beliefFilter.endIdx - $beliefFilter.startIdx + 1} of {DATES.length} dates
  </span>
</div>

<style>
  .slider-wrap {
    position: absolute;
    bottom: 16px;
    left: 50%;
    transform: translateX(-50%);
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 10px 18px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    z-index: 10;
  }
  .label { font-size: 0.72rem; color: var(--text-muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; }
  .range-row { display: flex; align-items: center; gap: 10px; }
  .date { font-size: 0.78rem; color: var(--text); min-width: 50px; text-align: center; }
  .sliders { display: flex; flex-direction: column; gap: 4px; }
  input[type="range"] {
    width: 180px;
    accent-color: var(--accent);
  }
  .count { font-size: 0.7rem; color: var(--text-muted); }
</style>
